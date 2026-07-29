from __future__ import annotations

import json
import tempfile
import unittest
from importlib.resources import files
from pathlib import Path

from retail_execution import (
    ProfileValidationError,
    load_profile_document,
    named_profiles,
    resolve_profile,
)


class ExecutionProfileTests(unittest.TestCase):
    def test_named_profiles_are_bounded_and_validate(self) -> None:
        profiles = named_profiles()
        self.assertEqual(
            {"safe", "balanced", "performance", "ultra-performance"},
            set(profiles),
        )
        for name in profiles:
            self.assertEqual(name, resolve_profile(name, environment={})["profile"])

    def test_golden_vectors(self) -> None:
        vectors = json.loads(
            files("retail_execution")
            .joinpath("data", "v1", "golden-vectors.json")
            .read_text(encoding="utf-8")
        )
        for vector in vectors:
            with self.subTest(vector["name"]):
                resolved = resolve_profile(
                    vector["profile"],
                    document=vector.get("document"),
                    datagen_overrides=vector.get("overrides"),
                    environment=vector.get("environment", {}),
                )
                self.assertEqual(vector["expectedDatagen"], resolved["datagen"])

    def test_explicit_override_beats_environment(self) -> None:
        resolved = resolve_profile(
            "safe",
            datagen_overrides={"partitionWorkers": 5},
            environment={"RETAIL_DATAGEN_PARTITION_WORKERS": "4"},
        )
        self.assertEqual(5, resolved["datagen"]["partitionWorkers"])

    def test_unsafe_or_unknown_values_fail(self) -> None:
        with self.assertRaises(ProfileValidationError):
            resolve_profile(
                "safe",
                datagen_overrides={"marketWorkers": 5},
                environment={},
            )
        with self.assertRaises(ProfileValidationError):
            resolve_profile(
                "safe",
                datagen_overrides={"partitionWorkers": 20, "memoryLimitGb": 4},
                environment={},
            )

    def test_supplied_document_must_be_complete_and_profile_shaped(self) -> None:
        for document in (
            {"schemaVersion": "retail-execution-profile/v1"},
            {
                "schemaVersion": "retail-execution-profile/v1",
                "profile": "safe",
                "datagen": {},
                "catalog": {},
            },
        ):
            with self.subTest(document=document):
                with self.assertRaises(ProfileValidationError):
                    resolve_profile(document=document, environment={})

    def test_custom_requires_a_document_and_nonfinite_memory_fails(self) -> None:
        with self.assertRaises(ProfileValidationError):
            resolve_profile("custom", environment={})
        with self.assertRaises(ProfileValidationError):
            resolve_profile(
                "custom",
                document={
                    "schemaVersion": "retail-execution-profile/v1",
                    "profile": "custom",
                    "datagen": {},
                },
                environment={},
            )
        for value in (float("nan"), float("inf"), float("-inf")):
            with self.subTest(value=value):
                with self.assertRaises(ProfileValidationError):
                    resolve_profile(
                        "safe",
                        datagen_overrides={"memoryLimitGb": value},
                        environment={},
                    )

    def test_all_layer_blocks_are_schema_validated(self) -> None:
        safe = named_profiles()["safe"]
        for mutate in (
            lambda row: row.update({"ml": "not-an-object"}),
            lambda row: row["api"].update({"gomaxprocs": -99999}),
            lambda row: row["ingestion"].update({"scanWorkers": 0}),
            lambda row: row["ml"].update({"unknownWorker": 2}),
        ):
            with self.subTest(mutate=mutate):
                candidate = json.loads(json.dumps(safe))
                mutate(candidate)
                with self.assertRaises(ProfileValidationError):
                    resolve_profile(
                        candidate["profile"],
                        document=candidate,
                        environment={},
                    )

    def test_packaged_schema_is_the_active_contract(self) -> None:
        schema = json.loads(
            files("retail_execution")
            .joinpath("data", "v1", "schema.json")
            .read_text(encoding="utf-8")
        )
        self.assertEqual(
            schema["properties"]["api"]["properties"]["gomaxprocs"][
                "minimum"
            ],
            1,
        )
        invalid = named_profiles()["safe"]
        invalid["api"]["gomaxprocs"] = 0
        with self.assertRaises(ProfileValidationError):
            resolve_profile("safe", document=invalid, environment={})

    def test_malformed_yaml_uses_the_profile_error_contract(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / "broken.yaml"
            path.write_text("profile: [unterminated", encoding="utf-8")
            with self.assertRaises(ProfileValidationError):
                load_profile_document(path)


if __name__ == "__main__":
    unittest.main()
