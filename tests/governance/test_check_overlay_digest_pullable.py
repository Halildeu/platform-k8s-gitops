"""Contract tests for the overlay digest pullability guard.

The property under test is not "does it call the registry" -- it is the one that
decides whether the guard is safe to put in front of every promotion PR:

    the guard must never turn "I could not look" into "it is missing".

GHCR returns 404 both for a digest that does not exist and for a package the
credential may not read. A checker that collapses those two cases either fails
honest PRs the moment its token lapses, or -- worse -- passes a bad digest while
sounding certain. Every test here pins one half of that distinction.

No network: the registry probe is replaced with a table of canned answers.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "governance" / "check_overlay_digest_pullable.py"

CONTROL = "sha256:" + "c0" * 32
GOOD = "sha256:" + "11" * 32
ABSENT = "sha256:" + "22" * 32
PKG = "halildeu/platform-backend-user-service"


def _load():
    spec = importlib.util.spec_from_file_location("digest_guard", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    # dataclasses resolves annotations via sys.modules[cls.__module__]; register
    # before exec or @dataclass raises on a module loaded straight from a path.
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


guard = _load()


def _kustomization(digest: str, repo: str = PKG) -> str:
    return (
        "apiVersion: kustomize.config.k8s.io/v1beta1\n"
        "kind: Kustomization\n"
        "images:\n"
        "  - name: user-service\n"
        f"    newName: ghcr.io/{repo}\n"
        f"    digest: {digest}\n"
    )


def _install_probe(monkeypatch, answers: dict[str, int | None]) -> list[str]:
    """Replace the registry probe with a lookup table; record what was asked."""
    asked: list[str] = []

    def fake_probe(repo, reference, credential):  # noqa: ARG001
        asked.append(reference)
        status = answers.get(reference)
        detail = f"HTTP {status}" if status else "registry unreachable: stub"
        return status, detail

    monkeypatch.setattr(guard, "probe", fake_probe)
    return asked


def _run(monkeypatch, capsys, pins, controls, answers):
    monkeypatch.setattr(guard, "collect_all_pins", lambda: pins)
    monkeypatch.setattr(guard, "collect_changed_pins", lambda *a: pins)
    monkeypatch.setattr(guard, "controls_at", lambda ref: controls)
    asked = _install_probe(monkeypatch, answers)
    monkeypatch.setattr("sys.argv", ["guard", "--base-ref", "origin/main"])
    code = guard.main()
    return code, capsys.readouterr().out, asked


def _pin(digest: str) -> "guard.Pin":
    return guard.Pin(
        path="kustomize/overlays/test/kustomization.yaml",
        name="user-service",
        repo=PKG,
        digest=digest,
    )


# --------------------------------------------------------------------------- #
# Parsing
# --------------------------------------------------------------------------- #


def test_parses_digest_pins_from_kustomization():
    pins = guard.parse_pins(_kustomization(GOOD), "overlays/test/kustomization.yaml")
    assert [(p.repo, p.digest) for p in pins] == [(PKG, GOOD)]


def test_reads_digests_pinned_straight_into_a_pod_spec():
    """CronJobs / activation overlays pin `image: ...@sha256:` outside kustomization."""
    pod_spec = (
        "apiVersion: batch/v1\n"
        "kind: CronJob\n"
        "spec:\n"
        "  jobTemplate:\n"
        "    spec:\n"
        "      template:\n"
        "        spec:\n"
        "          containers:\n"
        "            - name: probe\n"
        f"              image: ghcr.io/{PKG}@{GOOD}\n"
    )
    pins = guard.parse_pins(pod_spec, "kustomize/overlays/test/cronjob.yaml")
    assert [(p.repo, p.digest) for p in pins] == [(PKG, GOOD)]


def test_pod_spec_digests_from_other_registries_stay_out_of_scope():
    """Docker Hub images are pinned by digest here too, but are not the failure."""
    pod_spec = "          image: curlimages/curl:8.10.1@" + GOOD + "\n"
    assert guard.parse_pins(pod_spec, "kustomize/overlays/test/cronjob.yaml") == []


def test_ignores_tag_pins_and_foreign_registries():
    doc = (
        "images:\n"
        "  - name: a\n"
        "    newName: ghcr.io/x/y\n"
        "    newTag: sha-abc123\n"          # mutable tag, not this guard's job
        "  - name: b\n"
        "    newName: docker.io/library/nginx\n"
        f"    digest: {GOOD}\n"             # different registry, out of scope
    )
    assert guard.parse_pins(doc, "k.yaml") == []


# --------------------------------------------------------------------------- #
# The distinction this guard exists to preserve
# --------------------------------------------------------------------------- #


def test_absent_digest_fails_when_control_proves_package_readable(monkeypatch, capsys):
    code, out, _ = _run(
        monkeypatch,
        capsys,
        pins=[_pin(ABSENT)],
        controls={PKG: CONTROL},
        answers={CONTROL: 200, ABSENT: 404},
    )
    assert code == 1, "a genuinely missing digest must block the PR"
    assert "UNRETRIEVABLE DIGEST" in out
    assert "not in the registry" in out


def test_same_404_is_inconclusive_when_control_also_404s(monkeypatch, capsys):
    """The regression that matters: unreadable package must not read as absent."""
    code, out, _ = _run(
        monkeypatch,
        capsys,
        pins=[_pin(ABSENT)],
        controls={PKG: CONTROL},
        answers={CONTROL: 404, ABSENT: 404},
    )
    assert code == 0, "no credential to look with is not evidence of absence"
    assert "INCONCLUSIVE" in out
    assert "UNRETRIEVABLE" not in out
    assert "is not reporting them as good" in out


def test_inconclusive_does_not_probe_the_new_digest(monkeypatch, capsys):
    """Once the control says 'not readable', further probes prove nothing."""
    _, _, asked = _run(
        monkeypatch,
        capsys,
        pins=[_pin(ABSENT)],
        controls={PKG: CONTROL},
        answers={CONTROL: 404, ABSENT: 404},
    )
    assert asked == [CONTROL]


def test_retrievable_digest_passes(monkeypatch, capsys):
    code, out, _ = _run(
        monkeypatch,
        capsys,
        pins=[_pin(GOOD)],
        controls={PKG: CONTROL},
        answers={CONTROL: 200, GOOD: 200},
    )
    assert code == 0
    assert "All new digests are retrievable" in out


def test_missing_control_is_inconclusive_not_pass(monkeypatch, capsys):
    """No control on the base ref means no way to self-validate."""
    code, out, _ = _run(
        monkeypatch,
        capsys,
        pins=[_pin(GOOD)],
        controls={},
        answers={GOOD: 200},
    )
    assert code == 0
    assert "INCONCLUSIVE" in out
    assert "cannot self-validate" in out


def test_unreachable_registry_never_reads_as_absent(monkeypatch, capsys):
    code, out, _ = _run(
        monkeypatch,
        capsys,
        pins=[_pin(GOOD)],
        controls={PKG: CONTROL},
        answers={CONTROL: None, GOOD: None},
    )
    assert code == 0, "a network failure is not a verdict about the digest"
    assert "INCONCLUSIVE" in out


def test_unchanged_pins_are_not_rechecked(monkeypatch, capsys):
    """Only new/changed pins are in scope; a quiet PR must not fail on old ones."""
    monkeypatch.setattr(guard, "collect_changed_pins", lambda *a: [])
    monkeypatch.setattr("sys.argv", ["guard", "--base-ref", "origin/main"])
    assert guard.main() == 0
    assert "nothing to verify" in capsys.readouterr().out


# --------------------------------------------------------------------------- #
# The guard must keep saying what it does not prove
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "answers, expected",
    [
        ({CONTROL: 200, GOOD: 200}, "digest-probe"),   # pass path
        ({CONTROL: 404, GOOD: 404}, "digest-probe"),   # inconclusive path
    ],
)
def test_cluster_pull_probe_is_always_offered(monkeypatch, capsys, answers, expected):
    """CI's credential != the cluster's ghcr-pull; the guard must say so (#2876)."""
    _, out, _ = _run(
        monkeypatch,
        capsys,
        pins=[_pin(GOOD)],
        controls={PKG: CONTROL},
        answers=answers,
    )
    assert expected in out


def test_docstring_records_why_the_control_exists():
    """Strip the rationale and the next reader 'simplifies' the control away."""
    text = SCRIPT.read_text(encoding="utf-8")
    assert "404" in text and "control" in text.lower()
    assert "#2863" in text and "#2876" in text, "both incidents stay cited"
