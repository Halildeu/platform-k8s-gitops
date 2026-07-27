"""No script may hardcode another user's home directory — Faz 22 ops portability.

The platform host moved from `10.9.10.53` (user `halil`) to `10.9.10.15` (user `aiadmin`)
on 2026-07-23. Eight scripts hardcoded `/home/halil/bootstrap-drill/...` to read the test
Vault root token, so on the new host they resolve to a path that does not exist and cannot
exist — the user is gone. Measured 2026-07-27: every one of them was broken on `.15`,
including the ROPC migration that had landed the day before.

Nothing caught it because none of these scripts run in CI: they are operator-run against a
live host, so a broken absolute path fails only at the moment someone needs it.

Two shapes were wrong, and the second is the interesting one:

* plain hardcode — `python3 -c "...open('/home/halil/...')"`, no override possible;
* a **self-defeating intent gate** — the script accepted `VAULT_INIT_FILE` as an override
  and then asserted it equalled the hardcoded literal, so the override could never be used.
  The gate's intent (refuse being silently repointed at prod) is legitimate; pinning it to
  a stale absolute path is what broke. Fixed by pinning against a resolved
  `*_DEFAULT` variable instead, which keeps the gate exactly as strict.

`$HOME` is the portable form. This guard keeps the fix from eroding one script at a time.
"""

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SEARCH_ROOTS = ("scripts", "bootstrap")

# Scope: the bootstrap-drill tree, which holds Vault init material (root tokens,
# gate passwords). A stale absolute path there is a HARD failure — the script cannot
# read the credential and cannot continue.
#
# Deliberately NOT a blanket "no /home/<user>/" rule. Measured 2026-07-27: 56 such
# lines across 21 scripts, and most are not defects —
#   /home/runner/...            the GitHub self-hosted runner's real home (correct)
#   candidate-path lists        try several locations; a stale entry just never matches
#   backup/log/lock dirs        env-overridable; WHERE backups land on the new host is
#                               an operational decision with data implications, not a
#                               mechanical rename
# A guard that failed on those would be noise, and noise gets suppressed. The wider
# sweep is tracked separately with that measurement attached.
HARDCODED_HOME = re.compile(r"/(?:home|Users)/[A-Za-z][A-Za-z0-9._-]*/bootstrap-drill/")

# Comment lines may legitimately mention the old path when explaining the migration.
COMMENT = re.compile(r"^\s*#")


def _shell_scripts() -> list[Path]:
    """Glob discovery, so a script added next month is covered on landing."""
    found: list[Path] = []
    for root in SEARCH_ROOTS:
        found.extend((REPO_ROOT / root).rglob("*.sh"))
    return sorted(p for p in found if p.is_file())


def test_shell_scripts_are_discoverable():
    """A silently empty glob would make the assertion below vacuous."""
    scripts = _shell_scripts()
    assert len(scripts) > 20, f"only {len(scripts)} shell scripts discovered — glob looks wrong"


def test_no_script_hardcodes_a_user_home_directory():
    offenders: list[str] = []
    for path in _shell_scripts():
        rel = path.relative_to(REPO_ROOT)
        for lineno, line in enumerate(path.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
            if COMMENT.match(line):
                continue
            m = HARDCODED_HOME.search(line)
            if m:
                offenders.append(f"{rel}:{lineno}: {m.group(0)!r} — use $HOME")
    assert not offenders, (
        "hardcoded home directory on a bootstrap-drill credential path:\n  "
        + "\n  ".join(offenders)
        + "\n\nThe host moved 53->15 and the user changed halil->aiadmin; an absolute "
          "/home/<user>/ path cannot resolve on the new host. Use $HOME, and if an intent "
          "gate pins the value, pin it against a resolved *_DEFAULT variable rather than a "
          "literal path."
    )
