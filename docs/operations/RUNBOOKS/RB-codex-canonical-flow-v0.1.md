# RB-codex-canonical-flow-v0.1 – Kanonik Codex Akışı (Happy Path)

ID: RB-codex-canonical-flow-v0.1  
Service: ops-local  
Status: Draft  
Owner: @team/platform

-------------------------------------------------------------------------------
1. AMAÇ
-------------------------------------------------------------------------------

- Codex ile çalışırken “happy path” adımlarını standartlaştırmak.
- Hedef: daha az gürültü, daha yüksek kanıt (evidence), daha az sapma.

-------------------------------------------------------------------------------
2. KAPSAM
-------------------------------------------------------------------------------

- Repo: `Halildeu/platform-ssot`
- Kapsam: Codex ile yapılan local iş akışı (planlama, doküman/skript değişikliği, gate, commit/push).
- Canonical authority:
  - `docs/OPERATIONS/OPO-AUTHORITY-MAP.v1.md`
  - `docs/OPERATIONS/AI-MULTIREPO-OPERATING-CONTRACT.v1.md`
  - `standards.lock`
- Dış kapsam:
  - CI fail → log-digest → local autopilot gibi “failure loop” (ayrı runbook’ta standardize edilecek).

-------------------------------------------------------------------------------
3. BAŞLATMA / DURDURMA
-------------------------------------------------------------------------------

### 3.1 Kanonik Happy Path (v0.1)
0) **MODE** (`DONE|PLAN|READ_ONLY`)
   - Her yanıt `MODE: DONE|PLAN|READ_ONLY` ile başlar.
   - MODE != PLAN iken plan dili görünmez; “Planlanan Değişiklikler” yazılmaz.
   - MODE = PLAN iken “Uygulanan Değişiklikler” yazılmaz.

0.5) **Canonical Git Öncesi Gate Entry Points**
   - Local gate adı: `local-gate-chain`
   - Runner: `scripts/run_local_gate_chain.sh`
   - Guard: `scripts/require_local_gate.sh`
   - Hook installer: `scripts/setup_local_git_hooks.sh`
   - Hook enforce: `.githooks/pre-commit`, `.githooks/pre-push`
   - PASS artifact: `.cache/reports/local-gate-chain/status.json`

1) **WORK LOG – UI Mirror**
   - `Ran/Edited/Reviewed/Considering` satırları ile yapılan işleri ham şekilde yansıt.

2) **Local Gate (Zorunlu)**
   - `bash scripts/setup_local_git_hooks.sh`
   - `bash scripts/run_local_gate_chain.sh`
   - Git geçişi sırasında `scripts/require_local_gate.sh --auto-run` hook içinden
     zorunlu çağrılır; PASS artifact yoksa commit/push durur.

3) **RESULT**
   - “Ne çıktı?” (1–5 madde, geçmiş zaman).

4) **EVIDENCE POINTERS**
   - Serbest metin yok; EVIDENCE POINTERS yalnız code block içinde yazılır.
   - Minimum:
     ```text
     gate: PASS|FAIL
     execution_log: .autopilot-tmp/execution-log/execution-log.md
     chatlog: .autopilot-tmp/codex-chatlog/latest.md
     ```
   - Koşullu (çalıştırıldıysa, aynı code block içine):
     ```text
     flow_report: .autopilot-tmp/flow-mining/flow-report.md
     flow_stats: .autopilot-tmp/flow-mining/flow-stats.json
     ```
   - Opsiyonel meta (aynı code block içine): `branch`, `sha`, `commit`, `pr`

5) **Uygulanan Değişiklikler**
   - `dosya:line — ... eklendi/güncellendi/hizalandı` (emir kipi yok).

6) **NEXT**
   - Yoksa: `NEXT: none`
   - Varsa: 1–5 gerçek iş maddesi

7) **Publish**
   - `git commit` + `git push` (+ gerekiyorsa PR).

### 3.2 Durdurma
- Bu akış “local-only”dir; özel bir stop adımı yoktur.
- Local çıktıları temizlemek için (opsiyonel): `.autopilot-tmp/` altındaki dizinler silinebilir (gitignored).

-------------------------------------------------------------------------------
4. GÖZLEMLEME / LOG / METRİKLER
-------------------------------------------------------------------------------

- Local gate kanıtı:
  - `.cache/reports/local-gate-chain/status.json`
  - `.cache/reports/local-gate-chain/summary.txt`
  - `.cache/reports/local-gate-chain/logs/*`
- Local chat transcript:
  - `.autopilot-tmp/codex-chatlog/latest.md`
  - `.autopilot-tmp/codex-chatlog/YYYYMMDD.md`
- Process mining (local, gitignored):
  - `python3 scripts/ops/analyze_codex_flow.py --days 7`
  - Çıktılar:
    - `.autopilot-tmp/flow-mining/flow-report.md`
    - `.autopilot-tmp/flow-mining/flow-stats.json`

-------------------------------------------------------------------------------
5. ARIZA DURUMLARI VE ADIMLAR
-------------------------------------------------------------------------------

- [ ] Arıza senaryosu 1 – Gate FAIL
  - Given: local gate FAIL
  - When: `.cache/reports/local-gate-chain/summary.txt` içinde failing step görülür
  - Then:
    1) İlk failing step log’unu aç: `.cache/reports/local-gate-chain/logs/*`
    2) Hedefli düzeltmeyi yap (docs/scripts).
    3) Local gate’i tekrar koş: `bash scripts/run_local_gate_chain.sh`

-------------------------------------------------------------------------------
6. ÖZET
-------------------------------------------------------------------------------

- Standart akış: WORK LOG → local gate → RESULT → EVIDENCE → change-log → NEXT → commit/push.
- Git öncesi zorunlu eşik: `.cache/reports/local-gate-chain/status.json` PASS olmadan commit/push yok.
- Kanıt dosyaları repoya girmez: `.autopilot-tmp/**` ve `.cache/reports/local-gate-chain/**` gitignored.

-------------------------------------------------------------------------------
7. LİNKLER (İSTEĞE BAĞLI)
-------------------------------------------------------------------------------

- SSOT: `docs/OPERATIONS/OPO-AUTHORITY-MAP.v1.md`
- Transition-active guide: `AGENT-CODEX.core.md`
- Runbook: `docs/04-operations/RUNBOOKS/RB-codex-chat-transcript.md`
- Script: `scripts/setup_local_git_hooks.sh`
- Script: `scripts/run_local_gate_chain.sh`
- Script: `scripts/require_local_gate.sh`
- Script: `scripts/ops/analyze_codex_flow.py`
- Local outputs:
  - `.cache/reports/local-gate-chain/status.json`
  - `.cache/reports/local-gate-chain/summary.txt`
  - `.autopilot-tmp/flow-mining/flow-report.md`

-------------------------------------------------------------------------------
X. CHAT FORMAT LINT (LOCAL, NON-BLOCKING)
-------------------------------------------------------------------------------

- Günlük chatlog formatını doğrulamak için:
  - `python3 scripts/ops/lint_codex_chat_format.py`
- Rapor:
  - `.autopilot-tmp/flow-mining/chat-format-report.md`
