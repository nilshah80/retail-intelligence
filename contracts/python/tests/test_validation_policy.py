from pathlib import Path

import yaml


REPO_ROOT = Path(__file__).resolve().parents[3]
POLICY = REPO_ROOT / "contracts/validation-policy.yaml"


def test_repository_ci_is_prohibited_by_contract() -> None:
    policy = yaml.safe_load(POLICY.read_text(encoding="utf-8"))

    assert policy["schemaVersion"] == "retail-validation-policy/v1"
    assert policy["repositoryCI"] == {
        "allowed": False,
        "workflowDirectory": ".github/workflows",
        "enforcement": "contract_validation_rejects_workflow_files",
    }
    assert policy["validation"]["mode"] == "developer_run"
    assert policy["validation"]["entrypoint"] == "tools/dev.py"


def test_repository_contains_no_ci_workflow_files() -> None:
    workflow_root = REPO_ROOT / ".github/workflows"
    workflow_files = (
        list(workflow_root.glob("*.yml"))
        + list(workflow_root.glob("*.yaml"))
        if workflow_root.exists()
        else []
    )

    assert workflow_files == []
