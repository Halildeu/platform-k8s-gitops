# RB Faz 22.2.A - #1044 two-device operator packet

> **Status**: Operator packet for #1044 evidence collection.
> **Scope**: Two additional A1 non-domain Windows lab devices plus the existing
> `HALILKOOLUB735` baseline. This packet is a short execution surface for the
> longer canonical runbook `RB-faz22-non-domain-windows-pilot.md`.
> **Boundary**: local A1 / workgroup evidence only. No domain AD password reset,
> cached-domain credential update, M365/Entra reset, SMB/file action, pre-logon
> VPN, production/domain-wide rollout, or real-user destructive action claim.

## 1. Use this packet when

- #1044 is still open and the two user-owned / local lab Windows devices are
  ready to be exercised.
- You want the shortest safe checklist for collecting the evidence bundle.
- The long runbook remains canonical for policy and rationale; this packet is
  only the operator execution shortcut.

Do not use this packet for `acik.local` domain-joined IT pilot. That remains
`RB-faz22-endpoint-pilot-it-owned.md` plus #1037 / #1015.

## 2. Hard guardrails

- No destructive command on the two additional devices.
- Allowed runtime command for #1044 repeatability: `COLLECT_INVENTORY` /
  inventory refresh and read-only diagnostics only.
- Do not run local password change, user lock/unlock, user disable/enable,
  uninstall, SMB/file action, raw PowerShell, or arbitrary shell on those
  devices as part of #1044.
- Do not paste JWT, enrollment token, password, private key, webhook URL, or
  raw credential into issue comments, chat, evidence docs, process arguments, or
  shell history.
- Each device must have a unique hostname and a distinct backend device ID.

The local `HALILKOOLUB735` password/account smokes are already recorded as
separate evidence. They do not authorize destructive operations on the two
additional #1044 devices.

## 3. Device setup checklist

Fill this per device before running diagnostics:

| Field | Device 1 | Device 2 |
|---|---|---|
| VM / PC name |  |  |
| Hostname |  |  |
| Device class | A1 | A1 |
| Workgroup / non-domain confirmed |  |  |
| Backend reachable `testai.acik.com:443` |  |  |
| Agent installed |  |  |
| Enrollment token source recorded without token value |  |  |
| Backend device ID |  |  |
| `EndpointAgent` service running |  |  |
| Local admin availability confirmed out-of-band |  |  |

## 4. Manifest-driven evidence pack (recommended)

Use the wrapper when you want one reviewed packet that contains the exact
operator checklist and shell script for the two-device batch. The manifest is
explicitly no secrets: do not put JWTs, enrollment tokens, passwords, private
keys, webhook URLs, or raw credentials in it.

Create the example manifest:

```bash
python3 scripts/faz22-non-domain/a1-operator-evidence-pack.py \
  --write-example-manifest /tmp/faz22-a1-operator-manifest.json
```

Edit `/tmp/faz22-a1-operator-manifest.json` with the actual VM names,
hostnames, backend device IDs, expected evidence doc names, and operator label.
Keep `deviceId` as `PENDING` until the backend ID is known.

Generate the review packet:

```bash
python3 scripts/faz22-non-domain/a1-operator-evidence-pack.py \
  --manifest /tmp/faz22-a1-operator-manifest.json \
  --output-dir /tmp/faz22-a1-operator-pack \
  --include-winget-egress
```

Review both generated files before executing anything:

```text
/tmp/faz22-a1-operator-pack/operator-checklist.md
/tmp/faz22-a1-operator-pack/run-evidence-pack.sh
```

After the observation data is collected, the same wrapper can generate the
pilot-wide rollup draft. Replace `<timestamp>` with the timestamp from the soak
output filename:

```bash
python3 scripts/faz22-non-domain/a1-operator-evidence-pack.py \
  --manifest /tmp/faz22-a1-operator-manifest.json \
  --output-dir /tmp/faz22-a1-operator-pack \
  --soak-output /tmp/faz22-a1-soak-rollup-<timestamp>.txt \
  --generate-rollup-doc
```

Boundary: the wrapper does not accept secrets, does not dispatch backend
commands by default, and does not complete #1044. It only turns the device
manifest into a repeatable operator checklist, command script, per-device
evidence drafts, and optional rollup draft.

## 5. Parallels linked-clone path

Use this only if the two devices are local Parallels clones. The helper is
dry-run by default and refuses to clone a running parent VM in execute mode.

```bash
# Dry-run: no VM mutation.
bash scripts/faz22-non-domain/a1-linked-clone-batch.sh

# Execute only after the operator has gracefully stopped or suspended the
# parent VM from Parallels GUI.
bash scripts/faz22-non-domain/a1-linked-clone-batch.sh --execute
```

After clone creation, personalize each VM:

- Set a unique hostname such as `NONDOMAIN-W11-LAB-01` and
  `NONDOMAIN-W11-LAB-02`.
- Remove any stale parent agent state before enrollment, or install/enroll with
  a fresh one-time token.
- Verify the backend device IDs are not the parent `HALILKOOLUB735` ID.

## 6. Read-only diagnostics

Run diagnostics only after both VMs are running and enrolled. This helper does
not dispatch backend commands and does not mutate the guest.

```bash
# Preflight: verifies VM names and running state only.
bash scripts/faz22-non-domain/a1-local-vm-diagnostics.sh \
  --dry-run \
  --vm "Windows 11" \
  --vm "NONDOMAIN-W11-LAB-01" \
  --vm "NONDOMAIN-W11-LAB-02"

# Read-only evidence collection.
bash scripts/faz22-non-domain/a1-local-vm-diagnostics.sh \
  --vm "Windows 11" \
  --vm "NONDOMAIN-W11-LAB-01" \
  --vm "NONDOMAIN-W11-LAB-02"

# Optional longer WinGet egress probe.
bash scripts/faz22-non-domain/a1-local-vm-diagnostics.sh \
  --include-winget-egress \
  --section-timeout-seconds 180 \
  --vm "NONDOMAIN-W11-LAB-01" \
  --vm "NONDOMAIN-W11-LAB-02"
```

Expected output location:

```text
/tmp/faz22-a1-local-vm-diagnostics-<timestamp>/<safe-vm-name>/read-only-diagnostics.txt
```

## 7. Per-device evidence draft

Generate a `PARTIAL` draft for each device. Fill the backend command and soak
facts after the non-destructive command smoke and observation window.

```bash
python3 scripts/faz22-non-domain/a1-evidence-doc-from-diagnostics.py \
  --diagnostics-file /tmp/faz22-a1-local-vm-diagnostics-<timestamp>/NONDOMAIN-W11-LAB-01/read-only-diagnostics.txt \
  --output-dir docs/faz-22-evidence \
  --device-id <backend-device-id-for-lab-01> \
  --operator "local-operator" \
  --install-method "A1 lab install"

python3 scripts/faz22-non-domain/a1-evidence-doc-from-diagnostics.py \
  --diagnostics-file /tmp/faz22-a1-local-vm-diagnostics-<timestamp>/NONDOMAIN-W11-LAB-02/read-only-diagnostics.txt \
  --output-dir docs/faz-22-evidence \
  --device-id <backend-device-id-for-lab-02> \
  --operator "local-operator" \
  --install-method "A1 lab install"
```

The generated draft is not a PASS verdict. It is the per-device evidence shell
that later receives command lifecycle and soak facts.

## 8. Non-destructive command smoke

For each additional device, queue only `COLLECT_INVENTORY` or the equivalent
inventory refresh path through endpoint-admin.

Evidence to capture per device:

- backend command ID
- terminal status
- delivered / started / completed timestamps
- result summary
- audit row ID or audit event evidence
- no raw token / JWT / credential in captured output

Acceptance expectation for #1044:

```text
COLLECT_INVENTORY terminal state: SUCCEEDED
No unexplained terminal failures
No destructive command issued on the two additional devices
```

## 9. Observation roll-up

The helper is SELECT-only. It does not dispatch commands or mutate the DB.

```bash
# Dry-run: prints SQL and thresholds.
bash scripts/faz22-non-domain/a1-soak-rollup.sh \
  --device-id <device-id-1> \
  --device-id <device-id-2>

# Execute through the existing test DB context.
bash scripts/faz22-non-domain/a1-soak-rollup.sh \
  --execute \
  --ssh-target halil@staging-sw \
  --device-id <halilkoolub735-device-id> \
  --device-id <device-id-1> \
  --device-id <device-id-2> \
  > /tmp/faz22-a1-soak-rollup-<timestamp>.txt
```

Generate the pilot-wide rollup draft:

```bash
python3 scripts/faz22-non-domain/a1-rollup-doc-from-soak.py \
  --soak-output /tmp/faz22-a1-soak-rollup-<timestamp>.txt \
  --output-dir docs/faz-22-evidence \
  --device '<halilkoolub735-device-id>=HALILKOOLUB735,A1,./2026-06-07-non-domain-pilot-tierA1-HALILKOOLUB735-current.md,PARTIAL' \
  --device '<device-id-1>=NONDOMAIN-W11-LAB-01,A1,./<device-1-evidence-doc>.md,PARTIAL' \
  --device '<device-id-2>=NONDOMAIN-W11-LAB-02,A1,./<device-2-evidence-doc>.md,PARTIAL'
```

Do not mark #1044 out of Needs Verify based on helper output alone. Operator
notes must explain planned reboot/sleep windows and any offline gap over 30
minutes.

## 10. Final PR packet

When the two-device batch is ready, the PR should include:

- two per-device evidence docs
- one pilot-wide rollup doc
- current-state delta summarizing device count, command facts, and observation
  facts
- PR body with `Tracked by #1044`, Cross-AI block, and ADR-0011 boundary block
- no `Closes`, `Fixes`, or `Resolves` language

Review boundaries:

- Implementer AI and reviewer AI must be provider-distinct.
- No overclaim: #1044 repeatability evidence is not domain-wide rollout,
  password-reset readiness, or production cutover readiness.
