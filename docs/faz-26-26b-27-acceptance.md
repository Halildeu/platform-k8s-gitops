# Faz 26 — 26B+27 Public Pilot Acceptance Criteria (D29-adapted)

> **Status**: DRAFT (Codex iter-3'ün işaret ettiği "sıradaki iş"). Owner numeric-eşik onayı bekliyor.
> **Ref**: [`docs/faz-26-governed-process-platform-plan.md`](./faz-26-governed-process-platform-plan.md) §5/§8 · Cross-AI thread Codex `019f180a` (AGREE).
> **Kapsam kilidi**: Bu acceptance YALNIZ 26B+27 birleşik public ilk release'i kanıtlar — genel Work-OS / full BPM / full records ürünü DEĞİL (plan §7 "12-ay sınırı").

---

## 1. Kapsam — 26B+27 ne kanıtlar

**Tek kapalı governance döngüsü, tek kamu iç-kontrol alanında, uçtan uca, izin-farkında, WORM-kanıtlı.** "Her şeyin temeli" değil; satılabilir tek döngü.

## 2. Pilot Kurulumu (who / what data / which domain)

| Eksen | Seçim |
|---|---|
| **Domain** | **Kamu İç Kontrol Uyum/Eylem Planı izleme + kanıt** (Kamu İç Kontrol Standartları: 5 bileşen / 18 standart → genel şartlar → eylemler → sorumlu → tarih → kanıt → olgunluk). Şu an kurumlarda Excel/Word ile yapılıyor. |
| **Veri (import)** | Gerçek/anonim Kamu İç Kontrol Eylem Planı **Excel'i** (≥1 bileşen, ≥6 standart, ≥20 eylem satırı). Opsiyonel: EBYS/M365/Workcube ek kaynak. |
| **Personalar** | `kik-yonetici` (tam) · `kik-sorumlu` (yalnız kendi standardı/eylemi) · `kik-okuyucu` (read-only) · `kik-yetkisiz` (başka birim — **negatif test**) |
| **Çerçeve crosswalk** | Bir kontrol → Kamu İç Kontrol (KOS/KFS) + ISO 27001 + COSO IC + KVKK m.12 (çoklu-çerçeve "wow") |

## 3. "Wow" Senaryosu — uçtan uca test script (9 adım, her biri pass/fail)

| # | Adım | Ölçüm / beklenen |
|---|---|---|
| 1 | `kik-yonetici` SSO giriş | 200 + doğru izin seti (OpenFGA) |
| 2 | Eylem Planı Excel **import** → sistem süreç-kontrol-risk-kanıt-görev graph'ı **AI ile ÖNERİR** | N satır parse + öneri üretildi; ≥ **%85** satır doğru eşleşti (user-validated) |
| 3 | Kullanıcı öneriyi **doğrular/düzeltir** → graph commit | Doğrulama akışı çalışır; her değişiklik audit'e yazılır |
| 4 | Çiçekte bir **kontrol düğümüne tıkla** → bağlı çerçeve(ler)+risk+kanıt+görev | **Crosswalk ≥3 çerçeve** gösterir (Kamu İK + ISO27001 + COSO/KVKK) |
| 5 | İzinli **AI özet**: "bu standardın durumu/eksikleri" | Atıflı özet üretir; **yalnız izinli veriden**; kaynak gösterir |
| 6 | **Gap → action** aç → **owner ata** → due/SLA | action oluşur; `notification-event` üretilir; SLA stub işler |
| 7 | `kik-sorumlu` giriş → **yalnız kendi eylemini** gör → **kanıt ekle** → evidence-sufficiency işaretle | Yetki dışı eylem GÖRÜNMEZ; evidence-attach + sufficiency çalışır |
| 8 | `kik-yonetici` **review** → approve/reject → closure-reason + acceptance-marker | Döngü kapanır; kim hangi kanıtla kabul etti kayıtlı |
| 9 | Kanıt **WORM audit** izine bağlı → immutable ID + hash-chain; **delete denenince REDDEDİLİR**; exportable audit trail | WORM delete **%100 denied**; audit export valid |

## 4. Acceptance Gate — 6 Katman + Ölçülebilir Kriter (D29-adapted)

| Katman | Kriter | Ölçüm / eşik | Kanıt |
|---|---|---|---|
| **1 Up** | Pod Running + TCP + `/health` | tüm servis 200 | `kubectl get` + curl |
| **2 Functional (Closed Loop)** | §3'teki 9 adımın tamamı | 9/9 pass | adım-adım çıktı + screenshot |
| **3 Permission-enforce (LEAK YOK)** | Allow+Deny sentetik; graph traversal/search/RAG/AI-özet hepsi izin-filtreli | `kik-yetkisiz` ve `kik-sorumlu` için **0 sızıntı** (negatif matris §5) | deny logları + AI-özet izin-filtre kanıtı |
| **4 KVKK-safe** | PII tespit/redaksiyon + erişim audit-event + retention-class uygulanır | PII AI-çıktıda/logda izinsiz **sızmaz**; her erişim audit'te | redaction örneği + audit satırı |
| **5 Records-model-correct** | evidence: immutable ID + hash-chain ref + legal-hold flag + retention-class + custody log + exportable audit | model alanları dolu; WORM delete denied; export valid | şema + WORM-deny + export |
| **6 Browser-smoke** | Agent kendi browser tool'uyla uçtan uca (HARD RULE: tarayıcıdan doğrulanmadan iş bitmez) | flower render + tıkla→bağlılar + AI özet + action + evidence; **console temiz** | screenshot + network + console log |

## 5. Negatif / Guardrail Matris (fail-closed olmalı)

| # | Senaryo | Beklenen |
|---|---|---|
| N1 | `kik-yetkisiz` başka birim eylemini açmaya çalışır | DENY (UI + API) |
| N2 | `kik-sorumlu` kendi dışındaki standardı arar | sonuç **boş** (leak yok) |
| N3 | İzinsiz veri RAG/AI özetine sızar mı | **HAYIR** — AI yalnız caller'ın izinli alt-graph'ından |
| N4 | Kanıt (evidence) silme/değiştirme | WORM **reddeder** |
| N5 | PII (TC/IBAN) AI çıktısına/loga düşer mi | **HAYIR** — redaksiyon |
| N6 | Import edilen graph onaysız işleme girer mi | HAYIR — user-validate zorunlu |
| N7 | Deadline geçti | `escalation-event` üretilir |

## 6. Pass/Fail Eşikleri

- **PASS** = 6/6 katman pass **VE** §5 negatif matrisin **7/7** fail-closed **VE** §3 9/9 adım.
- **Import doğruluk eşiği** (adım 2): ≥ %85 user-validated (owner ayarlayabilir).
- **Sızıntı toleransı**: **0** (permission leak / PII leak / WORM bypass = otomatik FAIL).
- Tek katman veya tek negatif test fail → release **gate kapalı**.

## 7. Kanıt Gereksinimleri (release raporu)

1. 9-adım çıktı + screenshot dizisi (browser).
2. Negatif matris 7/7 sonuç tablosu (deny logları).
3. WORM-deny + audit-export örneği.
4. AI-özet izin-filtre kanıtı (caller A vs B farklı özet).
5. Pod state + health + console/network log.

## 8. Açık Parametreler (owner-set)

- Import doğruluk eşiği (%85 default).
- Pilot kurum/birim + gerçek-vs-anonim veri.
- Hangi tek bileşen/standart seti (≥6 standart önerilir).
- Browser tool tier (claude-in-chrome vs computer-use).

## References
- Plan: [`docs/faz-26-governed-process-platform-plan.md`](./faz-26-governed-process-platform-plan.md)
- Board: GitHub Project #7 "Faz 26 — Governed Process & Work Platform" → "Next — 26B+27 Acceptance Criteria" epic
- D29 deseni: `docs/S1-S2-acceptance-smoke-runbook.md` (Up≠Functional≠Secured)
- Cross-AI: Codex `019f180a` iter-3 ("sıradaki iş = 26B+27 acceptance kriterleri")
