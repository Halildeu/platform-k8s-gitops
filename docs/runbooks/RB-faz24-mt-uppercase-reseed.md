# RB-faz24-mt-uppercase-reseed — Meeting/Transcript module gate UPPERCASE staged re-seed

> ADR-0041 §5 Amendment (Option A, Codex `019ed603`). Bağlı PR: platform-backend **#688** (catalog + services uppercase), gitops **#1657** (test-seed/invariant/ADR). Board: gitops **#1657**.

## Amaç

meeting/transcript module gate'inin OpenFGA object id'sini `module:meeting`/`module:transcript` (lowercase) → `module:MEETING`/`module:TRANSCRIPT` (UPPERCASE) olarak, **mevcut geçen 7/7 enforce smoke'unu transient 403'e düşürmeden** taşımak; ardından prod-promotion gate'inin permission-service **writer-path** kanıtını üretmek.

## Neden delete-first DEĞİL (Codex zorunlu sıra)

`#688` merge'i tek başına k3d-test'i bozmaz (deploy gitops digest-pin ile manuel). Kırılma noktası = **uppercase servis imajlarını lowercase-only OpenFGA store'a deploy etmek** → servis `module:MEETING` check eder, store'da yok → fail-closed 403. Bu yüzden uppercase tuple'lar **önce additive** eklenir, lowercase **en son** silinir.

## Ön-koşullar

- platform-backend `#688` MERGED + meeting/transcript/permission-service image'ları GHCR'da hazır (immutable `sha-<short>` digest).
- `ssh halil@staging-sw` + `kubectl --context k3d-test -n platform-test` erişimi.
- Host'ta `jq`. OpenFGA pod'da curl YOK → meeting-service pod üzerinden (`POD_DEPLOY=deploy/meeting-service`).

## Pre-flight (KRİTİK — Codex residual)

`meeting:<uuid>` / `transcript:<uuid>` **per-object ReBAC** (owner/participant/viewer) bu re-seed'in KAPSAMINDA DEĞİL (yalnız `module:*` gate). Ama meeting/transcript CREATE path'i `OBJECT_TYPE` tipiyle owner tuple yazar. Canonical `backend/openfga/model.fga` şu an `type meeting`/`type transcript` **içermiyor** — live store'da var mı doğrula:

```bash
# live model'de meeting/transcript type tanımı var mı?
SID=$(kubectl --context k3d-test -n platform-test exec deploy/meeting-service -- env | grep '^ERP_OPENFGA_STORE_ID=' | cut -d= -f2 | tr -d '\r')
MID=$(kubectl --context k3d-test -n platform-test exec deploy/meeting-service -- env | grep '^ERP_OPENFGA_MODEL_ID=' | cut -d= -f2 | tr -d '\r')
kubectl --context k3d-test -n platform-test exec deploy/meeting-service -- \
  curl -s "http://openfga:8080/stores/${SID}/authorization-models/${MID}" | jq -r '.authorization_model.type_definitions[].type' | sort
```

- **`module` görünür + `meeting`/`transcript` YOKSA**: module gate (bu RB) güvenle ilerler; ama **CREATE owner-tuple write'ı ayrı bir gap** → board follow-up issue (model.fga `type meeting`/`transcript` ekleme; ReBAC sharing slice). Bu RB onu çözmez, yalnız kaydeder.

## Adımlar (staged)

### 1. Additive uppercase seed (lowercase durur)
```bash
cd <gitops-repo>
KUBE_NS=platform-test ./scripts/faz24/openfga-meeting-transcript-seed.sh
```
- **Beklenen**: invariant guard PASS (`module:{MEETING,TRANSCRIPT} only`); 6 tuple write idempotent OK; 7/7 smoke_checks PASS (uppercase).
- **Fail sinyali**: invariant `exit 1` (JSON lowercase kalmış) / write HTTP≠200/400-already-exists / smoke mismatch.
- Bu adımda lowercase `module:meeting`/`module:transcript` tuple'ları **hâlâ store'da** (eski pod'lar onları check eder, çalışmaya devam).

### 2. Uppercase servis imajlarını deploy (digest-pin)
```bash
# overlays/test meeting/transcript deployment digest'lerini #688 build'ine pin'le
kubectl --context k3d-test -n platform-test set image deploy/meeting-service \
  meeting-service=ghcr.io/halildeu/platform-backend-meeting-service@sha256:<#688-digest>
kubectl --context k3d-test -n platform-test set image deploy/transcript-service \
  transcript-service=ghcr.io/halildeu/platform-backend-transcript-service@sha256:<#688-digest>
kubectl --context k3d-test -n platform-test rollout status deploy/meeting-service --timeout=180s
kubectl --context k3d-test -n platform-test rollout status deploy/transcript-service --timeout=180s
```
- **Beklenen**: pod imageID == GHCR digest; health 200; no-JWT 401.
- D30 immutable: digest-pin (`sha-<short>`), `main-stable` YASAK. Durable overlay bump gitops #1657'de (selfHeal revert guard).

### 3. Module-gate smoke (yeni uppercase pod'lar)
```bash
KUBE_NS=platform-test ./scripts/faz24/openfga-meeting-transcript-seed.sh   # idempotent re-run, 7/7 PASS
```
- Browser/persona harness (foundation handoff): `faz24-smoke@acik.com` token ile `GET api-gateway:8080/api/v1/admin/meetings` → **200**, unauth → **401** (HARD RULE Tarayıcıdan Sonuç Doğrulanmadan).

### 4. Lowercase tuple cleanup + invariant uppercase-only
```bash
# eski lowercase tuple'ları DELETE (per-tuple)
for obj in module:meeting module:transcript; do for u in user:1 user:9102; do for rel in can_view can_manage; do
  kubectl --context k3d-test -n platform-test exec -i deploy/meeting-service -- \
    curl -s -X POST "http://openfga:8080/stores/${SID}/write" -H 'Content-Type: application/json' \
    -d "{\"deletes\":{\"tuple_keys\":[{\"user\":\"$u\",\"relation\":\"$rel\",\"object\":\"$obj\"}]}}"
done; done; done
```
- **Beklenen**: HTTP 200 (veya 400 'tuple not found' = zaten yok, OK).
- Sonra adım 3 smoke tekrar → 7/7 PASS (uppercase-only store).

### 5. Writer-path prod-gate evidence (gate'in ASIL kanıtı)

direct-seed gate'i KAPATMAZ. permission-service writer path kanıtı:
```bash
# bir test rolüne MEETING granule grant (permission-service API) → outbox → OpenFGA module:MEETING tuple
# (test persona, admin@example.com şifresine DOKUNMA — HARD RULE)
# grant sonrası:
#  (a) tuple_sync_outbox row status=DONE
#  (b) OpenFGA check user:<persona> can_view module:MEETING => allowed:true
#  (c) meeting-service GET /api/v1/admin/meetings (persona token) => 200
```
- Üç kanıt birlikte = DD-EA-2 writer path LIVE → ADR-0041 §5 (b+c) acceptance.

## Rollback

Herhangi adımda fail → eski lowercase pod imajına geri set image + (silinmediyse) lowercase tuple'lar zaten store'da → eski enforce restore. Adım 4'e GEÇMEDEN önce her şey reversible (lowercase tuple'lar duruyor).

## Referans

- ADR-0041 Amendment (Option A) · platform-backend #688 · gitops #1657 · Codex `019ed603`
- `bootstrap/openfga/meeting-transcript-tuples.json` (uppercase) · `scripts/faz24/openfga-meeting-transcript-seed.sh`
- Foundation handoff persona harness: `faz24-smoke@acik.com` (MEETING/TRANSCRIPT_ADMIN realm rolleri + OpenFGA tuple)
