from __future__ import annotations

from pathlib import Path

from retail_ml.io import authority as authority_module


def test_job_authority_threads_explicit_run_without_reading_it_from_pin(
    monkeypatch, tmp_path: Path
) -> None:
    captured: dict[str, object] = {}

    def fake_verify(*args, **kwargs):
        captured.update(kwargs)
        return {"authorityId": "auth_example"}

    monkeypatch.setattr(authority_module, "verify_input_authority", fake_verify)
    pin = tmp_path / "expected-pin.json"
    pin.write_text("{}", encoding="utf-8")

    result = authority_module.verify_job_authority(
        repository_root=tmp_path,
        authority_path="authority.json",
        expected_pin_path=pin,
        expected_run_id="run-explicit",
        expected_job_purpose="complete_lineage_rebuild",
        retailer_id="retailer-demo",
        tenant_id="tenant-demo",
        environment="local",
        evidence_root="evidence/run-explicit",
    )

    assert result == {"authorityId": "auth_example"}
    assert captured["expected_run_id"] == "run-explicit"
    assert captured["expected_pin_path"] == pin.resolve()
