# Session Handoff — 2026-06-12 — Graph Mail Bidirectional (ai@acik.com read+send + backend TEST cutover)

> Format: D28 5-alan + sıradaki agent P0 aksiyon listesi
> Önceki handoff: [docs/session-handoff-2026-06-07-permission-tuple-sync-deploy.md](./session-handoff-2026-06-07-permission-tuple-sync-deploy.md)
> Board issue: [#892](https://github.com/Halildeu/platform-k8s-gitops/issues/892) (Graph mail adapter activation — bu oturum agent-yapılabilir kısmı kapadı)

---

## 1. Bağlam (bu oturumda ne yapıldı)

Kullanıcı `/goal "faz 22 için kalan otonom adımları tamamla"` ile başladı; ana iş **mail çift-yönlü hale getirme** oldu:

- **Soru**: "mail atabiliyoruz ama mail **alabiliyor / okuyabiliyor muyuz** ai@acik.com için?"
- **Yetki**: kullanıcı bu sohbetten **doğrudan gelen mailleri görme** yetkisi verdi
- **Sınır (kritik)**: yetki **yalnızca ai@acik.com** mailbox'ı için — read AND send — "tüm mailleri görme/gönderme gibi geniş yetki olmasın"
- **Korku**: "bu yetki ele geçerse herkes adına mail atılabilir mi?" → **AAP (ApplicationAccessPolicy)** ile blast-radius tek mailbox'a kısıtlandı
- **Backend**: "bildirim GÖNDERME için de Graph kullanalım daha doğru değil mi?" → backend notification-orchestrator mail send path SMTP → Graph cutover (TEST)

Sonuç: ai@acik.com için **okuma (D7) + agent gönderme (D7b) + AAP güvenlik** zinciri **tamamlandı (LIVE)**; **backend Graph cutover TEST (D7c)** ise yalnızca **adapter/infra seviyesinde LIVE** — functional intent→delivery smoke **PENDING** (§4). "Adapter/infra LIVE" ≠ "backend email functional delivery çalıştı".

---

## 2. İddia (MERGED PR'lar — hepsi 2026-06-12 doğrulandı `gh pr view`)

| PR | Başlık | Merge |
|---|---|---|
| [#1456](https://github.com/Halildeu/platform-k8s-gitops/pull/1456) | Graph API agent inbox read scope (Mail.Read app-only, ai@acik.com) — ADR-0024 **D7** addendum | 07:45Z |
| [#1471](https://github.com/Halildeu/platform-k8s-gitops/pull/1471) | graph-mail-list.sh heredoc stdin bug fix + D7 Mail.Read **LIVE** | 12:37Z |
| [#1473](https://github.com/Halildeu/platform-k8s-gitops/pull/1473) | graph-mail-send.sh — agent/ops explicit send helper (**D7b**) | 12:53Z |
| [#1477](https://github.com/Halildeu/platform-k8s-gitops/pull/1477) | backend mail send SMTP → Graph cutover (TEST overlay; ESO + ConfigMap flag) | 14:11Z |
| [#1480](https://github.com/Halildeu/platform-k8s-gitops/pull/1480) | backend Graph cutover TEST adapter-LIVE evidence (smoke pending) | 14:26Z |
| [#1482](https://github.com/Halildeu/platform-k8s-gitops/pull/1482) | ADR-0024 **D7c** — backend GraphMailAdapter TEST cutover (D1-D6 reactivation) | 14:51Z |

**Üç ayrı katman (karıştırma)**:
- **D7** = agent/ops **okuma** yüzeyi (`scripts/ops/graph-mail-list.sh`)
- **D7b** = agent/ops **gönderme** yüzeyi (`scripts/ops/graph-mail-send.sh`, dry-run default + `--confirm-recipients` guard)
- **D7c** = **backend pipeline** mail-send reactivation (GraphMailAdapter flag flip, TEST cluster) — D1-D6'nın TEST'te canlanması. **NB**: D7c **adapter/infra LIVE** (bean init + mutual exclusion + secret/env); **functional intent delivery PENDING** (§4). D7/D7b external-delivery PROVEN, D7c adapter-code-path henüz bir gerçek intent ile koşulmadı.

---

## 3. İspatlar (LIVE doğrulanan)

| Katman | Kanıt |
|---|---|
| **D7 read** | `graph-mail-list.sh` LIVE — ai@acik.com inbox Graph `GET /messages` app-only token ile okundu; SSH staging-sw → Vault cred → token → Graph |
| **D7b send** | **3 gerçek mail** gönderildi + teslim oldu (serban ×2 `halil.kocoglu@serban.com.tr`, hotmail ×1), hepsi HTTP **202**, recipient-confirmed (kullanıcı gelen mailleri yapıştırdı, NDR yok) |
| **AAP güvenlik** | ai@acik.com **ONLY** — mail-enabled security group ile kısıtlandı; **ai.enes@acik.com + serban Denied** doğrulandı (ele-geçirme senaryosunda blast-radius tek mailbox) |
| **Backend cutover (G1-G4)** | G1 ESO `True SecretSynced`; G2 Secret 3 Graph key (CLIENT_ID len=36, CLIENT_SECRET len=40, TENANT_ID len=36); G3 boot-log `GraphMailAdapter initialized: senderMailbox=ai@acik.com` + **SmtpAdapter absent (count=0, mutual exclusion proven)**; G4 pod env `NOTIFY_ADAPTERS_GRAPH_ENABLED=true` |
| **Binary provenance** | `GraphMailAdapter.java` main'de + test'ler → live image (sha-175b3da) Graph-inclusive → digest bump GEREKMEDİ |

Evidence doc: [docs/faz-23-evidence/2026-06-12-notify-graph-send-cutover-test.md](./faz-23-evidence/2026-06-12-notify-graph-send-cutover-test.md)
Runbook: [docs/runbooks/RB-graph-mail-agent-read.md](./runbooks/RB-graph-mail-agent-read.md) (§9 send surface, §9.5 closure)
ADR: [docs/adr/0024-graph-mail-adapter-defer.md](./adr/0024-graph-mail-adapter-defer.md) (D7/D7b/D7c)

---

## 4. İspatlamaz (PENDING — No Fake Work, overclaim YASAK)

- **Backend Graph FUNCTIONAL smoke** (en kritik açık kapı): `POST /api/v1/notify/intents` (email channel) → GraphMailAdapter.send() → DELIVERED + ai@acik.com **Sent Items** + `Authentication-Results` (SPF/DKIM/DMARC) **henüz koşulmadı**.
  - **Neden bu oturumda yapılmadı**: gerçek intent için **Keycloak persona (org_id claim) + aktif EMAIL template + verified subscriber + DB erişim** gerekiyor. Test Vault'ta KC persona yok (`kv/platform/keycloak/persona` boş), psql notification pod'da yok, `psql-srb` Error state. Bu **BL-010/BL-028 territory** (dedicated kurulum).
  - **Mevcut kanıt sınırı**: D7b raw Graph API'yi (POST /sendMail) kanıtladı; ama **adapter'ın spesifik code path'i** (in-cluster token service + payload builder bir gerçek intent ile) ayrı kapı.
  - Tam reçete ADR-0024 D7c + evidence doc §4'te yazılı.
- **Prod Graph cutover**: ayrı owner-gated slot (D30 disiplini) — ayrı **prod** backend secret + DKIM/DMARC re-validate + 72h soak.

---

## 5. Bilinen Boşluk + Sıradaki Agent için P0 Aksiyon Listesi

### ~~P0 — Backend Graph functional smoke~~ ✅ DONE (2026-06-12 15:26-15:28 UTC)
**KOŞULDU + PROVEN** — intent `graph-smoke-1781278009` → 202 → DELIVERED + provider_msg_id `@notification-orchestrator-graph` + ai@acik.com Sent Items + Inbox receipt + Authentication-Results. t318 ALLOW-path reuse (persona+OpenFGA tuple+template, tüm guard'lar açık). Codex `019ebc5b` AGREE. Evidence: `docs/faz-23-evidence/2026-06-12-notify-graph-send-cutover-test.md` §8. Kalan: **external Authentication-Results** (prod/external gate) + prod cutover. Aşağıdaki reçete referans için korunur:

<details><summary>Koşulan reçete (referans)</summary>

Zincir (proven, ~1h):
1. **KC persona + auth preflight** (Codex `019ebc5b` MED): BL-010 pattern (org_id User Attribute mapper) ile test realm'de email-channel persona → JWT mint. **org_id TEK BAŞINA YETMEZ** — endpoint'in istediği **audience + role/scope** + varsa **authz tuple/eligibility** koşulu da preflight'ta doğrulanmalı; yoksa smoke **auth katmanında takılır, adapter path'e hiç ulaşmaz** (false-negative riski).
2. **Aktif EMAIL template** + **verified subscriber** seed (psql erişimi gerek — notification pod'da psql yok; bir postgres-client pod veya port-forward + host psql)
3. **Intent submit**: `POST /api/v1/notify/intents` email channel (persona JWT + template + recipient)
4. **Doğrula**: delivery/audit row `DELIVERED` + provider message id → ai@acik.com **Sent Items** + recipient inbox + `Authentication-Results` header capture.
   - ⚠️ **Sent Items folder-specific** (Codex `019ebc5b` MED): `graph-mail-list.sh` şu an `/users/${MAILBOX}/messages` (tüm mesajlar) kullanıyor, `SentItems` klasörü değil — P0 ya helper'a `--folder sentitems` ekler ya da doğrudan `GET /users/ai@acik.com/mailFolders/SentItems/messages` smoke komutu yazar.
5. **Negative**: AADSTS / Graph 403/429/5xx / duplicate delivery YOK
6. Sonuç → evidence doc §8 LIVE + #892 board close-ready

</details>

### P0 — current-state.md Graph truth-delta (Codex `019ebc5b` drift guard) ✅ DONE
`docs/state/current-state.md` §8 (Session 42, 2026-05-20) stale anlatısı ("client secret yaratılmadı / AAP yapılmadı / Vault graph_* absent / ESO remoteRef commented") TEST için düzeltildi: §8'e **2026-06-12 truth-delta bloğu** eklendi (TEST Graph LIVE + functional smoke PROVEN; prod hâlâ defer). Next agent: §8 başındaki delta'yı oku, eski snapshot'ı historical gör.

### P1 — SMTP credential hygiene + Prod slot
- [#822](https://github.com/Halildeu/platform-k8s-gitops/issues/822) Office365 SMTP credential rotation (post-exposure hygiene) — TEST artık Graph primary; SMTP App Password rotate/retire değerlendir (rollback path olarak SMTP korunuyor, silme değil)
- **Prod Graph cutover** (owner-gated): ayrı prod backend secret üret + DKIM/DMARC re-validate + 72h soak

### P2 — Board temizliği
- [#892](https://github.com/Halildeu/platform-k8s-gitops/issues/892) "Graph mail adapter activation **deferred**" — D7/D7b/D7c **+ functional smoke** done (TEST). **TEST-scope close-ready**; OPEN kalmalı çünkü prod Graph cutover + external Authentication-Results (DKIM/DMARC) gate'leri açık (Codex `019ebc5b`).

### P3 — Faz 22.5 operator gates (mail dışı, unrelated)
- [#1428](https://github.com/Halildeu/platform-k8s-gitops/issues/1428) M1 artifact host prod-enable (owner + D30 gated)
- [#1015](https://github.com/Halildeu/platform-k8s-gitops/issues/1015) / [#1037](https://github.com/Halildeu/platform-k8s-gitops/issues/1037) IT pilot acik.local Windows PC (Gate 0 VPN routing blocker)
- [#1359](https://github.com/Halildeu/platform-k8s-gitops/issues/1359) Endpoint Agent tokenless AutoEnroll DNS/edge mTLS host
- [#102 task] R29 mitigation #3 — monthly synthetic Teams smoke Kubernetes CronJob (pending backlog)

---

## Credential / Altyapı State (next session referansı)

> **HİÇBİR SECRET BU DOC'TA DEĞİL** — sadece pointer'lar.

- **Entra app**: `acik-mail-graph-api` — Mail.Send + Mail.Read **Application** permissions + tenant admin consent (appId/tenantId değerleri ADR-0024 satır 41-42'de, gitleaks-pass identifiers)
- **AAP**: mail-enabled security group → ai@acik.com only restrict (`RestrictAccess`)
- **Backend TEST secret**: dedicated `notify-orchestrator-test-graph-20260612` (12 ay), agent helper secret'ten **AYRI** (bağımsız rotation). CLIENT_SECRET + KeyId **local dosyada** `~/notify-backend-graph-credential.txt` (repo'da değil)
- **Vault test**: `kv/platform/notification-orchestrator.graph_*` (platform-vault-test) seeded; agent helper ayrı path
- **Auth notu**: bu tenant'ta Conditional Access device-code auth'u agresif blokluyor (4× timeout) → foreground browser-popup `Connect-MgGraph`/`Connect-ExchangeOnline` çalışıyor

---

## Yeni Session İçin İlk Komut

```bash
cd /Users/halilkocoglu/Documents/platform-k8s-gitops
cat docs/session-handoff-2026-06-12-graph-mail-bidirectional.md   # bu doc — tam context
scripts/board-sync.sh list                                         # In Progress + claim'li iş
# P0 başlamak için: KC persona + template + subscriber setup chain (BL-010 pattern)
```
