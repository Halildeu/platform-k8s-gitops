# RB — Faz 24 Transcript-Ready Legacy Pre-Enable Gate

> **Issue:** `platform-k8s-gitops#2610`  
> **Ortam:** yalnız `k3d-test` + `platform-test` + `denetim-pc`  
> **Durum (2026-07-20):** `tracked-pending`; ready consumer default-off
> **Mutation sınırı:** §4-§5 read-only'dir. §6 yalnız TEST Vault'ta owner-gated
> dedicated Transit key/policy/token oluşturur. §8 imzalama yapar; Kubernetes,
> backend veya Windows runtime'ını kendi başına değiştirmez.

## 1. Amaç ve Fail-Closed Sonuç

`meeting-ai` ready consumer retained Redis stream'i `0-0` konumundan okuyacağı
için, etkinleştirme öncesinde aşağıdaki eski işlerin hiçbirinin consumer'a
ulaşamayacağı kanıtlanır:

- `meeting.event.v1` olup `analysisRunId` alanı eksik veya `null` kalan
  `meeting.transcript.ready` outbox kayıtları;
- aynı legacy veya malformed event'lerin `meeting:events` içindeki retained
  kopyaları;
- `transcript_finalizations.analysis_run_id IS NULL` satırları;
- önceki yanlış etkinleştirmeden kalmış ready-consumer PEL kayıtları.

Kapı ayrıca gelecekte yeniden null event üretilemeyeceğini exact transcript
imageID allowlist'i + PostgreSQL `NOT NULL` şemasıyla ve consumer'ın evidence
olmadan açılamayacağını exact platform-ai commit/startup-script allowlist'iyle
bağlar. Bu bağlardan biri yoksa sayaçlar sıfır olsa bile sonuç `REJECTED` olur.

Bugünkü repo policy'sinde iki allowlist de bilinçli olarak boştur ve
`currentBoundary.enableAuthorized=false` değerindedir. Mevcut backend fixture'ı
`analysisRunId:null`, mevcut finalization şemasında `analysis_run_id` yok ve
Windows startup permit guard'ı bulunmuyor. Bu nedenle bugünkü doğru sonuç
`tracked-pending`; consumer açılmaz.

## 2. Kanıt Sınırı

Collector aşağıdaki live identity'leri doğrudan okur:

| Yüzey | Read-only kanıt |
|---|---|
| Kubernetes | exact `k3d-test`, tek Ready transcript pod UID + imageID digest |
| PostgreSQL | exact DB endpoint'te iki `REPEATABLE READ READ ONLY` snapshot; Redis scan öncesi/sonrası aynı sayaçlar ve compatible occurrence-binding set digest'i |
| Redis | exact endpoint'te tek atomik `EVAL_RO`; complete stream classification + fixed-shape sayaç/digest + matching occurrence-binding set digest'i + group PEL |
| GPU host | policy-pinned bilgisayar adı, hardened deployment ledger commit, repo HEAD, startup script SHA-256, effective default-off ve loopback `/health` |
| Repo | GitOps commit, policy SHA-256, SQL/Lua/host-probe contract SHA-256 |

Redis payload byte'ları Redis dışına çıkarılmaz; Lua yalnız compatible binding
SHA-1 ara özetlerini collector'a döndürür, collector bunları sıralı bir SHA-256
set digest'ine indirger. PostgreSQL sorgusundaki UUID binding tuple'ları da yalnız
collector belleğinde aynı digest'e çevrilir ve evidence'e yazılmaz. Evidence'e
event key, meeting/session/tenant kimliği, transcript, payload, URL, token,
parola veya Secret değeri girmez.

## 3. Önkoşullar

1. Çalışılan GitOps commit full 40-hex olarak bilinir.
2. `kubectl --context k3d-test` read yetkisi vardır.
3. `psql`, `redis-cli`, `ssh`, `python3` kurulu runner kullanılır.
4. PostgreSQL credential'ı yalnız `PGUSER`, `PGPASSWORD` environment
   değişkenleriyle verilir. Collector `PGHOST=172.19.0.6`, `PGPORT=5432`,
   `PGDATABASE=transcript` ve `PGSSLMODE=disable` hedefini policy'den zorlar;
   `PGSERVICE`/`PGSERVICEFILE` kabul edilmez.
5. Redis erişimi `REDIS_HOST=172.19.0.250`, `REDIS_PORT=6379` ve
   `REDISCLI_AUTH` ile verilir. Host/port policy ile birebir eşleşmezse collection
   başlamaz.
   Credential komut argümanına konmaz ve shell tracing (`set -x`) açılmaz.
6. SSH config'teki canonical `denetim-pc` alias'i pinned host key ve operator
   identity kullanır. Ham credential yoktur.
7. `MAI_READY_CONSUMER_ENABLED` etkin değildir. Collector hiçbir flag yazmaz.
8. Her collector bileşeni `observedAt` üretir; collection start/finish penceresi
   en fazla `300s` olabilir. CLI probe timeout'u `5..60s` dışında reddedilir.

## 4. Read-Only Collection

Evidence dizini repo dışındaki mode-restricted geçici alanda tutulur:

```bash
umask 077
EVIDENCE_DIR="$(mktemp -d /tmp/faz24-ready-pre-enable.XXXXXX)"
GITOPS_COMMIT="$(git rev-parse HEAD)"

python3 scripts/faz24/collect_transcript_ready_pre_enable_evidence.py \
  --policy config/faz24-transcript-ready-pre-enable-policy.v1.json \
  --gitops-commit "${GITOPS_COMMIT}" \
  --output "${EVIDENCE_DIR}/candidate.json"
```

Collector `candidate` üretse bile bu enable izni değildir. `collection-blocked`
durumunda eksik live yüzey düzeltilir; sayaç tahmin edilmez veya elle yazılmaz.

## 5. Fail-Closed Verification

```bash
python3 scripts/faz24/verify_transcript_ready_pre_enable_evidence.py \
  "${EVIDENCE_DIR}/candidate.json" \
  --policy config/faz24-transcript-ready-pre-enable-policy.v1.json \
  --expected-gitops-commit "${GITOPS_COMMIT}" \
  --output "${EVIDENCE_DIR}/verdict.json"
```

Kabul için tüm koşullar birlikte gerekir:

- evidence yaşı policy'deki `900s` sınırını aşmaz;
- collection start/finish süresi `300s` sınırındadır; beş live observation ve
  iki PostgreSQL server-side `capturedAt` değeri aynı pencerenin içindedir;
- iki PostgreSQL snapshot'ı ve Redis scan exact policy endpoint'lerinden gelir;
- live transcript imageID tek exact approved producer capability ile eşleşir;
  capability event-contract, backfill, outbox remediation ve Redis remediation
  evidence SHA-256 özetlerinin tümünü taşır ve current SQL/Lua/host-probe gate
  contract SHA-256 ile birebir eşleşir; her digest repo-relative, en fazla 1 MB
  gerçek artifact byte'larından yeniden hesaplanır;
- `analysis_run_id` kolonu iki snapshot'ta mevcut, PostgreSQL `UUID NOT NULL`'dır;
- her non-null event `analysisRunId` değeri aynı
  tenant/meeting/session/finalization-version occurrence satırındaki
  `analysis_run_id` ile birebir eşleşir; sentinel veya orphan UUID kabul edilmez;
- PostgreSQL compatible outbox ve Redis compatible retained-event binding
  count + set SHA-256 değerleri birebir eşleşir;
- NULL finalization, legacy/malformed outbox ve retained Redis sayaçları sıfırdır;
- PENDING, active/stale CLAIMED, DEAD ve PUBLISHED legacy outbox sınıflarının
  her biri sıfırdır; PUBLISHED satır elle replay edilebileceği için istisna yoktur;
- atomik Redis scan `scanned == length`, truncation false olur; target consumer
  group henüz yoktur (`exists=false`, pending/consumer sıfır);
- PostgreSQL sayaçları Redis scan öncesi ve sonrasında aynıdır;
- GPU host live health consumer'ı `disabled`, worker/group'u kapalı gösterir;
- effective env dosyasında ready flag ya hiç yoktur (`matchCount=0`) ya da tek
  kez exact `false` olarak bulunur (`matchCount=1`); duplicate tanım koşulsuz
  reddedilir;
- exact platform-ai commit + startup script SHA-256, permit zorunlu host guard
  allowlist'iyle eşleşir; host probe byte'ları da query-contract ve ayrı probe
  SHA-256 ile verifier'a bağlıdır ve Windows bilgisayar adı exact
  `DENETIM-PC` policy identity'siyle eşleşir;
- repo policy `enableAuthorized=true` yönünde ayrıca deliberate değişmiştir.

Bu koşullardan biri eksikse verifier `enableAuthorized=false` döndürür.

## 6. Owner-Gated TEST Vault Transit Bootstrap

Bu adım yalnız `platform-test` Vault cluster'ında çalışır. Root token owner-only
bir dosyadan okunur; stdout, shell argümanı, GitHub artifact'ı veya evidence'e
girmez. Bootstrap şu dar mutation'ları yapar:

1. exact TEST Vault cluster ID ve unsealed/active health doğrular;
2. dedicated `meeting-ai` Transit mount'unu ve non-exportable, non-derived
   Ed25519 `transcript-ready-permit` key'ini oluşturur veya güvenlik
   özelliklerini read-back ile doğrular;
3. yalnız `meeting-ai/sign/transcript-ready-permit` ve
   `auth/token/lookup-self` yetkili git-reviewed ACL policy'yi uygular;
4. default policy taşımayan, non-renewable, en fazla `1800s` ve `10` kullanımlı
   signer token mint eder; accessor read-back ile policy/TTL/use sınırını
   doğrular;
5. signer token'ı mode `0600` secret dosyaya, public-key receipt'i ayrı mode
   `0600` dosyaya yazar. Sonraki hata halinde minted token accessor ile revoke
   edilir ve yalnız bu koşuda yaratılan kısmi dosyalar temizlenir.

```bash
umask 077
PERMIT_DIR="$(mktemp -d /tmp/faz24-ready-permit.XXXXXX)"
ROOT_TOKEN_FILE="${PERMIT_DIR}/test-vault-root.token"
SIGNER_TOKEN_FILE="${PERMIT_DIR}/transcript-ready-signer.token"
TRANSIT_RECEIPT="${PERMIT_DIR}/transit-receipt.json"

# ROOT_TOKEN_FILE owner tarafından terminal transcript'i dışında mode 0600
# oluşturulur. Ham token bu runbook çıktısına veya komut argümanına yazılmaz.
python3 scripts/ops/bootstrap_faz24_transcript_ready_permit_transit.py \
  --vault-origin "${TEST_VAULT_ORIGIN}" \
  --root-token-file "${ROOT_TOKEN_FILE}" \
  --expected-cluster-id "${TEST_VAULT_CLUSTER_ID}" \
  --signer-token-out "${SIGNER_TOKEN_FILE}" \
  --receipt-out "${TRANSIT_RECEIPT}"

rm -f -- "${ROOT_TOKEN_FILE}"
```

Bootstrap stdout'u yalnız key ID, public receipt SHA-256, TTL/use sayısı ve
out-of-band pin gereksinimini taşır. `SIGNER_TOKEN_FILE` Git'e, GitHub'a,
Windows host'a veya Kubernetes Secret'a kopyalanmaz; yalnız §8 imza koşusunda
Vault'a gönderilen `X-Vault-Token` header'ı için kullanılır.

## 7. Public Trust-Root ve Out-of-Band Pin

Public receipt'in SHA-256 değeri, receipt dosyasını taşıyan kanaldan bağımsız
owner/operator kanalında doğrulanır. Builder yalnız TEST environment allowlist'i,
dedicated key/version, canonical HTTPS Vault origin, Ed25519 public key ve
non-exportable/non-derived safety özellikleriyle trust root üretir.

```bash
RECEIPT_SHA256="$(python3 - "${TRANSIT_RECEIPT}" <<'PY'
import hashlib
import pathlib
import sys
print(hashlib.sha256(pathlib.Path(sys.argv[1]).read_bytes()).hexdigest())
PY
)"
TRUST_ROOT="${PERMIT_DIR}/transcript-ready-trust-root.json"

python3 scripts/faz24/build_transcript_ready_permit_trust_root.py \
  --receipt "${TRANSIT_RECEIPT}" \
  --expected-receipt-sha256 "${RECEIPT_SHA256}" \
  --allowed-app-environment test \
  --not-before "${TRUST_NOT_BEFORE_UTC}" \
  --not-after "${TRUST_NOT_AFTER_UTC}" \
  --output "${TRUST_ROOT}"

TRUST_ROOT_SHA256="$(python3 - "${TRUST_ROOT}" <<'PY'
import hashlib
import pathlib
import sys
print(hashlib.sha256(pathlib.Path(sys.argv[1]).read_bytes()).hexdigest())
PY
)"
```

Builder stdout'undaki `trust_root_sha256` değeri de Windows host'a trust-root
dosyasından ayrı kanalda pinlenir. Public trust root secret değildir; yine de
başka key/environment ile sessizce değiştirilmemesi için digest binding'i
zorunludur.

## 8. Accepted v2 Verdict'i DSSE Permit Olarak İmzalama

Verifier'ın `accepted-candidate` üretmesi yeterli değildir. Signer; verdict'in
kapalı alanlı `faz24.transcriptReadyPreEnableVerdict.v2` şemasını, `appEnv=test`,
GitOps commit, policy SHA-256, exact producer image digest, live pod UID/image/
evidence digest'i, platform-ai startup guard ve en fazla `900s` freshness'i
yeniden doğrular. Rejected, stale, extra-field veya mismatch verdict Vault'a
gönderilmez.

```bash
POLICY_SHA256="$(python3 - <<'PY'
import hashlib
import pathlib
print(hashlib.sha256(pathlib.Path(
    "config/faz24-transcript-ready-pre-enable-policy.v1.json"
).read_bytes()).hexdigest())
PY
)"
KEY_VERSION="$(python3 - "${TRANSIT_RECEIPT}" <<'PY'
import json
import pathlib
import sys
print(json.loads(pathlib.Path(sys.argv[1]).read_bytes())["keyVersion"])
PY
)"
PERMIT_ENVELOPE="${PERMIT_DIR}/transcript-ready-permit.dsse.json"

python3 scripts/faz24/sign_transcript_ready_pre_enable_permit.py \
  --verdict "${EVIDENCE_DIR}/verdict.json" \
  --trust-root "${TRUST_ROOT}" \
  --expected-trust-root-sha256 "${TRUST_ROOT_SHA256}" \
  --app-env test \
  --expected-gitops-commit "${GITOPS_COMMIT}" \
  --expected-policy-sha256 "${POLICY_SHA256}" \
  --expected-producer-image-digest "${PRODUCER_IMAGE_DIGEST}" \
  --vault-origin "${TEST_VAULT_ORIGIN}" \
  --vault-token-file "${SIGNER_TOKEN_FILE}" \
  --vault-key-version "${KEY_VERSION}" \
  --output "${PERMIT_ENVELOPE}"
```

Signer Vault'tan dönen signature'ı pinned public trust root ile lokal olarak
doğrulamadan zarf yazmaz. Başarılı imzadan sonra kısa ömürlü signer token revoke
edilir veya TTL/use sınırında expire olması izlenir; dosya güvenli biçimde
silinir. DSSE permit ve trust root platform-ai
`deploy/gpu-host/configure-meeting-ai.ps1` komutuna sırasıyla
`-ReadyPermitSourcePath` ve `-ReadyPermitTrustRootSourcePath` olarak verilir.
Platform-ai activation bunları kendi governed runtime alanına atomik taşır,
permit source'unu tüketir ve replay/stale/wrong-key durumunda consumer'ı
fail-closed kapalı tutar.

Bu adımların hiçbiri tek başına runtime acceptance değildir. Geçerli kanıt:
immutable platform-ai commit + Windows CI, test host activation, ready event
consume, canonical meeting result persistence ve attended kullanıcı yolculuğu
ayrı ayrı doğrulanınca oluşur.

## 9. Rejection ve Remediation Evidence

Verifier her başarısız kontrolü aşağıdaki evidence sınıfına bağlar:

| Kod | Gereken ayrı değişiklik/kanıt |
|---|---|
| `BACKFILL` | NULL finalization inventory, deterministic analysis-run backfill, `NOT NULL` constraint ve sonra sıfır live count |
| `PURGE_OR_REPUBLISH` | legacy outbox kayıtlarının bounded digest/count inventory'si; yeni non-null sözleşmeyle idempotent republish veya owner-onaylı purge sonucu |
| `DLQ_ACK_XDEL` | retained legacy/malformed Redis entry set'inin redacted digest'i; durable metadata-only DLQ receipt, varsa XACK, exact XDEL count ve sonra complete zero scan |
| `KEEP_CONSUMER_DISABLED` | compatible producer capability veya permit-enforcing host startup guard eksik; flag kapalı kalır |
| `FRESH_ZERO_SCAN` | remediation sonrası tüm live yüzeyler yeniden aynı collector/verifier ile ölçülür |

Capability artifact'lerinin her biri
`faz24.transcriptReadyRemediationEvidence.v1` şemasını, issue/environment,
exact backend commit, `status=accepted` ve doğru `evidenceType` değerini taşır.
İzinli tipler `EVENT_CONTRACT`, `BACKFILL`, `OUTBOX_REMEDIATION` ve
`REDIS_REMEDIATION`'dır. Path repo dışına çıkamaz; hash-benzeri serbest metin
tek başına kabul edilmez.

Artifact zarfı kapalı alanlıdır ve exact transcript image digest'i, current gate
contract SHA-256'sı, ana `Halildeu/platform-k8s-gitops#2610` gate issue'sundan
farklı claimed evidence issue'su, metadata-only claim receipt digest'i ve
completion timestamp'i taşır. Claim receipt de repo-relative, en fazla 1 MB,
byte-hash'i yeniden hesaplanan `faz24.transcriptReadyEvidenceIssueClaim.v1`
artifact'idir; gate issue, remediation issue, environment, claim zamanı ve
`github-project-v2` kaynağı kapalı alanlarla doğrulanır. Claim zamanı
completion'dan sonra olamaz; completion da fresh zero-scan collection
başlangıcından kesin önce olmalıdır.
Tür-bazlı içerik de kapalı alanlıdır:

| Tip | Zorunlu içerik |
|---|---|
| `EVENT_CONTRACT` | exact v1 event adı + non-null emission + occurrence-bound finalization sözleşmesi |
| `BACKFILL` | bounded NULL inventory count/digest, processed/failed count, zero result digest ve `UUID NOT NULL` occurrence bağı |
| `OUTBOX_REMEDIATION` | beş status + malformed before inventory count/digest, actual `PURGE` veya `REPUBLISH` sonucu, zero after count/digest |
| `REDIS_REMEDIATION` | legacy/malformed inventory digest, durable DLQ receipt digest/count, XACK/XDEL sonucu ve complete zero after scan |

Sıfır başlangıç yalnız canonical empty-set digest'i ve
`NOOP_ZERO_INVENTORY` ile kabul edilir. Pozitif inventory'de action ve processed
count birebir uyuşmazsa, failed count sıfır değilse veya result inventory sıfır
değilse artifact reddedilir.

Bu repo değişikliği backfill, outbox status değişimi, XACK/XDEL, host config yazımı
veya workload mutation yapmaz. Bu operasyonların her biri ayrı claimed issue,
rollback/irreversibility değerlendirmesi ve metadata-only evidence ister. Ham SQL
row veya Redis payload evidence'e kopyalanmaz.

## 10. Sonraki Enable Değişikliğinin Şartı

Bir sonraki source/runtime dalgası şu sırayı korur:

1. Backend non-null `analysisRunId` event sözleşmesini ve
   `transcript_finalizations.analysis_run_id NOT NULL` şemasını getirir.
2. Immutable transcript-service image build edilir ve test overlay digest'i
   GitOps ile rollout edilir; doğrudan workload `kubectl patch/set image/edit`
   kullanılmaz.
3. platform-ai startup script'i, fresh candidate artifact'ı policy digest +
   exact producer/AI/GitOps identity + TTL ile doğrulamadan
   `MAI_READY_CONSUMER_ENABLED=true` prosesini başlatmayı reddeder.
4. Exact producer/host tuple'ları policy allowlist'lerine ayrı review'lu değişiklik
   ile eklenir; `currentBoundary.enableAuthorized=true` deliberate olarak değişir.
5. Bu collector/verifier fresh v2 `accepted-candidate` üretir.
6. §6-§8 dedicated TEST Vault key + pinned public root ile exact verdict'i DSSE
   permit olarak imzalar.
7. Yalnız allowlisted startup guard fresh permit + pinned trust root'u tüketerek
   test consumer'ı başlatabilir. Artifact tek başına production, insan/hukuk
   veya müşteri acceptance kanıtı değildir.

## 11. Rollback

§4-§5 read-only olduğundan rollback gerektirmez. §6 başarısızlığında bootstrap
minted token'ı accessor ile revoke eder; dedicated TEST key silinmez, export
edilmez veya deletion-enabled yapılmaz. Kullanılmayan signer token ayrıca revoke/
expire edilir ve lokal secret dosya kaldırılır. Daha sonraki test enable
dalgasında rollback, Windows host governed config üzerinden consumer flag'ını
tekrar `false` yapmak, active permit'i revoke/consume etmek ve exact önceki
platform-ai commit'e dönmektir. Backend veri migration'ı geri alınmaz; legacy
remediation ve public trust-root audit kanıtı korunur.
