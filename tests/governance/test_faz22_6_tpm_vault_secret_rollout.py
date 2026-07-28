from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[2]
OVERLAY = ROOT / "kustomize/overlays/test/kustomization.yaml"
TPM_VAULT_CREDENTIAL_ANNOTATION = (
    "/spec/template/metadata/annotations/"
    "endpoint-admin.acik.com~1tpm-vault-credential-rev"
)
EXPECTED_REVISION = "2913-approle-secret-20260728-1"


def test_endpoint_admin_rolls_after_tpm_vault_credential_rotation():
    document = yaml.safe_load(OVERLAY.read_text(encoding="utf-8"))

    for patch in document["patches"]:
        target = patch.get("target", {})
        if (
            target.get("kind") != "Deployment"
            or target.get("name") != "endpoint-admin-service"
        ):
            continue

        operations = yaml.safe_load(patch["patch"])
        for operation in operations:
            if operation.get("path") == TPM_VAULT_CREDENTIAL_ANNOTATION:
                assert operation["op"] == "add"
                assert operation["value"] == EXPECTED_REVISION
                return

    raise AssertionError("endpoint-admin TPM Vault credential rollout marker not found")
