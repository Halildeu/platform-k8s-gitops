# TEST GPU host reboot resilience (gitops#3807)

Tracked by [#3807](https://github.com/Halildeu/platform-k8s-gitops/issues/3807).
TEST only. It changes no production host, model, source pin or historical analysis.

## Why

The 2026-09-15 reboot of the TEST GPU host left recording analysis down. The outage had three independent causes:

1. **Ollama:** It ran only from the tray app in the `denetimpc` session, so it did not come back after the reboot.
2. **meeting-ai:** It probed Ollama once with a 3 s timeout and exited non-zero ("refusing mock fallback"). Task Scheduler's `RestartOnFailure` retries only a failed *launch*, not a non-zero exit.
3. **Caddy:** `caddy.exe` started before WireGuard had assigned `10.99.0.2`, exited 1 on the bind error and was never retried. A duplicate `Workcube-Caddy-mTLS` boot task on the same Caddyfile failed the same way.

## State

| Part | Mechanism | Status |
|---|---|---|
| Ollama | `platform-ai-ollama-test` S4U boot task as `svc-ai-test`. The launcher `test-ollama-boot.ps1` and its runbook are in draft [#3791](https://github.com/Halildeu/platform-k8s-gitops/pull/3791); the host runs launcher sha256 `96764080…`. | Live since 2026-09-23 11:56Z. GPU placement equals the old tray instance: 4284 MiB of `qwen3.8:27b`. |
| meeting-ai | Bounded Ollama wait, default 600 s, still fails closed | platform-ai#351, then the exact-SHA GPU rollout |
| Caddy | `scripts/faz24/ensure_caddy_boot_retry.ps1`: boot trigger `PT1M` delay plus a 5-minute re-launch trigger, `IgnoreNew`; owned action unchanged | Apply after merge |
| Duplicate Caddy task | `Workcube-Caddy-mTLS` disabled, never deleted | Disabled 2026-09-23 |

## Caddy procedure (elevated Windows PowerShell 5.1 on the GPU host)

1. Keep a rollback copy first:

   ```powershell
   Export-ScheduledTask -TaskName CaddyI7AppMtls | Set-Content C:\ProgramData\AcikTestOps\3807\CaddyI7AppMtls.before.xml
   ```

2. Run the script in `-Mode Verify`. It changes nothing and exits 1 while the retry triggers are missing.
3. Run it in `-Mode Apply`, then run `-Mode Verify` again. Expect:
   - `retryTriggersPresent=true`
   - `duplicateState=Disabled`
   - `taskState=Running`
   - `listeners=[8243,8244]`

The script refuses to proceed if the owned action or principal differs from `C:\caddy\caddy.exe run --config C:\caddy\Caddyfile` as SYSTEM. It also refuses while the duplicate task is running.

`renew_test_live_mtls.ps1` keeps working: it still stops and starts the same task. With `IgnoreNew`, the periodic trigger is a no-op while Caddy runs.

**Rollback:**

```powershell
Register-ScheduledTask -TaskName CaddyI7AppMtls -Xml (Get-Content -Raw C:\ProgramData\AcikTestOps\3807\CaddyI7AppMtls.before.xml) -Force
```

Re-enable the duplicate only if it is really needed: `Enable-ScheduledTask -TaskName Workcube-Caddy-mTLS`.

## Ollama switch: measured lessons (2026-09-23)

- **Stop the runner too.** Stopping the tray app must also stop its `lib\ollama\llama-server.exe` children. An orphaned runner held 4257 MiB of VRAM, and the new server then placed the model almost entirely on the CPU (`size_vram` 413 MiB, 54 s load).
- **Wait for GPU discovery.** Ollama logs `Listening on` before GPU discovery ends. A cold discovery took about 21 s. Load the first model only after discovery.
- **Measure against the baseline.** Acceptance is equality with the baseline `size_vram`, not `size_vram > 0`. Per-process VRAM on WDDM comes from `\GPU Process Memory(*)\Dedicated Usage`; `nvidia-smi` shows `[N/A]` there.
- **Identity is not the limit.** Both SYSTEM and the non-administrator S4U account see CUDA in session 0.
- **Rollback:** Disable `platform-ai-ollama-test`. Move `C:\Users\denetimpc\AppData\Local\AcikTestOps\3807\backup\Ollama.lnk` back to the Startup folder and start the tray app in the `denetimpc` session.

## Reboot acceptance (not yet observed)

A reboot interrupts STT and analysis for every TEST user, so it runs only in a window agreed with the Faz 24 owner, after the meeting-ai wait is deployed.

1. **Before:** record task states, listeners, `11434` owner and meeting-ai `/ready`.
2. **Reboot.** Within 10 minutes, without manual action:
   - `8200`, `8243`, `8244`, `8300` and `11434` listen;
   - `11434` is owned by `svc-ai-test`;
   - meeting-ai `/ready` matches the recorded state.
3. **Functional check:** Produce a NEW persisted analysis through the canonical synthetic recording chain and reopen it in the browser. Readiness alone is not acceptance.

Until this is observed, reboot resilience stays unverified.
