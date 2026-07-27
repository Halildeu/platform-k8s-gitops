"""k3d bootstrap registry binding invariant — Faz 22 security hardening.

`bootstrap/k3d-*.yaml` declares the managed k3d image registry as desired state.
The registry image is `registry:2` with NO authentication configured, and Docker
Registry v2's default posture is unauthenticated READ-WRITE. Publishing that on a
wildcard address (`0.0.0.0`) therefore exposes an anonymous, writable image
registry to every host on the surrounding network — and because the cluster pulls
from it, an actor who can write to it can overwrite a tag the cluster consumes
(supply-chain path).

Measured on aiserver (10.9.10.15) 2026-07-26/27, when `host: "0.0.0.0"` was still
the declared value:

    curl http://10.9.10.15:5000/v2/         -> 200  (not 401 + WWW-Authenticate)
    curl http://10.9.10.15:5001/v2/_catalog -> {"repositories":["platform-backend-audio-gateway-service"]}

Binding to loopback costs nothing functionally: cluster nodes reach the registry
over the DOCKER NETWORK by container hostname, not via the host port publication
(node `registries.yaml`: `platform-test-registry:5001` -> `http://platform-test-registry:5000`).
Host-side `docker push localhost:<port>/...` keeps working.

This guard exists because the exposure was declared in the repo, not improvised on
the host — so every cluster recreate reintroduced it (test cluster was recreated
under #2306). A comment alone would not have survived; this test makes the
invariant machine-enforced.
"""

import ipaddress
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
BOOTSTRAP_DIR = REPO_ROOT / "bootstrap"


def _k3d_cluster_configs() -> list[Path]:
    """Discover cluster configs by GLOB, never a hardcoded list.

    A hardcoded list silently stops covering a newly added cluster config; the
    glob means a future `bootstrap/k3d-<newenv>.yaml` is guarded on the day it
    lands.
    """
    return sorted(BOOTSTRAP_DIR.glob("k3d-*.yaml"))


def test_cluster_configs_are_discoverable():
    """Fail loudly if the glob goes empty — otherwise every assertion below
    would pass vacuously after a directory rename."""
    found = _k3d_cluster_configs()
    assert found, f"no k3d-*.yaml discovered under {BOOTSTRAP_DIR}"


def test_managed_registry_is_never_published_on_a_wildcard_address():
    offenders: list[str] = []
    checked: list[str] = []

    for path in _k3d_cluster_configs():
        doc = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        create = (doc.get("registries") or {}).get("create")
        if not isinstance(create, dict):
            # A config may legitimately declare no managed registry at all.
            continue

        checked.append(path.name)
        host = create.get("host")

        if host is None:
            # An omitted `host` inherits k3d's own default rather than a value
            # this repo controls, so the binding stops being desired state.
            # Require it to be declared explicitly.
            offenders.append(f"{path.name}: registries.create.host not declared")
            continue

        try:
            address = ipaddress.ip_address(str(host))
        except ValueError:
            offenders.append(
                f"{path.name}: registries.create.host={host!r} is not an IP literal"
            )
            continue

        # is_loopback (not string equality) so ::1 passes while 0.0.0.0, :: and
        # any routable address fail.
        if not address.is_loopback:
            offenders.append(
                f"{path.name}: registries.create.host={host!r} is not loopback "
                "-> unauthenticated registry reachable off-host"
            )

    assert checked, (
        "no k3d-*.yaml declares registries.create — the invariant would be "
        "vacuous; if managed registries were removed on purpose, delete this test"
    )
    assert not offenders, (
        "unauthenticated k3d registry published beyond loopback:\n  "
        + "\n  ".join(offenders)
        + "\n\nUse host: \"127.0.0.1\". Cluster nodes reach the registry over the "
        "docker network by hostname, so loopback does not break image pulls."
    )
