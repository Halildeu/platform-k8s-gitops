from __future__ import annotations

import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts/deploy/verify-pod-digest.sh"
EXPECTED = "sha256:" + ("a" * 64)
ACTUAL = "sha256:" + ("b" * 64)
REPOSITORY = "ghcr.io/halildeu/platform-web-frontend-testai"


class VerifyPodDigestTests(unittest.TestCase):
    def run_verifier(
        self,
        *,
        image_id: str,
        cri_images: list[dict[str, object]],
        alias_mode: bool = True,
    ) -> tuple[subprocess.CompletedProcess[str], bool]:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp = Path(temp_dir)
            bin_dir = temp / "bin"
            bin_dir.mkdir()
            pods_path = temp / "pods.json"
            images_path = temp / "images.json"
            docker_marker = temp / "docker-called"

            pods_path.write_text(
                json.dumps(
                    {
                        "items": [
                            {
                                "metadata": {
                                    "name": "frontend-test",
                                    "creationTimestamp": "2026-08-01T00:00:00Z",
                                    "deletionTimestamp": None,
                                },
                                "status": {
                                    "containerStatuses": [{"imageID": image_id}]
                                },
                            }
                        ]
                    }
                )
            )
            images_path.write_text(json.dumps({"images": cri_images}))

            kubectl = bin_dir / "kubectl"
            kubectl.write_text('#!/usr/bin/env bash\ncat "$MOCK_PODS_JSON"\n')
            kubectl.chmod(0o755)
            docker = bin_dir / "docker"
            docker.write_text(
                "#!/usr/bin/env bash\n"
                'touch "$MOCK_DOCKER_MARKER"\n'
                '[[ "$*" == "exec k3d-test-server-0 crictl images -o json" ]] || exit 9\n'
                'cat "$MOCK_CRI_IMAGES_JSON"\n'
            )
            docker.chmod(0o755)

            args = [
                "bash",
                str(SCRIPT),
                "--context",
                "k3d-test",
                "--namespace",
                "platform-test",
                "--selector",
                "app.kubernetes.io/name=frontend",
                "--expected-digest",
                EXPECTED,
            ]
            if alias_mode:
                args.extend(
                    [
                        "--expected-repository",
                        REPOSITORY,
                        "--cri-node-container",
                        "k3d-test-server-0",
                    ]
                )

            env = os.environ.copy()
            env.update(
                {
                    "PATH": f"{bin_dir}:{env['PATH']}",
                    "MOCK_PODS_JSON": str(pods_path),
                    "MOCK_CRI_IMAGES_JSON": str(images_path),
                    "MOCK_DOCKER_MARKER": str(docker_marker),
                }
            )
            result = subprocess.run(
                args,
                cwd=ROOT,
                env=env,
                text=True,
                capture_output=True,
                check=False,
            )
            return result, docker_marker.exists()

    def test_direct_digest_match_does_not_query_cri(self):
        result, docker_called = self.run_verifier(
            image_id=f"{REPOSITORY}@{EXPECTED}",
            cri_images=[],
        )
        self.assertEqual(0, result.returncode, result.stderr + result.stdout)
        self.assertFalse(docker_called)

    def test_unique_cri_record_binding_runtime_alias_and_expected_digest_passes(self):
        actual_ref = f"docker.io/library/import-2026-08-01@{ACTUAL}"
        result, docker_called = self.run_verifier(
            image_id=actual_ref,
            cri_images=[
                {
                    "id": "sha256:" + ("c" * 64),
                    "repoDigests": [actual_ref, f"{REPOSITORY}@{EXPECTED}"],
                }
            ],
        )
        self.assertEqual(0, result.returncode, result.stderr + result.stdout)
        self.assertTrue(docker_called)
        self.assertIn("uniquely binds runtime alias", result.stdout)

    def test_alias_without_expected_digest_fails_closed(self):
        actual_ref = f"docker.io/library/import-2026-08-01@{ACTUAL}"
        result, _ = self.run_verifier(
            image_id=actual_ref,
            cri_images=[
                {
                    "id": "sha256:" + ("c" * 64),
                    "repoDigests": [actual_ref],
                }
            ],
        )
        self.assertNotEqual(0, result.returncode)
        self.assertIn("not uniquely bound", result.stdout)

    def test_alias_in_multiple_cri_records_fails_closed(self):
        actual_ref = f"docker.io/library/import-2026-08-01@{ACTUAL}"
        result, _ = self.run_verifier(
            image_id=actual_ref,
            cri_images=[
                {
                    "id": "sha256:" + ("c" * 64),
                    "repoDigests": [actual_ref, f"{REPOSITORY}@{EXPECTED}"],
                },
                {
                    "id": "sha256:" + ("d" * 64),
                    "repoDigests": [actual_ref, f"{REPOSITORY}@{EXPECTED}"],
                },
            ],
        )
        self.assertNotEqual(0, result.returncode)
        self.assertIn("actual-matches:   2", result.stdout)

    def test_noncanonical_runtime_image_id_fails_closed(self):
        result, _ = self.run_verifier(
            image_id=ACTUAL,
            cri_images=[],
        )
        self.assertNotEqual(0, result.returncode)
        self.assertIn("not a canonical repository@digest", result.stdout)

    def test_digest_mismatch_without_explicit_alias_mode_stays_strict(self):
        actual_ref = f"docker.io/library/import-2026-08-01@{ACTUAL}"
        result, docker_called = self.run_verifier(
            image_id=actual_ref,
            cri_images=[
                {
                    "id": "sha256:" + ("c" * 64),
                    "repoDigests": [actual_ref, f"{REPOSITORY}@{EXPECTED}"],
                }
            ],
            alias_mode=False,
        )
        self.assertNotEqual(0, result.returncode)
        self.assertFalse(docker_called)


if __name__ == "__main__":
    unittest.main()
