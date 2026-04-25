# RB-codex-chat-transcript – Codex Chat Transcript (Local-only)

ID: RB-codex-chat-transcript  
Service: ops-local  
Status: Draft  
Owner: @team/platform

-------------------------------------------------------------------------------
1. AMAÇ
-------------------------------------------------------------------------------

- Codex’in chat’te yazdığı tüm metni kopyalamadan, yerel transcript olarak biriktirmek.
- Transcript formatı: verbatim + `BEGIN_CODEX_RESPONSE`/`END_CODEX_RESPONSE` + `WORK LOG – UI Mirror`.

-------------------------------------------------------------------------------
2. KAPSAM
-------------------------------------------------------------------------------

- Local-only: `.autopilot-tmp/codex-chatlog/` (gitignored).
- Günlük transcript: `.autopilot-tmp/codex-chatlog/YYYYMMDD.md` (UTC).
- Pointer: `.autopilot-tmp/codex-chatlog/latest.md` → bugünün dosyası.
- Kapsam dışı:
  - Token/secret/credential içeren metinlerin transcript’e yazdırılması (yasak).
  - Transcript’in repo’ya commit edilmesi (yasak; gitignored olmalı).

-------------------------------------------------------------------------------
3. BAŞLATMA / DURDURMA
-------------------------------------------------------------------------------

- Başlat (günlük rotasyon/pointer):
  - `bash scripts/ops/codex_chatlog_set_latest.sh`
  - Beklenen: `.autopilot-tmp/codex-chatlog/YYYYMMDD.md` oluşur ve `latest.md` bugünü gösterir.
- Durdurma (local):
  - Bu mekanizma local-only’dir; istenmiyorsa `.autopilot-tmp/codex-chatlog/` dizini silinebilir veya ignore edilerek kullanılmayabilir.
- Legacy ayrıştırma:
  - Verbatim kuralı devreye girerken eski `latest.md` arşivlenir ve temiz `latest.md` başlatılır.

-------------------------------------------------------------------------------
4. GÖZLEMLEME / LOG / METRİKLER
-------------------------------------------------------------------------------

- Hızlı kontrol:
  - `tail -n 200 .autopilot-tmp/codex-chatlog/latest.md`
  - `rg -n \"BEGIN_CODEX_RESPONSE|END_CODEX_RESPONSE\" .autopilot-tmp/codex-chatlog/latest.md`
- Beklenen minimum:
  - Her yanıtta `WORK LOG – UI Mirror` bloğu vardır.
  - Komut çalıştıysa `Ran <cmd>` satırı vardır.
  - Dosya değiştiyse `Edited <path> +a -b` satırı vardır.
- Local doc-qa standardı (execution log):
  - `python3 scripts/run_doc_qa_execution_log_local.py --out-dir .autopilot-tmp/execution-log`

-------------------------------------------------------------------------------
5. ARIZA DURUMLARI VE ADIMLAR
-------------------------------------------------------------------------------

- [ ] Arıza senaryosu 1 – `latest.md` bugünü göstermiyor:
  - Given: `latest.md` yok veya yanlış güne bağlı.
  - When: transcript “günlük dosya” yerine eski/boş dosyaya yazılıyor.
  - Then:
    - `bash scripts/ops/codex_chatlog_set_latest.sh` çalıştır.
    - `ls -la .autopilot-tmp/codex-chatlog` ile `latest.md -> YYYYMMDD.md` doğrula.

- [ ] Arıza senaryosu 2 – Verbatim marker eksik:
  - Given: transcript içinde `BEGIN_CODEX_RESPONSE`/`END_CODEX_RESPONSE` yok.
  - When: yanıtlar tamlık kuralına uymuyor.
  - Then:
    - `AGENT-CODEX.core.md` içindeki “VERBATIM ZORUNLULUK / TAMLIK KURALI” kuralını doğrula.
    - Yeni yanıtla tekrar dene; problem sürerse rule enforcement mekanizmasını gözden geçir.

-------------------------------------------------------------------------------
6. ÖZET
-------------------------------------------------------------------------------

- Transcript local-only’dir ve gitignored kalmalıdır.
- Her yanıt verbatim + marker’lı + `WORK LOG – UI Mirror` içermelidir.
- Günlük rotasyon/pointer için helper: `bash scripts/ops/codex_chatlog_set_latest.sh`.

-------------------------------------------------------------------------------
7. LİNKLER (İSTEĞE BAĞLI)
-------------------------------------------------------------------------------

- Core rules: `AGENT-CODEX.core.md`
- Helper: `scripts/ops/codex_chatlog_set_latest.sh`
- Doc-qa local runner: `scripts/run_doc_qa_execution_log_local.py`
- Template: `docs/99-templates/RUNBOOK.template.md`

-------------------------------------------------------------------------------
X. EVIDENCE POINTERS (CODE BLOCK, STRICT)
-------------------------------------------------------------------------------

- EVIDENCE POINTERS serbest metin değildir; içerik yalnız code block içinde literal path satırlarıyla yazılır.
- KISALTMA YASAK: `execution-log.md`, `latest.md`, `flow-report.md` gibi kısaltmalar kullanılmaz.
- Path değerleri `.autopilot-tmp/` ile başlayan full path olur.

Zorunlu code block (minimum satırlar):
```text
gate: PASS|FAIL
execution_log: .autopilot-tmp/execution-log/execution-log.md
chatlog: .autopilot-tmp/codex-chatlog/latest.md
```

Koşullu satırlar (komut çalıştırıldıysa, aynı code block içine eklenir):
```text
flow_report: .autopilot-tmp/flow-mining/flow-report.md
flow_stats: .autopilot-tmp/flow-mining/flow-stats.json
```

SELF-CHECK (ZORUNLU)
- Yanıt gönderilmeden önce EVIDENCE POINTERS code block satırlarında `.autopilot-tmp/` geçtiği doğrulanır (en az `execution_log` ve `chatlog`).
- Eğer geçmiyorsa: EVIDENCE POINTERS yanlış yazılmış demektir ve düzeltilmeden yanıt gönderilmez.

-------------------------------------------------------------------------------
X. MODE (DONE/PLAN/READ_ONLY)
-------------------------------------------------------------------------------

- Her yanıtın en üstünde MODE satırı bulunur:
  - `MODE: DONE` | `MODE: PLAN` | `MODE: READ_ONLY`
- MODE != PLAN iken “plan dili” görünmez; “Planlanan Değişiklikler” bölümü yazılmaz.
- MODE = PLAN iken “Uygulanan Değişiklikler” yazılmaz; bunun yerine opsiyonel “Planlanan Değişiklikler” yazılır.
