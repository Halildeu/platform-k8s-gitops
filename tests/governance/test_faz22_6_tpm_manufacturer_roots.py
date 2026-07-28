import hashlib
import re
import ssl
import subprocess
import tempfile
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[2]
OVERLAY = ROOT / "kustomize/overlays/test/kustomization.yaml"
ACTIVATION = (
    ROOT
    / "kustomize/overlays/test/activation/endpoint-admin-remote-bridge-device-key"
    / "configmap-device-key-patch.yaml"
)
ROOT_PINS_KEY = "ENDPOINT_ADMIN_TPM_ATTEST_MANUFACTURER_ROOT_SHA256"
ROOT_PEMS_KEY = "ENDPOINT_ADMIN_TPM_ATTEST_MANUFACTURER_ROOT_PEMS"
NUVOTON_ROOT_SHA256 = "cd8185ff8995ed09811970090a8c36fafab34ef87f47fa51fdb9ecf95c9c2e04"
NUVOTON_ROOT_CN = "Nuvoton TPM Root CA 2111"


def _primary_values() -> dict[str, str]:
    document = yaml.safe_load(OVERLAY.read_text(encoding="utf-8"))
    for patch in document["patches"]:
        target = patch.get("target", {})
        if (
            target.get("kind") != "ConfigMap"
            or target.get("name") != "endpoint-admin-service-config"
        ):
            continue
        operations = yaml.safe_load(patch["patch"])
        values = {
            operation["path"].removeprefix("/data/"): operation["value"]
            for operation in operations
            if operation["path"].startswith("/data/")
        }
        if ROOT_PINS_KEY in values:
            return values
    raise AssertionError("endpoint-admin TPM manufacturer root patch not found")


def _certificate_blocks(pem_bundle: str) -> list[str]:
    return re.findall(
        r"-----BEGIN CERTIFICATE-----.*?-----END CERTIFICATE-----",
        pem_bundle,
        flags=re.DOTALL,
    )


def _der(block: str) -> bytes:
    return ssl.PEM_cert_to_DER_cert(block)


def _openssl_inspect_and_verify_root(block: str) -> str:
    with tempfile.NamedTemporaryFile(mode="w", suffix=".pem") as certificate_file:
        certificate_file.write(block)
        certificate_file.flush()
        details = subprocess.run(
            [
                "openssl",
                "x509",
                "-in",
                certificate_file.name,
                "-noout",
                "-subject",
                "-issuer",
                "-text",
            ],
            check=True,
            capture_output=True,
            text=True,
        ).stdout
        verification = subprocess.run(
            [
                "openssl",
                "verify",
                "-CAfile",
                certificate_file.name,
                certificate_file.name,
            ],
            check=True,
            capture_output=True,
            text=True,
        ).stdout
    assert verification.strip().endswith(": OK")
    return details


def test_test_overlay_pins_every_manufacturer_root_and_contains_nuvoton_2111():
    values = _primary_values()
    pins = set(values[ROOT_PINS_KEY].split(","))
    certificate_blocks = _certificate_blocks(values[ROOT_PEMS_KEY])
    certificate_pins = {
        hashlib.sha256(_der(block)).hexdigest()
        for block in certificate_blocks
    }

    assert certificate_pins == pins
    assert NUVOTON_ROOT_SHA256 in pins

    nuvoton_block = next(
        block
        for block in certificate_blocks
        if hashlib.sha256(_der(block)).hexdigest() == NUVOTON_ROOT_SHA256
    )
    details = _openssl_inspect_and_verify_root(nuvoton_block)
    subject = next(line for line in details.splitlines() if line.startswith("subject="))
    issuer = next(line for line in details.splitlines() if line.startswith("issuer="))
    assert NUVOTON_ROOT_CN in subject
    assert subject.removeprefix("subject=") == issuer.removeprefix("issuer=")
    assert "CA:TRUE, pathlen:0" in details
    assert "Certificate Sign" in details


def test_device_key_activation_uses_the_same_pinned_root_bundle():
    primary = _primary_values()
    activation = yaml.safe_load(ACTIVATION.read_text(encoding="utf-8"))["data"]

    assert activation[ROOT_PINS_KEY] == primary[ROOT_PINS_KEY]
    assert activation[ROOT_PEMS_KEY] == primary[ROOT_PEMS_KEY]
