#!/usr/bin/env python3
"""TEST notification routing and DEV banner boundaries (#3733, #3582)."""

import pathlib
import subprocess
import unittest

import yaml

ROOT = pathlib.Path(__file__).resolve().parents[2]
KEY = "USER_PENDING_ACTIVATION_NOTIFICATION_ADMIN_EMAIL"
MARKER = "user-service.acik.com/activation-recipient-rev"


def render(environment):
    output = subprocess.check_output(
        ["kustomize", "build", str(ROOT / "kustomize/overlays" / environment)],
        text=True,
    )
    return {
        (doc["kind"], doc["metadata"]["name"]): doc
        for doc in yaml.safe_load_all(output)
        if doc
    }


class FollowupsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.test = render("test")
        cls.prod = render("prod")

    def test_test_notification_recipient_and_rollout(self):
        config = self.test[("ConfigMap", "user-service-config")]["data"]
        self.assertEqual(config[KEY], "halil.kocoglu@acik.com")
        self.assertEqual(config["USER_PENDING_ACTIVATION_NOTIFICATION_ENABLED"], "true")
        pod = self.test[("Deployment", "user-service")]["spec"]["template"]
        self.assertEqual(pod["metadata"]["annotations"][MARKER], "3733-1")

    def test_production_is_not_activated_or_rolled(self):
        config = self.prod[("ConfigMap", "user-service-config")]["data"]
        base = yaml.safe_load(
            (ROOT / "kustomize/base/apps/user-service/configmap.yaml").read_text()
        )["data"]
        self.assertEqual(config[KEY], base[KEY])
        self.assertEqual(config["USER_PENDING_ACTIVATION_NOTIFICATION_ENABLED"], "false")
        pod = self.prod[("Deployment", "user-service")]["spec"]["template"]
        self.assertNotIn(MARKER, pod.get("metadata", {}).get("annotations", {}))

    def test_banner_names_dev_without_starting_legacy_services(self):
        path = ROOT / "bootstrap/host/devai/00-platform-dev-motd"
        subprocess.run(["sh", "-n", str(path)], check=True)
        output = subprocess.check_output(["sh", str(path)], text=True)
        self.assertIn("PLATFORM DEVELOPMENT HOST", output)
        self.assertIn("/home/<user>/repos", output)
        self.assertNotIn("retired host", output)
        source = path.read_text()
        self.assertIn("/etc/aiserver-archive/ARCHIVE_STANDBY", source)
        for command in ("systemctl", "docker ", "rm ", "sudo "):
            self.assertNotIn(command, source)


if __name__ == "__main__":
    unittest.main()
