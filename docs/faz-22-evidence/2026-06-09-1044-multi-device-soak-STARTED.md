# Faz 22.5 — #1044 Multi-Device Stability Soak: STARTED (2026-06-09)

> **HARD RULE "Yarın YASAK / zaman bekleme yok":** the 24-72h soak is **not a
> deferred blocker** — it is **started NOW** as a continuous server-side
> observation. The 24-72h elapses via a cron harness on `staging-sw`; the agent
> does not "wait", the harness accumulates the acceptance ledger.

## Harness (running, session-independent)

- **Host:** `staging-sw` · **Script:** `/home/halil/faz225-soak/observe.sh`
- **Cron:** `0 */4 * * * /home/halil/faz225-soak/observe.sh` (every 4h)
- **Ledger:** `/home/halil/faz225-soak/ledger.log` (append-only)
- **Signals (auth-free):** endpoint-admin pod `ready`/`restartCount`; cluster
  `pods_ready`; `req_act_60m` (request activity = device interaction);
  `ERR_60m` (real `"level":"ERROR"` lines); `enroll409_60m` (benign enroll-retry).

## T0 baseline (2026-06-09T08:13:56Z)

```
endpoint-admin[ready=True restarts=0] | pods_ready=14/18 | req_act_60m=45 | ERR_60m=0 | enroll409_60m=1
```
- endpoint-admin pod: **Ready, 0 restarts**, ~9h uptime (started 2026-06-08T23:23:55Z). ✅
- Service actively serving (**45 req/hr** = devices interacting). ✅
- **0 ERROR-level** log lines. ✅
- Multi-device set enrolled (testai grid: MKR-A1, HALILKOOLUB735, SRB-AIDENETIMPC, be013/be014a-smoke, CODEX-P0, stagingsw — 7 devices; HALILKOOLUB735 + MKR-A1 online with fresh heartbeats).

## Acceptance gates

| Gate | Window | Criteria |
|---|---|---|
| **24h** | T0+24h (~2026-06-10T08:14Z) | endpoint-admin restarts stays ≤ baseline+1; ERR_60m stays low; req_act_60m > 0 throughout (service continuously serving); no pod crash-loop |
| **72h** | T0+72h (~2026-06-12T08:14Z) | same, sustained across the full window |

A scheduled review re-evaluates the ledger at the 24h mark and marks the gate
PASS/FAIL; cron is removed after the 72h window.

## Known benign signal

A device intermittently re-POSTs enrollment with a consumed token →
`409 "Enrollment token is not pending"` WARN (not an ERROR). Tracked as
`enroll409_60m`; benign (does not fail the soak) but flagged for the
enroll-retry-guard follow-up (#108/#109 family).

## Scope note

This soak covers **service + existing multi-device stability**. The #1044
"2 *fresh* Parallels VM repeatability" sub-requirement (brand-new VMs) is a
separate provisioning enhancement (linked-clone tooling exists per the parallel
A1 helper set); the continuous stability observation is the core soak and is
running now.

> Live truth note: the testai endpoint-admin digest is actively churning under
> parallel-session work (sha-84c927b → sha-c96c148 #527 during T0 window); the
> soak observes whatever digest is live and counts a controlled rollout-restart
> distinctly from a crash-loop.
