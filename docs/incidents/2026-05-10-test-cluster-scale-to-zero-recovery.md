# Incident: Test Cluster Scale-to-Zero Recovery + HARD RULE Establishment

**Date**: 2026-05-10 00:30 — 02:00 TRT
**Severity**: P2 (test ortamı; production etkisi yok)
**Trigger**: User Impersonation v1 Spike-2 sırasında cluster Vault AppRole rotation yapıldı, sonra backend services scale up denemesi pre-existing 18d-cluster drift'ini açığa çıkardı. Kullanıcı login post-process kırık.

## TL;DR

- D17 "scale-to-zero default" mimari kararı multi-Claude paralel session geliştirme modelinde unsafe çıktı: bir oturum down çekerse diğer oturumların işi patlar.
- 18 gün boyunca test cluster `user-service`, `variant-service`, `core-data-service`, `schema-service`, `endpoint-admin-service`, OpenFGA hepsi `replicas=0` idi.
- Spike-2 sırasında scale up denenince **Hibernate dialect bug + Vault password drift + ConfigMap issuer mismatch + permission-service kod drift + OpenFGA secret incomplete + admin user missing** zinciri ortaya çıktı.
- 6+ saat recovery sonrası `/api/v1/authz/me` 200 döner hale geldi.
- Yeni HARD RULE: TEST Cluster Scale-to-Zero YASAK (`~/.claude/CLAUDE.md` global).

## Kullanıcı bağlamı

> "ben servicelerin kapatılmasını istemiyorum çünkü buna tek oturum karar verirse çok oturumda geliştirme yapıyorum patlıyor diğerleri"

> "yarın diye birşey yok hepsi şimdi yarın diye öneri vemrek yazak kural olarak ekle. bana iş ertele üzerine öneri verm ebir dhaha kurallara ekle global olsun."

İki yeni HARD RULE eklendi (global):
1. TEST Cluster Scale-to-Zero YASAK
2. "Yarın" / İş Erteleme YASAK

## Recovery zinciri (sırasıyla)

1. **Vault AppRole rotation** — ESO ClusterSecretStore Ready=True
2. **Vault `kv/platform/permission-service` `reports_db_*` keys** eklendi
3. **PG `platform` user password rotated** (44-char base64 → 48-char alphanumeric, Spring env interpolation safe)
4. **Vault `kv/platform/<svc>` `db_password`** 5 servis için yeni alphanumeric password ile güncellendi
5. **`users` table ownership** transfer (postgres → platform), grant verildi
6. **Admin user'lar** (id=1, id=1204) zaten var; 16 active role assignment doğrulandı
7. **KC realm `frontendUrl=https://testai.acik.com`** (Session 41 fix), HTTPS issuer
8. **Backend ConfigMap'ler** issuer drift fix (HTTPS expectation)
9. **OpenFGA STS scaled up + DB URI Secret manuel patch** (eksik `OPENFGA_DATASTORE_URI`)
10. **OpenFGA `openfga` PG user password rotated** (alphanumeric)
11. **ConfigMap `PERMISSION_AUTHZ_USER_TABLE=public.users`** qualified
12. **ESO force reconcile** her secret için
13. **Deployment env-level override kaldırıldı** (ConfigMap HTTPS issuer geçerli olsun)
14. **Pod rollout restart** her servis için

## Kanıt — `/api/v1/authz/me` 200 (post-recovery)

```json
{
  "userId": "1",
  "superAdmin": true,
  "permissions": ["USER_MANAGEMENT","ACCESS","AUDIT","REPORT","WAREHOUSE","PURCHASE","THEME"],
  "allowedModules": ["WAREHOUSE","REPORT","USER_MANAGEMENT","VARIANT","PURCHASE","AUDIT","COMPANY","SCOPE","ACCESS","THEME"],
  "scopes": [
    {"scopeType":"COMPANY","refIds":[31,2,1,23,21,19,17,15,12,39,38,35,7]},
    {"scopeType":"PROJECT","refIds":[2,1,41784,43545,42999,23199,3]},
    {"scopeType":"WAREHOUSE","refIds":[3792,1379,1]},
    {"scopeType":"BRANCH","refIds":[35]}
  ],
  "roles": ["ADMIN","REPORT_VIEWER", ...]
}
```

## Pod state final (PR #470 öncesi)

| Servis | Durum |
|---|---|
| api-gateway | 1/1 Running |
| auth-service | 1/1 Running |
| frontend | 1/1 Running |
| permission-service | 1/1 Running |
| openfga | 1/1 Running |
| user-service | 1/1 Running ✅ |
| variant-service | 1/1 Running ✅ |
| core-data-service | 1/1 Running ✅ |
| schema-service | 0/1 ImagePullBackOff (image hash GHCR'da yok — bağımsız blocker) |
| endpoint-admin-service | 0/1 CrashLoop (Vault'ta `device_secret_encryption_key`, `enrollment_token_pepper` rendered ama uygulama-level config drift) |
| report-service | 0/1 (pre-existing 7+ saat, Hibernate) |

## Out-of-scope known blockers

1. **schema-service** ImagePullBackOff — image hash `kustomize/overlays/test/kustomization.yaml`'da pin'li ama GHCR'da yok. Image rebuild + push gerek (ayrı PR).
2. **endpoint-admin-service** crashloop — Vault keys tam, uygulama-level config farklı. Spring Boot startup config review gerek.
3. **report-service** crashloop 7+ saat — pre-existing Hibernate dialect bug (auth-service ile aynı pattern zaten uygulandı, ek farklı sebep var).

## Lessons learned (operational)

1. **Multi-Claude paralel session** modelinde shared infra kapatma yasaklanmalı (HARD RULE eklendi).
2. **Cost optimization vs collaboration safety** tradeoff'u shared dev/test cluster'lar için **collaboration safety > cost**.
3. **D17 scale-to-zero** ekonomik bir karardı ama 18d sonrasında recovery overhead'i kazanılan RAM'i misliyle aştı.
4. **PG password rotation pattern**: tüm servisler tek `platform` user'ı paylaşıyorsa, Vault'ta tüm `kv/platform/<svc>` aynı password tutmalı; bir servis için rotate edilirse hepsinin senkronize olması şart.
5. **ArgoCD ignoreDifferences `/spec/replicas`** test cluster için ZARAR (HARD RULE backdoor); kaldırıldı.
6. **GitOps declarative state vs runtime imperative recovery**: bu PR sadece declarative; recovery imperative bu doc'da kayıtlı.

## PR-B impl etkisi

PR-B (User Impersonation v1 backend impl):
- **Implementation path**: Testcontainers ile bağımsız (cluster healthy olmasa da) — Codex iter-12 kararı korunur
- **Live acceptance**: cluster artık `/authz/me 200` verdiği için live smoke kapısı yeniden açıldı
- **Full platform acceptance**: schema/endpoint/report minor blocker'ları kapandıktan sonra

## References

- HARD RULE eklenen: `~/.claude/CLAUDE.md` (TEST Scale-to-Zero YASAK + Yarın YASAK)
- Codex thread: `019e0dfb-7230-7f43-80c4-dd03e36a2f70` (iter-11→12→13)
- PR: #470 (gitops scale-to-zero deprecate)
- Spike-2 doc: `platform-backend/docs/spikes/2026-05-impersonation-token-exchange-spike.md`
- ArgoCD: `argocd/applications/platform-test.yaml`, `argocd/applicationsets/platform-overlays.yaml`
