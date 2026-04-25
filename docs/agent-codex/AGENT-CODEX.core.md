# Çekirdek Kurallar

> Transition Durumu: Bu dosya transition-active rehber katmanındadır;
> canonical OPO authority değildir. Canonical kaynaklar:
> `standards.lock`,
> `docs/OPERATIONS/AI-MULTIREPO-OPERATING-CONTRACT.v1.md`,
> `docs/OPERATIONS/OPO-AUTHORITY-MAP.v1.md`.

## 1. Genel

- Tüm açıklamalar Türkçe yazılmalıdır.
- Cevaplar mümkün olduğunca yapılandırılmış ve kısa olmalıdır.
- Her görev, [BE] / [WEB] / [MOB] / [AI] / [DATA] / [DOC] tiplerinden birine
  map edilmeye çalışılmalıdır.

## 2. Doküman öncelik sırası

1. `standards.lock`
2. `docs/OPERATIONS/AI-MULTIREPO-OPERATING-CONTRACT.v1.md`
3. `docs/OPERATIONS/OPO-AUTHORITY-MAP.v1.md`
4. `AGENTS.md` (giriş rotası)
5. `docs/03-delivery/PROJECT-FLOW.md` ve ilişkili current delivery dokümanları
6. Bu dosya (çekirdek transition rehberi)
7. `DOC-HIERARCHY.md`
8. `NAMING.md`
9. İlgili alan transition rehberi
10. İlgili layout / style / architecture dokümanları

Çelişki durumunda bu sıra baz alınır; transition-active dosyalar canonical
katmanı override edemez.

## 3. Cevap formatı

### 3.0 MODE (ZORUNLU)
Yanıtın en üstünde tek satır MODE yazılır:
- `MODE: DONE` (değişiklik yapıldı)
- `MODE: PLAN` (sadece plan/öneri; değişiklik yapılmadı)
- `MODE: READ_ONLY` (keşif/rapor; repo değişmedi)

Kural:
- MODE != PLAN iken “plan dili” görünmez; “Planlanan Değişiklikler” bölümü yazılmaz.
- MODE = PLAN iken “Uygulanan Değişiklikler” yazılmaz; bunun yerine opsiyonel “Planlanan Değişiklikler” yazılır.

Her görevde varsayılan yapı (sıra zorunlu):

1) MODE: DONE|PLAN|READ_ONLY (zorunlu)
2) WORK LOG – UI Mirror (zorunlu)
3) WORK LOG – Summary (opsiyonel)
4) RESULT (zorunlu)
5) EVIDENCE POINTERS (zorunlu)
6) Uygulanan Değişiklikler (MODE=DONE|READ_ONLY)
7) NEXT (zorunlu)

### 3.1 WORK LOG (ZORUNLU, 2 KATMAN)
1) **WORK LOG – UI Mirror (Zorunlu)**
   - UI’daki listeyi metin olarak yansıtır: `Ran ...`, `Edited ... +x -y`, `Reviewed ...`, `Considering ...` vb.
   - 10–40 satır arası olabilir; kısa ve ham olmalı (paraphrase yok).
   - Komut çalıştırıldıysa: en az 1 `Ran <cmd>` satırı zorunlu.
   - `Ran` satırı komutun tamamını içerir (kısaltma/truncate yok).
   - Dosya değiştiyse: en az 1 `Edited <path> +a -b` satırı zorunlu.
2) **WORK LOG – Summary (Opsiyonel)**
   - 3–8 satırlık özet (insan okuması için).

Not: WORK LOG token/secret içermez.

### 3.2 RESULT (ZORUNLU)
- “Ne çıktı?” sorusuna cevap verir.
- 1–5 madde, geçmiş zaman (eklendi/güncellendi/çıkarıldı).
- Emir kipi yok.

### 3.3 EVIDENCE POINTERS (ZORUNLU)
- “Bunu nereden doğrularım?” sorusuna cevap verir.
- **Serbest metin yok.** EVIDENCE POINTERS içeriği **yalnızca** code block içinde yazılır.
- **KISALTMA YASAK**: `execution-log.md`, `latest.md`, `flow-report.md` gibi kısaltmalar kullanılmaz; path değerleri `.autopilot-tmp/` ile başlayan full path olur.

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

Opsiyonel meta (aynı code block içine eklenir):
```text
branch: <name>
sha: <short>
commit: <sha>
pr: <url>
```

SELF-CHECK (ZORUNLU)
- Yanıt gönderilmeden önce EVIDENCE POINTERS code block satırlarında `.autopilot-tmp/` geçtiği doğrulanır (en az `execution_log` ve `chatlog`).
- Eğer geçmiyorsa: EVIDENCE POINTERS yanlış yazılmış demektir ve düzeltilmeden yanıt gönderilmez.


### 3.4 DOC-QA LOCAL STANDARDI (ZORUNLU)
- Local doğrulama/gate koşulacaksa varsayılan komut:
  - `python3 scripts/run_doc_qa_execution_log_local.py --out-dir .autopilot-tmp/execution-log`
- Bu komut:
  - doc-qa check setini çalıştırır
  - `.autopilot-tmp/execution-log/` altında `execution-log.md` ve `checks.json` üretir (raw loglar: `raw/`)
- Tek tek `check_doc_*` komutları yalnızca hedefli debug için kullanılmalıdır.
- WORK LOG – UI Mirror içinde bu komut `Ran python3 scripts/run_doc_qa_execution_log_local.py --out-dir .autopilot-tmp/execution-log` olarak görünmelidir.

### 3.5 Uygulanan Değişiklikler (MODE=DONE|READ_ONLY)
- Sadece “dosya yolu + değişiklik” içerir.
- Değişiklik bu görevde uygulandıysa: geçmiş zaman (örn. “eklendi/güncellendi/silindi”) yazılır.
- Emir kipi yok; “→ ekle/hizala/çalıştır” kullanılmaz.
- Format: `dosya:line — değişiklik` (parantezli `(line N)` kullanılmaz).
- MODE = PLAN iken bu bölüm yazılmaz.

Örnek:
- `docs/OPERATIONS/OPO-AUTHORITY-MAP.v1.md:51 — Geçiş kuralı netleştirildi.`

### 3.5.1 Planlanan Değişiklikler (MODE=PLAN, OPSİYONEL)
- Sadece MODE = PLAN iken yazılır.
- “dosya yolu + planlanan değişiklik” içerir.
- Emir kipi yok; “→ ekle/hizala/çalıştır” kullanılmaz.

### 3.6 NEXT (ZORUNLU)
- NEXT satır formatı zorunlu:
  - `NEXT: none`
  - veya `NEXT: optional — <kısa açıklama> — <link/komut>`
- 1–5 madde olabilir; her madde ayrı bir `NEXT: optional — ...` satırı olarak yazılır.


## 4. Riskli komutlar

Aşağıdaki komutlar **asla** otomatik önerilmez veya çalıştırılmaz:

- Veritabanı silme / drop komutları
- `git reset --hard`, `git clean -fdx`
- `rm -rf` ile kritik klasör silme

Bu tip işlemler gerekiyorsa:
- Önce riskler açıkça yazılır,
- Sonra insan onayı olmadan uygulanmaz.

## 5. İş seçimi (PROJECT-FLOW)

- Kullanıcı “sırada ne var / devam edelim” dediğinde, `docs/03-delivery/PROJECT-FLOW.md` içindeki Story tablosu esas alınır.
- Seçim kuralı: `Öncelik` en yüksek (DESC) ve `Durum != 🟩 Done` olan Story önce gelir.

## 6. Genel İş Yapış (SSOT)

- Önce deterministik scriptler: kontrol/rapor/gate/queue/tracker (tekrar üretilebilir sonuç).
- Yetmezse Codex: yalnız allowlist + limitler içinde düzenleme/implementasyon.
- Her fix localde yapılır: local validate → commit → push. (GitHub-side auto-fix yok.)
- needs-human (token/permission/infra/approval): Codex yalnız teşhis/kanıt üretir, otomatik fix yapmaz.

## 7. Local Chat Transcript (Kopyasız)

- Transcript dizini: `.autopilot-tmp/codex-chatlog/` (gitignored).
- Codex her yanıtının sonunda, kullanıcıya gönderdiği yanıtın **tam metnini** (verbatim) transcript’e append eder.
  - Yeniden biçimlendirme, paraphrase, kısaltma yapılmaz.
  - “Undo/Review” benzeri bloklar dahil, kullanıcıya giden metin ne ise aynen yazılır.

**VERBATIM ZORUNLULUK (Kopyasız / Birebir)**

**GÜNLÜK ROTASYON (UTC)**
- Transcript hedef dosyası: `.autopilot-tmp/codex-chatlog/YYYYMMDD.md` (UTC tarih).
- `latest.md` her zaman bugünün dosyasını gösterir (pointer/symlink). Yerel helper:
  - `bash scripts/ops/codex_chatlog_set_latest.sh`
- Her yanıt append akışı:
  1) `bash scripts/ops/codex_chatlog_set_latest.sh` (latest güncel)
  2) Bugünün dosyasına `--- ts_utc/branch/sha --- + BEGIN/END + verbatim` bloğunu append et.

**TAMLIK KURALI (NO DROP)**
- Verbatim blok, kullanıcıya görünen yanıt metninin *tamamını* içerir: `Undo`, `Review`, dosya listeleri, diff özetleri, linkler, boş satırlar dahil.
- Hiçbir satır atlanmaz, yeniden sıralanmaz, yeniden biçimlendirilmez.
- Her yanıt için `BEGIN_CODEX_RESPONSE` / `END_CODEX_RESPONSE` marker’ları zorunludur (opsiyonel değildir).

- Transcript’e yazılan ana blok aşağıdaki formatta olmak zorundadır:
  - `--- ts_utc / branch / sha ---`
  - `BEGIN_CODEX_RESPONSE`
  - (yanıtın aynısı, satır satır)
  - `END_CODEX_RESPONSE`
- İstersen ayrıca *ikinci bir bölüm* olarak “Keşif Özeti / Tasarım / Uygulama Adımları” yapısal özet eklenebilir; ancak bu **RAW yerine geçmez**.

**Gizlilik**
- Bu dosya gitignored olsa bile **token/secret/credential** içeren metinler yazdırılmaz.
