"""Deterministic horizon-quantile LightGBM with governed calibration and TreeSHAP."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Final

import numpy as np
import pandas as pd
from lightgbm import LGBMRegressor, early_stopping

from retail_ml.keys import SeriesKey
from retail_ml.models.confidence import forecast_confidence
from retail_ml.models.intermittent import croston_sba

NUMERIC_FEATURES: Final[tuple[str, ...]] = (
    "horizon",
    "origin_units",
    "weekly_units_equivalent",
    "week_index",
    "units_lag_1",
    "units_lag_4",
    "units_lag_13",
    "units_lag_52",
    "units_roll_mean_4",
    "units_roll_mean_8",
    "units_roll_mean_13",
    "units_roll_mean_52",
    "units_roll_std_4",
    "units_roll_std_8",
    "units_roll_std_13",
    "units_roll_std_52",
    "zero_share_52w",
    "demand_trend_4v13",
    "price_ratio_13w",
    "local_category_price_index",
    "iso_week",
    "week_sin",
    "week_cos",
    "event_count_origin",
    "working_days_origin",
    "working_days_horizon",
    "weather_tavg_origin",
    "weather_precip_origin",
    "weather_tavg_horizon",
    "weather_precip_horizon",
    "weather_fallback_used",
    "macro_index_value",
    "competitor_price_ratio",
    "competitor_available",
    "competitor_in_stock",
    "competitor_age_days",
    "origin_year",
)
CATEGORICAL_FEATURES: Final[tuple[str, ...]] = (
    "market_id",
    "store_id",
    "channel_id",
    "dept_id",
    "category",
    "sub_cat",
)
MODEL_FEATURES: Final[tuple[str, ...]] = NUMERIC_FEATURES + CATEGORICAL_FEATURES
DRIVER_FEATURE_GROUPS: Final[dict[str, frozenset[str]]] = {
    "demand_trend": frozenset(
        {
            "origin_units",
            "weekly_units_equivalent",
            "units_lag_1",
            "units_lag_4",
            "units_roll_mean_4",
            "units_roll_mean_8",
            "units_roll_std_4",
            "units_roll_std_8",
            "zero_share_52w",
            "demand_trend_4v13",
            "macro_index_value",
        }
    ),
    "seasonality": frozenset(
        {
            "horizon",
            "week_index",
            "origin_year",
            "units_lag_13",
            "units_lag_52",
            "units_roll_mean_13",
            "units_roll_mean_52",
            "units_roll_std_13",
            "units_roll_std_52",
            "iso_week",
            "week_sin",
            "week_cos",
            "market_id",
            "store_id",
            "channel_id",
            "dept_id",
            "category",
            "sub_cat",
        }
    ),
    "price": frozenset({"price_ratio_13w", "local_category_price_index"}),
    "competitor_activity": frozenset(
        {
            "competitor_price_ratio",
            "competitor_available",
            "competitor_in_stock",
            "competitor_age_days",
        }
    ),
    "weather_local_events": frozenset(
        {
            "working_days_origin",
            "working_days_horizon",
            "weather_tavg_origin",
            "weather_precip_origin",
            "weather_tavg_horizon",
            "weather_precip_horizon",
            "weather_fallback_used",
            "event_count_origin",
        }
    ),
}


@dataclass(frozen=True)
class CalibrationAdjustment:
    scope: str
    market_id: str | None
    horizon: int
    sufficient: bool
    fallback: bool
    n_series: int
    n_origins: int
    n_rows: int
    actual_sum: float
    p50_adjustment: float
    p90_adjustment: float
    raw_p50_coverage: float
    raw_p90_coverage: float


@dataclass(frozen=True)
class HorizonModel:
    horizon: int
    p50_model: LGBMRegressor
    p90_model: LGBMRegressor
    #: Decision #91. None when the cohort had too few training rows to fit its own head,
    #: in which case the shared head is used and `cold_start_head_fallback` records it, so
    #: an absent model is visible rather than looking like a deliberate choice.
    p90_cold_model: LGBMRegressor | None
    cold_start_head_rows: int
    categories: dict[str, tuple[str, ...]]
    global_calibration: CalibrationAdjustment
    market_calibrations: dict[str, CalibrationAdjustment]
    p50_best_iteration: int
    p90_best_iteration: int
    tail_preferred_keys: frozenset[SeriesKey]


@dataclass(frozen=True)
class HorizonModelSet:
    models: tuple[HorizonModel, ...]

    def for_horizon(self, horizon: int) -> HorizonModel:
        for model in self.models:
            if model.horizon == horizon:
                return model
        raise KeyError(f"no trained model for horizon {horizon}")

    @property
    def calibration_accepted(self) -> bool:
        return all(model.global_calibration.sufficient for model in self.models)

    def calibration_records(self) -> list[dict[str, Any]]:
        records: list[dict[str, Any]] = []
        for model in self.models:
            records.append(asdict(model.global_calibration))
            records.extend(asdict(value) for value in model.market_calibrations.values())
        return records


def _categories(frame: pd.DataFrame) -> dict[str, tuple[str, ...]]:
    return {
        column: tuple(
            sorted(frame[column].fillna("unknown").astype(str).unique().tolist())
        )
        for column in CATEGORICAL_FEATURES
    }


def prepare_model_frame(
    frame: pd.DataFrame,
    *,
    categories: dict[str, tuple[str, ...]],
) -> pd.DataFrame:
    prepared = frame.copy()
    for column in NUMERIC_FEATURES:
        if column not in prepared:
            prepared[column] = 0.0
        prepared[column] = pd.to_numeric(prepared[column], errors="coerce").fillna(0.0)
    for column in CATEGORICAL_FEATURES:
        if column not in prepared:
            prepared[column] = "unknown"
        prepared[column] = pd.Categorical(
            prepared[column].fillna("unknown").astype(str),
            categories=categories[column],
        )
    return prepared[list(MODEL_FEATURES)]


def _sufficiency(frame: pd.DataFrame) -> tuple[bool, int, int, int, float]:
    series = frame[["sku_id", "store_id", "channel_id"]].drop_duplicates()
    origins = pd.to_datetime(frame["forecast_origin"]).dt.date.nunique()
    actual_sum = float(pd.to_numeric(frame["target_units"], errors="coerce").sum())
    n_series = len(series)
    n_rows = len(frame)
    sufficient = (
        n_series >= 100
        and origins >= 8
        and n_rows >= 500
        and actual_sum > 0
    )
    return sufficient, n_series, int(origins), n_rows, actual_sum


def _coverage(actual: np.ndarray, predicted: np.ndarray) -> float:
    return float(np.mean(actual <= predicted)) if len(actual) else 0.0


def _adjustment(
    frame: pd.DataFrame,
    raw_p50: np.ndarray,
    raw_p90: np.ndarray,
    *,
    scope: str,
    market_id: str | None,
    horizon: int,
    fallback: bool,
) -> CalibrationAdjustment:
    sufficient, n_series, n_origins, n_rows, actual_sum = _sufficiency(frame)
    actual = pd.to_numeric(frame["target_units"], errors="coerce").to_numpy(dtype=float)
    p50_adjustment = float(np.quantile(actual - raw_p50, 0.50)) if sufficient else 0.0
    p90_adjustment = float(np.quantile(actual - raw_p90, 0.90)) if sufficient else 0.0
    return CalibrationAdjustment(
        scope=scope,
        market_id=market_id,
        horizon=horizon,
        sufficient=sufficient,
        fallback=fallback,
        n_series=n_series,
        n_origins=n_origins,
        n_rows=n_rows,
        actual_sum=actual_sum,
        p50_adjustment=round(p50_adjustment, 8),
        p90_adjustment=round(p90_adjustment, 8),
        raw_p50_coverage=round(_coverage(actual, raw_p50), 8),
        raw_p90_coverage=round(_coverage(actual, raw_p90), 8),
    )


#: Decision #91. A training row with no origin-visible lag-52 has no seasonal history, so
#: it is the training-side analogue of decision #82's cold-start cohort.
def _cold_start_training_mask(frame: pd.DataFrame) -> pd.Series:
    lag = pd.to_numeric(frame.get("units_lag_52"), errors="coerce")
    if lag is None:
        return pd.Series(False, index=frame.index)
    return lag.isna()


#: Below this the cohort-specific head is not fitted and the shared head is used, with the
#: fallback recorded. A quantile head fitted on a handful of rows is noise with a
#: confidence interval attached.
MIN_COLD_START_TRAINING_ROWS: Final[int] = 2_000


def _fit_pair(
    train: pd.DataFrame,
    calibration: pd.DataFrame,
    *,
    categories: dict[str, tuple[str, ...]],
    threads_per_model: int,
    seed: int,
) -> tuple[LGBMRegressor, LGBMRegressor, LGBMRegressor | None]:
    common: dict[str, Any] = {
        "objective": "quantile",
        "n_estimators": 400,
        "learning_rate": 0.04,
        "num_leaves": 47,
        "min_child_samples": 60,
        "subsample": 1.0,
        "colsample_bytree": 1.0,
        "reg_lambda": 0.1,
        "random_state": seed,
        "deterministic": True,
        "force_col_wise": True,
        "n_jobs": threads_per_model,
        "verbosity": -1,
    }
    p50 = LGBMRegressor(alpha=0.50, **common)
    p90 = LGBMRegressor(alpha=0.90, **common)
    fit_kwargs: dict[str, Any] = {
        "categorical_feature": list(CATEGORICAL_FEATURES)
    }
    if not calibration.empty:
        fit_kwargs["eval_X"] = prepare_model_frame(
            calibration,
            categories=categories,
        )
        fit_kwargs["eval_y"] = pd.to_numeric(
            calibration["target_units"],
            errors="coerce",
        ).fillna(0.0)
        fit_kwargs["callbacks"] = [early_stopping(30, verbose=False)]
    train_x = prepare_model_frame(train, categories=categories)
    train_y = pd.to_numeric(train["target_units"], errors="coerce").fillna(0.0)
    p50.fit(train_x, train_y, **fit_kwargs)
    p90.fit(train_x, train_y, **fit_kwargs)

    # Decision #91: a dedicated cold-start P90 head.
    #
    # Both heads above are fitted on one frame in which established-history rows
    # outnumber cold-start rows roughly six to one, so the shared P90 head learns
    # established dispersion and is then asked to bound a cohort whose spread is much
    # wider -- decision #84 measured the cold-start champion at std 93.66 against an
    # actual 132.54. Two post-hoc corrections were rejected for exactly that reason: C6
    # could not rescale a mis-shaped spread into the band, and C7's measured constant
    # offset per segment overshot on held-out data and cost 46.9% of displayed confidence.
    # Fitting the quantile on the cohort's own rows lets the width vary per row with the
    # features, instead of applying one number to a whole segment.
    #
    # P50 is deliberately NOT refitted per cohort. A1 non-inferiority, WAPE, bias and every
    # decision #77 display cell must stay unchanged by construction, not by measurement.
    cold_mask = _cold_start_training_mask(train)
    p90_cold: LGBMRegressor | None = None
    if int(cold_mask.sum()) >= MIN_COLD_START_TRAINING_ROWS:
        cold_kwargs: dict[str, Any] = {
            "categorical_feature": list(CATEGORICAL_FEATURES)
        }
        cold_calibration = calibration[_cold_start_training_mask(calibration)]
        if not cold_calibration.empty:
            cold_kwargs["eval_X"] = prepare_model_frame(
                cold_calibration, categories=categories
            )
            cold_kwargs["eval_y"] = pd.to_numeric(
                cold_calibration["target_units"], errors="coerce"
            ).fillna(0.0)
            cold_kwargs["callbacks"] = [early_stopping(30, verbose=False)]
        p90_cold = LGBMRegressor(alpha=0.90, **common)
        p90_cold.fit(train_x[cold_mask.to_numpy()], train_y[cold_mask], **cold_kwargs)
    return p50, p90, p90_cold


def _tail_replay_preferred_keys(
    frame: pd.DataFrame,
    calibration: pd.DataFrame,
    calibrated_p50: np.ndarray,
    *,
    minimum_rows: int = 8,
) -> frozenset[SeriesKey]:
    """Select intermittent routing only from origin-safe held-out replay."""

    calibration_replay = calibration[
        [
            "sku_id",
            "store_id",
            "channel_id",
            "forecast_origin",
            "target_units",
            "units_lag_52",
        ]
    ].copy()
    calibration_replay["lightgbm_p50"] = calibrated_p50
    calibration_replay["croston_p50"] = np.nan
    history = frame[
        [
            "sku_id",
            "store_id",
            "channel_id",
            "forecast_origin",
            "origin_units",
        ]
    ].copy()
    grouped_history = {
        tuple(str(value) for value in key): group.sort_values(
            "forecast_origin"
        )
        for key, group in history.groupby(
            ["sku_id", "store_id", "channel_id"],
            sort=False,
            observed=True,
        )
    }
    for index, row in calibration_replay.iterrows():
        key = (
            str(row["sku_id"]),
            str(row["store_id"]),
            str(row["channel_id"]),
        )
        series_history = grouped_history.get(key)
        if series_history is None:
            continue
        observed = series_history[
            pd.to_datetime(series_history["forecast_origin"])
            < pd.Timestamp(row["forecast_origin"])
        ]["origin_units"]
        if not observed.empty:
            calibration_replay.at[index, "croston_p50"] = croston_sba(observed)
    # Learn replay preference for every series with enough held-out evidence.
    # Intermittency is evaluated later, at the scored origin. Filtering the
    # historical replay by its then-current zero share creates a cold-start
    # hole when a series first crosses the slow-mover threshold.
    replay = calibration_replay[
        calibration_replay["croston_p50"].notna()
    ].copy()
    if replay.empty:
        return frozenset()
    replay["croston_error"] = (
        pd.to_numeric(replay["croston_p50"], errors="coerce")
        - pd.to_numeric(replay["target_units"], errors="coerce")
    ).abs()
    replay["lightgbm_error"] = (
        pd.to_numeric(replay["lightgbm_p50"], errors="coerce")
        - pd.to_numeric(replay["target_units"], errors="coerce")
    ).abs()
    replay["seasonal_error"] = (
        pd.to_numeric(replay["units_lag_52"], errors="coerce").fillna(0.0)
        - pd.to_numeric(replay["target_units"], errors="coerce")
    ).abs()
    grouped = replay.groupby(
        ["sku_id", "store_id", "channel_id"],
        sort=False,
        observed=True,
    ).agg(
        rows=("target_units", "size"),
        actual_units=("target_units", "sum"),
        croston_error=("croston_error", "sum"),
        lightgbm_error=("lightgbm_error", "sum"),
        seasonal_error=("seasonal_error", "sum"),
    )
    winners = grouped[
        (grouped["rows"] >= int(minimum_rows))
        & (grouped["actual_units"] > 0)
        & (grouped["croston_error"] <= grouped["lightgbm_error"])
        & (grouped["croston_error"] <= grouped["seasonal_error"])
    ]
    return frozenset(
        SeriesKey(str(sku), str(store), str(channel))
        for sku, store, channel in winners.index
    )


def fit_horizon_model(
    frame: pd.DataFrame,
    *,
    horizon: int,
    threads_per_model: int,
    seed: int = 20260730,
) -> HorizonModel:
    if frame.empty:
        raise ValueError(f"no training rows for horizon {horizon}")
    origins = sorted(pd.to_datetime(frame["forecast_origin"]).dt.date.unique())
    if len(origins) < 10:
        raise ValueError("at least 10 training origins are required")
    calibration_origins = set(origins[-8:])
    origin_values = pd.to_datetime(frame["forecast_origin"]).dt.date
    calibration = frame[origin_values.isin(calibration_origins)].copy()
    train = frame[~origin_values.isin(calibration_origins)].copy()
    categories = _categories(frame)
    p50, p90, p90_cold = _fit_pair(
        train,
        calibration,
        categories=categories,
        threads_per_model=threads_per_model,
        seed=seed + horizon,
    )
    calibration_x = prepare_model_frame(calibration, categories=categories)
    raw_p50 = np.clip(p50.predict(calibration_x), 0.0, None)
    raw_p90 = np.clip(p90.predict(calibration_x), 0.0, None)
    global_adjustment = _adjustment(
        calibration,
        raw_p50,
        raw_p90,
        scope="global",
        market_id=None,
        horizon=horizon,
        fallback=False,
    )
    market_adjustments: dict[str, CalibrationAdjustment] = {}
    for market, indices in calibration.groupby("market_id", observed=True).groups.items():
        positions = calibration.index.get_indexer(indices)
        market_frame = calibration.loc[indices]
        candidate = _adjustment(
            market_frame,
            raw_p50[positions],
            raw_p90[positions],
            scope="market",
            market_id=str(market),
            horizon=horizon,
            fallback=False,
        )
        if not candidate.sufficient:
            candidate = CalibrationAdjustment(
                **{
                    **asdict(candidate),
                    "fallback": True,
                    "p50_adjustment": global_adjustment.p50_adjustment,
                    "p90_adjustment": global_adjustment.p90_adjustment,
                }
            )
        market_adjustments[str(market)] = candidate
    calibrated_p50 = np.clip(
        raw_p50
        + np.array(
            [
                market_adjustments.get(
                    str(market),
                    global_adjustment,
                ).p50_adjustment
                for market in calibration["market_id"]
            ]
        ),
        0.0,
        None,
    )
    tail_preferred_keys = _tail_replay_preferred_keys(
        frame,
        calibration,
        calibrated_p50,
    )
    p50_best = int(p50.best_iteration_ or 400)
    p90_best = int(p90.best_iteration_ or 400)
    return HorizonModel(
        horizon=horizon,
        p50_model=p50,
        p90_model=p90,
        p90_cold_model=p90_cold,
        cold_start_head_rows=int(_cold_start_training_mask(train).sum()),
        categories=categories,
        global_calibration=global_adjustment,
        market_calibrations=market_adjustments,
        p50_best_iteration=p50_best,
        p90_best_iteration=p90_best,
        tail_preferred_keys=tail_preferred_keys,
    )


def score_horizon_model(frame: pd.DataFrame, model: HorizonModel) -> pd.DataFrame:
    result = frame.copy()
    prepared = prepare_model_frame(result, categories=model.categories)
    raw_p50 = np.clip(model.p50_model.predict(prepared), 0.0, None)
    raw_p90 = np.clip(model.p90_model.predict(prepared), 0.0, None)
    # Decision #91: cold-start rows take their own quantile head. The row-level mask is
    # the same no-lag-52 condition the head was fitted on, so a row is bounded by the
    # model trained on rows like it.
    if model.p90_cold_model is not None:
        cold = _cold_start_training_mask(frame).to_numpy()
        if cold.any():
            cold_p90 = np.clip(
                model.p90_cold_model.predict(prepared[cold]), 0.0, None
            )
            raw_p90 = raw_p90.copy()
            raw_p90[cold] = cold_p90
    p50_adjustments = np.array(
        [
            model.market_calibrations.get(
                str(market),
                model.global_calibration,
            ).p50_adjustment
            for market in result["market_id"]
        ]
    )
    p90_adjustments = np.array(
        [
            model.market_calibrations.get(
                str(market),
                model.global_calibration,
            ).p90_adjustment
            for market in result["market_id"]
        ]
    )
    p50 = np.clip(raw_p50 + p50_adjustments, 0.0, None)
    p90 = np.maximum(np.clip(raw_p90 + p90_adjustments, 0.0, None), p50)
    result["lightgbm_p50_raw"] = raw_p50
    result["lightgbm_p90_raw"] = raw_p90
    result["lightgbm_p50"] = p50
    result["lightgbm_p90"] = p90
    result["yhat_p50"] = p50
    result["yhat_p90"] = p90
    result["confidence"] = forecast_confidence(p50, p90)
    result["tail_replay_preferred"] = [
        SeriesKey(str(sku), str(store), str(channel))
        in model.tail_preferred_keys
        for sku, store, channel in zip(
            result["sku_id"],
            result["store_id"],
            result["channel_id"],
            strict=True,
        )
    ]
    contributions = model.p50_model.predict(prepared, pred_contrib=True)
    feature_names = list(model.p50_model.booster_.feature_name())
    feature_index = {name: index for index, name in enumerate(feature_names)}
    assigned: set[str] = set()
    for group, configured in DRIVER_FEATURE_GROUPS.items():
        selected = sorted(configured & feature_index.keys())
        assigned.update(selected)
        for name in selected:
            result[f"shap_feature_{name}"] = contributions[:, feature_index[name]]
        result[f"shap_{group}"] = (
            contributions[:, [feature_index[name] for name in selected]].sum(axis=1)
            if selected
            else 0.0
        )
    remaining = sorted(set(feature_names) - assigned)
    for name in remaining:
        result[f"shap_feature_{name}"] = contributions[:, feature_index[name]]
    result["shap_other"] = (
        contributions[:, [feature_index[name] for name in remaining]].sum(axis=1)
        if remaining
        else 0.0
    )
    result["shap_base_value"] = contributions[:, -1]
    result["driver_method"] = "lightgbm_tree_shap_p50"
    return result


__all__ = [
    "CATEGORICAL_FEATURES",
    "DRIVER_FEATURE_GROUPS",
    "HorizonModel",
    "HorizonModelSet",
    "MODEL_FEATURES",
    "NUMERIC_FEATURES",
    "fit_horizon_model",
    "prepare_model_frame",
    "score_horizon_model",
]
