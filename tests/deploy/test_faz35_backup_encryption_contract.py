"""Faz 35 ES-209 — backup archives must be unreadable at rest.

A whistleblowing database dump is every report narrative in one file; an OpenFGA
export says which staff subject is attached to which case; a Vault raft snapshot is
every secret the cell holds. Before this contract all three were written to a shared
volume in the clear — the pg dump as `.sql.gz`, the export as a directory of JSON, the
snapshot verbatim.

These tests pin the properties that keep that from coming back quietly:

* every archive is encrypted, and the job refuses to run rather than write plaintext
  when the key is absent;
* the encryption is verified on the written file, not assumed from the command line —
  a pipeline whose middle stage fails still exits zero in `sh`;
* legacy plaintext artifacts are actively deleted rather than aged out, because a
  retention window on data that should never have existed is not a fix;
* the credential that fetches from a network service and the key that encrypts the
  result live in different containers.
"""

import pathlib
import unittest

import yaml

ROOT = pathlib.Path(__file__).resolve().parents[2]
BACKUP = ROOT / "kustomize/base/apps/etik-speak/backup"

ARCHIVE_KEY_SECRET = "etik-speak-backup-archive-key"

# Credentials that reach a service over the network. Where one of these is present,
# the archive key must not be.
NETWORK_CREDENTIALS = {"FGA_TOKEN", "VAULT_TOKEN"}


def cronjobs():
    for path in sorted(BACKUP.glob("cronjob-*.yaml")):
        doc = yaml.safe_load(path.read_text())
        spec = doc["spec"]["jobTemplate"]["spec"]["template"]["spec"]
        yield doc["metadata"]["name"], spec


def env_names(container):
    return {e["name"] for e in container.get("env", [])}


def writer(spec):
    """The container that writes to /archive — the only one holding the key."""
    for container in spec.get("containers", []):
        for mount in container.get("volumeMounts", []):
            if mount["mountPath"] == "/archive" and not mount.get("readOnly"):
                return container
    raise AssertionError("no container writes to /archive")


class BackupEncryptionContract(unittest.TestCase):

    def test_every_backup_job_encrypts_what_it_writes(self):
        for name, spec in cronjobs():
            with self.subTest(name):
                script = "\n".join(
                    c.get("command", [])[-1] for c in spec.get("containers", []))
                self.assertIn("openssl enc -aes-256-cbc", script,
                              f"{name} writes an archive without encrypting it")
                self.assertIn("-pbkdf2", script,
                              f"{name} derives its key without PBKDF2")
                self.assertIn("-salt", script, f"{name} encrypts without a salt")

    def test_missing_key_stops_the_job_instead_of_writing_plaintext(self):
        for name, spec in cronjobs():
            with self.subTest(name):
                script = writer(spec)["command"][-1]
                self.assertIn('if [ -z "${ARCHIVE_KEY:-}" ]', script,
                              f"{name} does not check for an empty archive key")
                self.assertIn("exit 1", script,
                              f"{name} does not fail closed on a missing key")

    def test_a_failure_mid_pipeline_fails_the_job(self):
        """The first live run failed pg_dump on DNS and still reported success.

        `set -eu` only inspects the last command in a pipeline, and dash — Debian's
        `/bin/sh` — has no `pipefail`. So openssl encrypted an empty stream, exited
        zero, and the job went green with a 48-byte archive.
        """
        for name, spec in cronjobs():
            with self.subTest(name):
                container = writer(spec)
                self.assertEqual("/bin/bash", container["command"][0],
                                 f"{name} encrypts under a shell without pipefail")
                self.assertIn("set -euo pipefail", container["command"][-1],
                              f"{name} does not enable pipefail")

    def test_the_written_file_is_verified_against_a_size_floor(self):
        """openssl writes a valid 48-byte header for empty input, so `-s` proves nothing."""
        for name, spec in cronjobs():
            with self.subTest(name):
                script = writer(spec)["command"][-1]
                self.assertIn("Salted__", script,
                              f"{name} does not verify the file it wrote is encrypted")
                self.assertIn('SIZE=$(stat -c %s "$OUT")', script,
                              f"{name} does not measure the archive it wrote")
                floor = next(
                    (int(w) for line in script.splitlines() if "-lt" in line
                     for w in line.split() if w.isdigit()), 0)
                self.assertGreater(floor, 48,
                                   f"{name} accepts an archive an empty stream could produce")

    def test_legacy_plaintext_artifacts_are_deleted_not_aged_out(self):
        expected = {
            "etik-speak-pg-dump": "-name '*.sql.gz' -delete",
            "etik-speak-openfga-export": "-type d -exec rm -rf {} +",
            "etik-speak-vault-snapshot": "-name '*.snap' -delete",
        }
        for name, spec in cronjobs():
            with self.subTest(name):
                script = writer(spec)["command"][-1]
                needle = expected[name]
                self.assertIn(needle, script,
                              f"{name} leaves earlier plaintext artifacts in place")
                index = script.index(needle)
                self.assertNotIn("-mtime", script[index - 60:index],
                                 f"{name} ages plaintext out instead of deleting it")

    def test_archive_key_is_held_only_by_the_container_that_writes_the_archive(self):
        for name, spec in cronjobs():
            with self.subTest(name):
                holders = [
                    c["name"]
                    for c in spec.get("initContainers", []) + spec.get("containers", [])
                    if "ARCHIVE_KEY" in env_names(c)
                ]
                self.assertEqual([writer(spec)["name"]], holders,
                                 f"{name} exposes the archive key beyond its writer")

    def test_network_credentials_never_share_a_container_with_the_archive_key(self):
        for name, spec in cronjobs():
            with self.subTest(name):
                for container in spec.get("initContainers", []) + spec.get("containers", []):
                    names = env_names(container)
                    if names & NETWORK_CREDENTIALS:
                        self.assertNotIn(
                            "ARCHIVE_KEY", names,
                            f"{name}/{container['name']} holds both a network credential "
                            "and the archive key")

    def test_staged_plaintext_never_reaches_a_disk_that_outlives_the_pod(self):
        """Split jobs stage plaintext before encrypting it; that staging must be tmpfs."""
        for name, spec in cronjobs():
            if not spec.get("initContainers"):
                continue
            with self.subTest(name):
                work = next((v for v in spec["volumes"] if v["name"] == "work"), None)
                self.assertIsNotNone(work, f"{name} stages plaintext with no work volume")
                self.assertEqual("Memory", work.get("emptyDir", {}).get("medium"),
                                 f"{name} stages plaintext on disk")

    def test_encrypting_image_is_pinned_by_digest(self):
        """The archives are only as immutable as the tool that wrote them."""
        for name, spec in cronjobs():
            with self.subTest(name):
                self.assertIn("@sha256:", writer(spec)["image"],
                              f"{name} encrypts with a floating image tag")

    def test_archive_key_comes_from_its_own_secret(self):
        for name, spec in cronjobs():
            with self.subTest(name):
                source = next(
                    e for e in writer(spec)["env"] if e["name"] == "ARCHIVE_KEY")
                self.assertEqual(
                    ARCHIVE_KEY_SECRET, source["valueFrom"]["secretKeyRef"]["name"],
                    f"{name} reads the archive key from a shared secret")


if __name__ == "__main__":
    unittest.main()
