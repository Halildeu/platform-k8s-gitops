# Faz 24 Meeting Owner Stable-Subject Backfill

> **Issue:** [#2360](https://github.com/Halildeu/platform-k8s-gitops/issues/2360)  
> **Hedef:** Yalnız `k3d-test / platform-test`; production bu runbook'un kapsamı dışındadır.  
> **Durum:** Source ve canlı kabul kanıtı oluşmadan tamamlanmış sayılmaz.

## 1. Neden

Recorder consent akışı, `meeting:<uuid>#can_record` kontrolünü yapar. Tarihsel
Meeting owner tuple'ları mutable sayısal `userId` ile yazıldığı için aynı OIDC
kullanıcısının `userId` değeri değiştiğinde `AUDIO_GATEWAY_MEETING_FORBIDDEN`
oluşabilir. Kalıcı nesne kimliği Keycloak/OIDC `sub` olmalıdır.

Canlı keşifte Meeting DB'deki her UUID biçimli `created_by_subject` değerinin
mevcut realm kullanıcısı olmadığı görülmüştür. Bu nedenle UUID biçimi tek başına
kabul edilmez. Yalnız `keycloak.user_entity.id` ile `platform-test` realm'inde
exact eşleşen subject'ler eligible olur; diğerleri karantinada kalır.

## 2. Güvenlik Sınırları

- Script yalnız `k3d-test`, `platform-test`, `platform-pg-test` hedeflerini kabul eder.
- `TENANT_ID` zorunludur; tüm Meeting satırları tenant filtresiyle okunur.
- Varsayılan `MODE=plan` read-only'dir.
- `apply` ve `rollback`, aktif #2360 board claim'i ve
  `CONFIRM_TEST_MUTATION=YES` olmadan çalışmaz.
- Unmatched subject varken tenant-geneli apply, ayrıca
  `ACK_UNMATCHED_SUBJECTS=YES` olmadan fail-closed olur.
- Legacy tuple'lar silinmez; rollback penceresinde korunur.
- Raw user/meeting kimlikleri stdout'a yazılmaz. Geçici ve rollback dosyaları
  `0600` modundadır; rollback manifesti repo dışında tutulur.
- Apply, mevcut bir rollback manifestini asla ezmez. Partial failure olursa o ana
  kadar yazılan tuple'ların manifesti korunur ve aynı dosyayla rollback yapılır.
- Rollback, apply çıktısındaki manifest SHA-256 değeri verilmeden başlamaz;
  dosyayı mode-0600 snapshot'a kopyalar, digest ve duplicate satır kontrolünden
  sonra işler. Manifestteki OpenFGA store/model kimlikleri de mevcut runtime ile
  exact eşleşmeden delete başlamaz.
- Production tuple mutation için ayrı issue, ayrı runbook ve açık yetki gerekir.

## 3. Sıra

1. Backend PR #825 CI ve review kapılarından geçer.
2. Keycloak tenant claim uzlaşması #2359 altında hazırlanır.
3. Yeni backend image immutable digest ile test overlay'e alınır; migration
   sırasında legacy fallback ve dual-write açıkça GitOps üzerinden etkinleşir.
4. Önce ekran görüntüsündeki tek Meeting için `plan -> apply -> verify` çalışır.
5. Desktop recorder allow ve sentetik deny doğrulanır.
6. Tenant-geneli plan incelenir. Exact realm eşleşmeyen kayıtlar yazılmaz.
7. Eligible set için apply/verify çalışır; rollback manifest digest'i kanıta eklenir.
8. Backfill ve browser smoke kanıtından sonra legacy fallback kapatılır;
   dual-write rollback penceresi boyunca ayrıca değerlendirilir.

## 4. Plan

```bash
TENANT_ID='<canonical-tenant-uuid>' \
TARGET_MEETING_ID='<meeting-uuid>' \
MODE=plan \
  scripts/faz24/backfill-meeting-owner-stable-sub.sh
```

Beklenen JSON alanları:

- `meetingRows=1`
- `eligibleExactRealmSubjects=1`
- `quarantinedUnmatchedSubjects=0`
- `candidateDigest=<sha256>`

Kimliklerin kendisi rapora yazılmaz.

## 5. Hedefli Apply ve Verify

```bash
export BOARD_SESSION_ID='codex-faz24-gitops-2360-owner-backfill'
export TENANT_ID='<canonical-tenant-uuid>'
export TARGET_MEETING_ID='<meeting-uuid>'
export ROLLBACK_FILE="$HOME/.local/state/platform/faz24-owner-backfill-target.tsv"

MODE=apply CONFIRM_TEST_MUTATION=YES \
  scripts/faz24/backfill-meeting-owner-stable-sub.sh

MODE=verify \
  scripts/faz24/backfill-meeting-owner-stable-sub.sh
```

Apply önce exact tuple varlığını okur, sonra yalnız eksik tuple'ı yazar. Eşzamanlı
bir yazma yarışında HTTP `400/409 already exists`, tekrar exact read ile
doğrulanırsa idempotent kabul edilir; diğer cevaplar redacted hata ile fail eder.
Verify exact `owner` tuple varlığını ve nil UUID persona için
`can_record=false` sonucunu kontrol eder.

## 6. Tenant-Geneli Backfill

Önce read-only plan:

```bash
TENANT_ID='<canonical-tenant-uuid>' MODE=plan \
  scripts/faz24/backfill-meeting-owner-stable-sub.sh
```

Unmatched kayıtlar varsa bunlar yazılmaz. Sayısal kanıt incelendikten sonra
eligible alt-küme için açık karantina kabulü gerekir:

```bash
export BOARD_SESSION_ID='codex-faz24-gitops-2360-owner-backfill'
export TENANT_ID='<canonical-tenant-uuid>'
export ROLLBACK_FILE="$HOME/.local/state/platform/faz24-owner-backfill-tenant.tsv"

MODE=apply CONFIRM_TEST_MUTATION=YES ACK_UNMATCHED_SUBJECTS=YES \
  scripts/faz24/backfill-meeting-owner-stable-sub.sh
```

Bu kabul unmatched subject'lere yetki vermez; yalnız exact realm eşleşen setin
yazılmasına izin verir. Unmatched kayıtlar ayrı identity-history çalışmasıdır.

## 7. Rollback

Yalnız aynı apply çalışmasında `newlyWritten` olarak kaydedilen tuple'lar silinir:

```bash
export BOARD_SESSION_ID='codex-faz24-gitops-2360-owner-backfill'
export TENANT_ID='<canonical-tenant-uuid>'
export ROLLBACK_FILE="$HOME/.local/state/platform/faz24-owner-backfill-target.tsv"
export ROLLBACK_SHA256='<apply çıktısındaki sha256>'

MODE=rollback CONFIRM_TEST_MUTATION=YES \
  scripts/faz24/backfill-meeting-owner-stable-sub.sh
```

Önceden var olan stable veya legacy tuple'lar rollback manifestine yazılmadığı
için bu komut onları silmez.

Rollback güncel Meeting DB satırına veya kullanıcının realm'de hâlâ bulunmasına
bağlı değildir; apply manifesti otoritedir. Manifestteki meeting, subject ve tenant
alanlarının UUID biçimi, kolon sayısı, duplicate içermemesi, tenant eşleşmesi ve
apply SHA-256 değeri fail-closed doğrulanır. Silme sonrası exact tuple'ın artık
bulunmadığı tekrar okunur. Yalnız açık "tuple not found" yanıtı idempotent kabul
edilir; diğer HTTP `400/409` cevapları hata sayılır.

Manifest ayrıca apply anındaki OpenFGA store/model kimliklerini taşır. Rollback
anındaki meeting-service runtime farklı store veya model gösteriyorsa script
fail-closed durur; başka store'a tahmini delete göndermez.

## 8. Kabul Kanıtı

Issue #2360 yorumunda en az şunlar bulunur:

- backend source commit, image digest ve test overlay imageID eşleşmesi;
- plan/apply/verify JSON çıktılarındaki sayılar ve candidate digest;
- rollback manifest SHA-256 ve entry sayısı, path'in kendisi hassas ise redacted;
- original target Meeting için recorder `ALLOW` ve sentetik persona için `DENY`;
- yeni oluşturulan Meeting için stable owner tuple ve recorder `ALLOW`;
- browser/Electron smoke sonucu;
- unmatched kayıtların sayısı ve neden üzerinde kapanış iddiası olmadığı.

## 9. Ne Kanıtlamaz

- Source testleri canlı rollout'u kanıtlamaz.
- Stable owner tuple varlığı mikrofon/STT kalitesini kanıtlamaz.
- Test backfill production yetkisi veya production readiness kanıtı değildir.
- Unmatched tarihsel subject'ler çözülmeden tüm geçmiş Meeting'lerin erişilebilir
  olduğu söylenemez.
