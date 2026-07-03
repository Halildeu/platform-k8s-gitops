# Session Handoff — 2026-07-03 — Faz 25 ATS P1 ürün yüzeyi: 43-PR arc + doygunluk kanıtı

> Format: D28 5-alan + sıradaki agent action list.
> Kapsanan repolar: `Halildeu/ats` (PUBLIC, tüm kod), `Halildeu/ats-strategy` (PRIVATE, CI yok — manuel validator), `Halildeu/ats-gitops` (PRIVATE, CI billing-blocked, owner-gated).
> Memory: `~/.claude/projects/-Users-halilkocoglu-Documents-platform-k8s-gitops/memory/project_faz25_ats_gate_safe_hardening.md` (devam-1..devam-38 zinciri — dilim dilim tüm karar/blocker kaydı).
> Codex cross-AI thread: `019f23a6-f460-72e2-bc78-09a9ba146a60` (Codex'in lokal Claude CLI'ı her koşuda "Not logged in" — her verdict'te beyan edildi, simüle edilmedi).

## 1. Bağlam (bu oturumda ne yapıldı, neden handoff)

Aktif /goal: **Faz 25'i ürün-yüzeyi öncelikli, plan/sistem uyumlu, endüstri standartlarına ve rakiplere bakarak, KVKK'ya takılmadan (izinlerin alınacağı varsayımıyla) tam otonom tamamla.** Bu oturum P1 ürün yüzeyini uçtan uca kapattı ve **agent-doable işin doygunluğunu kanıtladı** (yapay dilim üretmek No Fake Work ihlali olurdu). Kullanıcı explicit "hand off" dedi → bu doc.

ATS-0016 hatırlatma: **G0 = RELEASE gate'i, build gate'i değil.** P1 build sentetik/consented-fixture sınırında serbest; gerçek aday verisi / pilot / satış / partner-acceptance G0 NO-GO iken YASAK.

## 2. İddia (MERGED işler)

Bu arc'ta toplam **43 PR** (ats `#42–#87` aralığında + ats-strategy `#1–#2`), hepsi: scratchpad worktree → impl → test → **Codex MCP adversarial review (REVISE→AGREE)** → CI-yeşil REST check-runs gate → normal squash merge (admin YOK) → `ai-post-merge-cleanup.sh`.

Bu pencerede landing olan son 15 dilim (öne çıkanlar):

| Dilim | Repo/PR | İçerik |
|---|---|---|
| slice-24 | ats #85 | OIDC `DEFAULT_SCOPE` = tam P1 seti (11 scope) — dev-IdP scope-masking sınıfı kapatıldı (Codex blocker) |
| slice-25 | ats | STT dikey: `ats.transcription.write` ayrı authority + `POST /interviews/{id}/transcribe` + **ingest-evidence guard** (WORM'da `recording.ingested.payload.object_key == sourceObjectKey` yoksa provider'a gitmeden fail-closed — ghost-key evidence-minting kapandı) + SegmentSanitizer S1/S2 kanıtı |
| slice-26 | ats | OpenAPI drift-guard: snapshot pin (14 path), bilinçli-pin akışı gerçek kullanımla test edildi |
| slice-27 | ats | a11y test katmanı (axe-core, negatif self-test; contrast token-level guard'da) |
| slice-28/29 | ats | Transkript-üret butonu + one-shot kilit + `boundInterviewId` derived-state-reset (stale-context disiplini) |
| slice-30 | ats `985ec92` | KVKK P1 crosswalk: K2 (STT consent-gate), K7 (transcription.write + ingest-evidence), K9 (SegmentSanitizer runtime kanıtı) |
| slice-31 | ats-strategy #1 | G0 evidence register §2c: owner görüşme malzemesi (redacted, "iddia değil kanıt"; açılabilir public-repo path'leri; 41-PR audit-net ifade) |
| slice-32 | ats-strategy #2 `4e54eeb` | Canonical G0 doc'larındaki stale build-gate dili → release/pilot-gate semantiği (ATS-0016 tutarlı) |

**Ürün akışı browser-verified (SQL seed OLMADAN, agent'ın kendi browser tool'u ile):** OIDC login → consent (disclosure-first, pre-selection yok) → upload (consent-gate fail-closed canlı kanıt) → Transkript üret (ayrı yetki + ingest-guard + sanitizer) → segment listesi → citation (evidence gate) → 3 insan-yolu + refresh-resume → export (gerçek şema digest; PROD path fail-closed) → DSAR + iki-adım silme. WORM zinciri: `consent.recorded → recording.ingested → transcript.created`.

## 3. İspatlar

- **Test yeşili:** vitest 29/29 (component+a11y+OIDC), app-boot 41 (CitationReviewApiTest 8/8 dahil ghost-key testi), ai-orchestration 33/33, eval-harness pytest 30/30. Tümü koşularak (No Fake Work), CI run'ları PR'larda.
- **Güvenlik kanıtları:** ghost-key → 4xx + gövdede "recording.ingested" + AI-stub `TRANSCRIBE_CALLS` sayacı değişmedi + transcript/WORM satırı 0. Free-string key 4xx. `recording.write` tek başına transcribe'a 403.
- **Sanitizer kanıtı:** yanıtta `"(stub)"` YOK, `speakerLabel:"S2"` var (parenthetical annotation strip runtime'da doğrulandı).
- **Doygunluk kanıtı (devam-37):** tünel probe canlı DOWN kanıtı (`ssh halil@staging-sw "nc -z -w 3 127.0.0.1 22024"` → fail); her iki repo origin/main kendi son merge'lerimde (ats `985ec92`, ats-strategy `4e54eeb`) — dış sinyal yok; eval-harness zaten komple.
- **Süreç:** 0 admin-merge, 0 CI-kırmızı merge; her PR'da Implementer(Anthropic)/Reviewer(OpenAI Codex) audit trail.

## 4. İspatlamaz (bu oturumun kanıtlamadıkları)

- **Gerçek STT motoru bağlantısı yok** — provider stub; Faz 24 motoru ile wire-contract uyumu keşfedilmedi (tünel DOWN).
- **Prod/pilot çalışırlığı yok** — ats-gitops deploy wiring + gerçek IdP yok (billing-blocked + owner-gated). Kriter-6 (gerçek TR fixture doğruluk ölçümü) ölçülmedi (consented golden fixture yok).
- **G0 kanıt toplama yapılmadı** — LOI/DPO/VERBIS owner aksiyonları (malzemeler hazır, §2c).
- Board-Done ≠ runtime-LIVE ayrımı burada da geçerli.

## 5. Bilinen boşluk + sıradaki agent için aksiyon listesi

**P0 — tünel izleme + ATS-0017 (tek agent-doable iş):**
```bash
ssh halil@staging-sw "nc -z -w 3 127.0.0.1 22024"   # denetim-PC reverse-SSH tüneli
```
- **UP ise:** ATS-0017 gerçek-STT keşif dilimi: Faz 24 motorunun `/v1/transcribe` HTTP yüzeyini **read-only** keşfet; HttpAIProvider sözleşmesiyle (POST `{"audio_ref"}` → `{"language","segments":[{speaker,start_ms,end_ms,text}]}`) uyum matrisi çıkar → sonra adaptör dilimi (worktree+Codex+CI pattern'i ile).
- **DOWN ise:** `git fetch` + origin/main log her iki repoda sinyal kontrolü; sinyal yoksa ~30 dk sonra tekrar. (Eski session'da ~06:54'e planlı bir wakeup kalmış olabilir — zararsız, aynı probe.)

**P1 — owner-gated (agent malzemeleri hazırladı, bekliyor):**
1. ats-gitops deploy wiring + prod IdP → GitHub Actions billing çözülünce deploy zinciri dilimi.
2. Golden TR fixture (consented panel kaydı) → eval-harness tek komutla koşuya hazır; fixture gelince kriter-6 ölçümü dilimi.
3. G0 kanıtları: LOI / DPO görüşü / VERBIS bildirimi → register `docs/G0/g0-evidence-register.md` (ats-strategy; path'te büyük `G0`) fail-closed validator ile.

**Sıradaki agent çalışma pattern'i (değiştirme):** scratchpad worktree → impl → build/test → Codex MCP iter (`codex-reply`, thread yukarıda; AGREE'siz merge yok) → REST check-runs 0-pending/0-nonsuccess gate → squash merge → `bash ~/.claude/scripts/ai-post-merge-cleanup.sh <PR>` → memory devam-N → sıradaki dilim. Dev zinciri: docker `ats-pg-dev` :55432, dev-IdP :9451, ai-stub :9452, app-boot :8080 (SPRING_APPLICATION_JSON), vite :5183 — iş sonunda hepsini durdur.

**Bilinen tuzaklar (tekrarı önle):** TestRestTemplate string URL = URI template (pre-encoded %2F çift-encode olur — raw slash geç); Map.of 10-pair limitinde (SCOPE map tam sınırda); fresh worktree'de packages/ui + mfe için ayrı `npm install`; ats-strategy path case `docs/G0/`; kvkk-crosswalk guard kapalı status sözlüğü ("enforced (repo-test)"); repo-adı literal'leri ATS kod dosyalarında boundary-guard'a takılır.

## Yeni Session İçin İlk Komut

```bash
cd ~/Documents/platform-k8s-gitops
cat docs/session-handoff-2026-07-03-faz25-ats-p1-saturation.md   # tam context
# sonra: yukarıdaki P0 tünel probe ile başla
```
