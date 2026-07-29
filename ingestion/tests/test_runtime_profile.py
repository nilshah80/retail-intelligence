"""Bounded execution-profile resolution for ingestion.

The point of these tests is that ingestion reads the *shared* contract and never
invents its own limits, and that the resolved profile is marked
fingerprint-excluded so a worker-count change cannot invalidate curated identity.
"""

import pytest
from retail_ingestion.runtime.profile import (
    INGESTION_FIELDS,
    resolve_ingestion_runtime,
)


class TestResolution:
    @pytest.mark.parametrize(
        ("name", "scan", "transform", "write", "threads", "memory"),
        [
            ("safe", 2, 2, 2, 1, 4),
            ("balanced", 4, 4, 4, 2, 8),
            ("performance", 8, 8, 8, 8, 32),
            ("ultra-performance", 16, 12, 12, 12, 64),
        ],
    )
    def test_named_profiles_match_the_shared_contract(
        self, name: str, scan: int, transform: int, write: int, threads: int, memory: int
    ) -> None:
        runtime = resolve_ingestion_runtime(name)
        assert runtime.profile == name
        assert runtime.scan_workers == scan
        assert runtime.transform_workers == transform
        assert runtime.write_workers == write
        assert runtime.duckdb_threads == threads
        assert runtime.memory_limit_gb == memory

    def test_default_is_safe_not_host_capacity(self) -> None:
        # Never auto-expand to detected CPU/RAM.
        runtime = resolve_ingestion_runtime()
        assert runtime.memory_limit_gb <= 8
        assert runtime.scan_workers <= 4

    def test_every_declared_field_is_present(self) -> None:
        runtime = resolve_ingestion_runtime("balanced")
        record = runtime.manifest_record()
        for field in INGESTION_FIELDS:
            assert field in record

    def test_explicit_ingestion_overrides_beat_environment(self) -> None:
        runtime = resolve_ingestion_runtime(
            "safe",
            overrides={"scanWorkers": 5, "memoryLimitGb": 6},
            environment={
                "RETAIL_INGESTION_SCAN_WORKERS": "4",
                "RETAIL_INGESTION_MEMORY_LIMIT_GB": "5",
            },
        )
        assert runtime.scan_workers == 5
        assert runtime.memory_limit_gb == 6

    def test_ingestion_environment_overrides_named_profile(self) -> None:
        runtime = resolve_ingestion_runtime(
            "safe",
            environment={"RETAIL_INGESTION_DUCKDB_THREADS": "3"},
        )
        assert runtime.duckdb_threads == 3

    def test_fractional_ingestion_memory_is_rejected(self) -> None:
        from retail_execution.profiles import ProfileValidationError, named_profiles

        document = named_profiles()["safe"]
        document["ingestion"]["memoryLimitGb"] = 4.5
        with pytest.raises(ProfileValidationError, match="whole number"):
            resolve_ingestion_runtime("safe", document=document, environment={})


class TestManifestRecord:
    def test_profile_is_marked_fingerprint_excluded(self) -> None:
        # If this block ever entered a fingerprint, changing a worker count would
        # invalidate curated identity and serve spurious 409s.
        record = resolve_ingestion_runtime("safe").manifest_record()
        assert record["affectsRunIdentity"] is False
        assert record["schemaVersion"] == "retail-execution-profile/v1"

    def test_record_contains_no_binary_floats(self) -> None:
        """The manifest is fingerprint-adjacent, so keep it canonicalizable."""
        from retail_contracts.fingerprint import assert_fingerprintable

        assert_fingerprintable(resolve_ingestion_runtime("performance").manifest_record())


class TestDuckdbPragmas:
    def test_pragmas_carry_the_resolved_bounds(self) -> None:
        pragmas = resolve_ingestion_runtime("performance").duckdb_pragmas()
        assert "PRAGMA threads=8" in pragmas
        assert "PRAGMA memory_limit='32GB'" in pragmas

    def test_safe_profile_is_genuinely_small(self) -> None:
        pragmas = resolve_ingestion_runtime("safe").duckdb_pragmas()
        assert "PRAGMA threads=1" in pragmas
        assert "PRAGMA memory_limit='4GB'" in pragmas


class TestCli:
    def test_profile_command_exposes_all_five_overrides(self, capsys) -> None:
        from retail_ingestion.cli import main

        result = main(
            [
                "profile",
                "--execution-profile",
                "safe",
                "--scan-workers",
                "3",
                "--transform-workers",
                "4",
                "--write-workers",
                "5",
                "--duckdb-threads",
                "2",
                "--memory-limit-gb",
                "6",
            ]
        )
        assert result == 0
        output = capsys.readouterr().out
        assert '"scanWorkers": 3' in output
        assert '"transformWorkers": 4' in output
        assert '"writeWorkers": 5' in output
        assert '"duckdbThreads": 2' in output
        assert '"memoryLimitGb": 6' in output

    def test_profile_command_accepts_yaml_document_on_every_os(
        self, tmp_path, capsys
    ) -> None:
        from retail_execution.profiles import named_profiles
        from retail_ingestion.cli import main

        import yaml

        document = named_profiles()["balanced"]
        document["ingestion"]["scanWorkers"] = 6
        path = tmp_path / "profile.yaml"
        path.write_text(yaml.safe_dump(document), encoding="utf-8")
        result = main(["profile", "--execution-profile-file", str(path)])
        assert result == 0
        assert '"scanWorkers": 6' in capsys.readouterr().out
