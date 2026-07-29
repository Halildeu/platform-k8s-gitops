#!/usr/bin/env python3
"""Guard the rendered test-only direct-STT consumer activation contract."""

from pathlib import Path
import shutil
import subprocess
import unittest

import yaml


REPO_ROOT = Path(__file__).resolve().parents[2]
TEST_OVERLAY = REPO_ROOT / "kustomize" / "overlays" / "test" / "kustomization.yaml"
TEST_ESO_OVERLAY = (
    REPO_ROOT / "kustomize" / "overlays" / "test" / "eso" / "kustomization.yaml"
)
PROD_OVERLAY = REPO_ROOT / "kustomize" / "overlays" / "prod" / "kustomization.yaml"
BASE_TRANSCRIPT = (
    REPO_ROOT
    / "kustomize"
    / "base"
    / "apps"
    / "transcript-service"
    / "kustomization.yaml"
)


def render(overlay: Path) -> list[dict]:
    kubectl = shutil.which("kubectl")
    if kubectl is None:
        raise RuntimeError("kubectl is required for Kustomize render checks")
    result = subprocess.run(
        [kubectl, "kustomize", str(overlay.parent)],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return [doc for doc in yaml.safe_load_all(result.stdout) if isinstance(doc, dict)]


def resource(documents: list[dict], kind: str, name: str) -> dict:
    matches = [
        doc
        for doc in documents
        if doc.get("kind") == kind and doc.get("metadata", {}).get("name") == name
    ]
    if len(matches) != 1:
        raise AssertionError(f"expected one {kind}/{name}, found {len(matches)}")
    return matches[0]


class TranscriptDirectSttActivationTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.test_documents = render(TEST_OVERLAY)
        cls.test_eso_documents = render(TEST_ESO_OVERLAY)
        cls.prod_documents = render(PROD_OVERLAY)
        cls.base_transcript_documents = render(BASE_TRANSCRIPT)

    def test_test_overlay_enables_the_canonical_result_stream_consumer(self):
        config = resource(
            self.test_documents, "ConfigMap", "transcript-service-config"
        )["data"]
        self.assertEqual("true", config["TRANSCRIPT_DIRECT_STT_RESULT_CONSUMER_ENABLED"])
        self.assertEqual(
            "transcript:direct-stt-results",
            config["TRANSCRIPT_DIRECT_STT_RESULT_STREAM_KEY"],
        )
        self.assertEqual(
            "transcript:direct-stt-results:dlq",
            config["TRANSCRIPT_DIRECT_STT_RESULT_CONSUMER_DLQ_STREAM_KEY"],
        )
        self.assertEqual(
            "transcript-service-v1",
            config["TRANSCRIPT_DIRECT_STT_RESULT_CONSUMER_GROUP_NAME"],
        )
        self.assertEqual("true", config["TRANSCRIPT_REDIS_HEALTH_ENABLED"])

    def test_config_change_forces_a_transcript_service_rollout(self):
        deployment = resource(
            self.test_documents, "Deployment", "transcript-service"
        )
        annotations = deployment["spec"]["template"]["metadata"]["annotations"]
        self.assertEqual(
            "2026-07-29-2610-v6-transport-epoch",
            annotations["transcript-service.acik.com/direct-stt-result-consumer-rev"],
        )

        container = next(
            item
            for item in deployment["spec"]["template"]["spec"]["containers"]
            if item["name"] == "transcript-service"
        )
        environment = {item["name"]: item for item in container["env"]}
        self.assertEqual(
            {
                "name": "transcript-service-secrets",
                "key": "TRANSCRIPT_REDIS_PASSWORD",
                "optional": False,
            },
            environment["TRANSCRIPT_REDIS_PASSWORD"]["valueFrom"]["secretKeyRef"],
        )

    def test_transcript_service_receives_the_existing_redis_requirepass(self):
        external_secret = resource(
            self.test_eso_documents, "ExternalSecret", "transcript-service-secrets"
        )
        entries = {
            item["secretKey"]: item["remoteRef"]
            for item in external_secret["spec"]["data"]
        }
        self.assertEqual(
            {
                "key": "kv/platform/audio-gateway-service",
                "property": "redis_password",
            },
            entries["TRANSCRIPT_REDIS_PASSWORD"],
        )

    def test_base_does_not_enable_the_test_only_consumer(self):
        config = resource(
            self.base_transcript_documents, "ConfigMap", "transcript-service-config"
        )["data"]
        self.assertNotEqual(
            "true", config.get("TRANSCRIPT_DIRECT_STT_RESULT_CONSUMER_ENABLED")
        )

    def test_prod_overlay_does_not_enable_the_test_only_consumer(self):
        configs = [
            doc
            for doc in self.prod_documents
            if doc.get("kind") == "ConfigMap"
            and doc.get("metadata", {}).get("name") == "transcript-service-config"
        ]
        if not configs:
            return

        config = configs[0]["data"]
        self.assertNotEqual(
            "true", config.get("TRANSCRIPT_DIRECT_STT_RESULT_CONSUMER_ENABLED")
        )
        self.assertNotEqual("true", config.get("TRANSCRIPT_REDIS_HEALTH_ENABLED"))


if __name__ == "__main__":
    unittest.main()
