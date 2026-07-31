# RB-kc-sms-otp — SMS OTP MFA şeridi (Keycloak SPI → notify → NetGSM)

> Faz 22 Sec, gitops#3212. TOTP varsayılan ve daha güçlü ikinci faktör olarak
> kalır; SMS **opt-in alternatiftir** ("Try another way"). SIM-swap maruziyeti
> owner kararıyla bilinçli kabul edilmiştir. **Agent kimseye kendiliğinden SMS
> atmaz** — gerçek teslim testi yalnız owner'ın verdiği numarayla yapılır.

## Zincir (tümü ölçülmüş)

```
KC SPI (sms-otp, providers/ JAR)
  → auth-service POST /oauth2/token           (Basic keycloak-sms-otp:secret,
     grant_type=client_credentials, audience=notification-orchestrator,
     permissions=notify:intents:system)       → access_token
  → auth-service POST /oauth2/mfa-delivery-grant (Basic; subject, recipient,
     channel, topic, template, auth_session_id) → tek kullanımlık grant JWT
  → notify POST /api/v1/internal/notify/intents (Bearer + X-Mfa-Delivery-Grant; recipients
     [{type: external, phone: E.164}], template auth.sms-otp, channels [sms])
  → NetGSM (test ESO'da kimlikler ekili; JetSMS PR-5 cutover bekliyor)
```

KC→cluster erişimi: `platform-test-net` üzerinde NodePort şeridi —
`http://k3d-test-server-0:31088` (auth) + `:31089` (notify),
`externalTrafficPolicy: Local` + NetPol ipBlock `172.19.0.7/32`
(`kustomize/overlays/test/activation/keycloak-sms-otp/`).

## Bileşen envanteri

| Parça | Yer |
|---|---|
| SPI kaynak + testler | platform-backend `keycloak-sms-otp-authenticator/` |
| auth-service istemci kaydı | platform-backend `auth-service application-k8s.yml` (`keycloak-sms-otp`, #1031) |
| SMS şablonu | platform-backend notify `V25__seed_auth_sms_otp_template.sql` (`auth.sms-otp`, tr/en) |
| Secret — auth tarafı | Vault `kv/platform/auth-service` `service_client_keycloak_sms_otp_secret` → ESO `auth-service-sms-otp-secret` |
| Secret — KC tarafı | `host-compose/keycloak/test/secrets/sms_otp_client_secret.txt` → docker secret → wrapper env `SMS_OTP_SERVICE_CLIENT_SECRET`. **Dosya sahipliği `1000:1000`, mod `400` olmalı** — aşağıdaki tuzağa bakın. |
| NodePort + NetPol + ESO | `kustomize/overlays/test/activation/keycloak-sms-otp/` |
| Flow | `scripts/keycloak/setup-privileged-mfa.sh` (`privileged-2fa-methods`, capability-gated) |

## ⚠️ Secret dosyası sahipliği — sessiz boş env tuzağı (2026-07-31 ölçümü)

Docker `secrets: file:` mount'u host dosyasının **sahipliğini ve modunu aynen
taşır**. `sms_otp_client_secret.txt` `aiadmin:aiadmin` + `600` ile yazılmıştı;
container'da `1001:1001 -rw-------` göründü ve KC (`keycloak`, uid **1000**)
onu okuyamadı. Entrypoint wrapper'ındaki `export X="$(cat $X_FILE)"` bu durumda
**hata vermez** — `cat` boş döner, env değişkeni **var ama boş** olur.

Belirti zinciri: SPI `secret=blank` görür → `attempted()` → ALTERNATIVE grubunda
kullanılabilir yöntem kalmaz → `AuthenticationFlowException` → giriş sayfasında
yanıltıcı **"Invalid username or password"**. Parola doğrudur.

Doğru durum ve doğrulama (kardeş secret'larla aynı):

```bash
sudo chown 1000:1000 host-compose/keycloak/test/secrets/sms_otp_client_secret.txt
sudo chmod 400       host-compose/keycloak/test/secrets/sms_otp_client_secret.txt
# recreate şart (restart secret sahipliğini yenilemez):
docker compose --profile manual up -d --force-recreate keycloak
# kanıt — uzunluk sıfırdan büyük olmalı:
docker exec platform-kc-test sh -lc 'V=$(tr "\0" "\n" < /proc/1/environ \
  | grep "^SMS_OTP_SERVICE_CLIENT_SECRET=" | cut -d= -f2-); echo bytes=${#V}'
```

`grep -c "^SMS_OTP_SERVICE_CLIENT_SECRET="` **yeterli kanıt değildir**: boş
değerde de 1 döner. Uzunluğu ölçün.

## Deploy (test) — sıra önemli

1. **JAR üret** (platform-backend main'inden). **Bu adım cluster digest
   bump'ıyla BİRLİKTE yapılmalı**: SPI bir host dosyasıdır, ArgoCD'nin
   görmediği tek parçadır ve digest'ler yenilenirken sessizce eski kalır.
   2026-07-31'de tam bu oldu — auth-service + notify grant'i konuşuyordu ama
   KC hâlâ grant istemeyen eski JAR'ı çalıştırdığı için teslimat yine
   `BLOCKED_BY_AUTHZ` döndü ve hiçbir hata satırı bunu söylemedi.

   Hostta java yok; Maven container'la derlenir:
   ```bash
   docker run --rm -v /srv/platform/build/platform-backend:/w \
     -v /srv/platform/build/.m2:/root/.m2 -w /w maven:3.9-eclipse-temurin-21 \
     mvn -q -B -f keycloak-sms-otp-authenticator/pom.xml package -DskipTests
   ```
   → `target/keycloak-sms-otp-authenticator-1.0.0.jar`.
   Kurduktan sonra **sha256'yı karşılaştır** (dosya adı sürüm taşımaz, yani
   aynı isim yeni içerik demek olabilir de olmayabilir de).
2. **Host'a koy**: `/srv/platform/stateful/test/keycloak-providers/` (dizin yoksa oluştur; compose ro-mount eder).
3. **Overlay slice apply** (selective):
   `kubectl --context k3d-test -n platform-test apply -k kustomize/overlays/test/activation/keycloak-sms-otp/`
   Beklenen: ExternalSecret `SecretSynced/Ready=True`, 2 svc, 2 netpol.
4. **auth-service env**: overlay auth-service patch'i `SERVICE_CLIENT_KEYCLOAK_SMS_OTP_SECRET`i bağlar (auth-service rollout'unda etkinleşir; #1031 image'ı gerekir).
5. **KC restart** (providers pickup — `start` her açılışta yeniden augment eder, ~10s):
   `cd /srv/platform/gitops/platform-k8s-gitops/host-compose/keycloak/test && docker compose --profile manual up -d --force-recreate keycloak`
6. **Provider doğrula**:
   `curl -s -H "$AUTH" http://127.0.0.1:8082/admin/realms/platform-test/authentication/authenticator-providers | jq '.[]|select(.id=="sms-otp")'`
7. **Flow**: `REALM=platform-test bash scripts/keycloak/setup-privileged-mfa.sh --apply` → `--check` CONVERGED. (Aktivasyon zaten owner-gated `--activate`; flow bound ise 4b restrüktürü canlıya anında yansır.)

## MFA teslim yetkisi (grant) — neden ve nasıl

notify'ın Layer-2 OpenFGA katmanı her dış alıcı için `can_receive` ilişkisi
arar; tek seferlik bir MFA telefonu için böyle bir ilişki yoktur ve **olmamalıdır**
(telefon başına tuple ne ölçeklenir ne de numara değişimine dayanır). Ölçülen
sonuç: `status=BLOCKED_BY_AUTHZ policy=authz_deny`.

Kalıcı çözüm (Codex 019fb825 tasarımı): auth-service, SMS niyetiyle birlikte
**tek kullanımlık, kısa ömürlü, imzalı bir teslim yetkisi** verir. notify bunu
**submit anında** — yani güven sınırında — doğrular ve yalnız **türetilmiş
kanıtı** kaydeder (`delivery_class`, `grant_jti`, `grant_subject`,
`grant_recipient_hash`, `grant_deliver_before`; V26). Asenkron dispatch
worker'ı JWT'yi hiç görmez; yalnız bu sunucu-yazımlı alanlar teslimatla
**birebir** eşleşiyor ve pencere açıksa **sadece alıcı-tuple kontrolünü**
atlar. Şablon çözümü, dış-alıcı politikası, tercih, oran sınırı, idempotency
ve denetim aynen işler.

Neden istemci-yazılabilir `metadata` değil: yetki kararı submit'te verilir ama
çok sonra worker'da uygulanır; kararı submit edenin de yazabildiği bir alanda
tutmak, şablonu yanlış etiketlemeyi bypass'a çevirirdi.

Kontroller (hepsi test-pinli): imza + `exp`, `iss=auth-service`,
`purpose=mfa_otp`, `jti` (tekrar koruması — DB'de unique), ve intent ile exact
eşleşme (topic, template, kanal, alıcı). Herhangi biri tutmazsa yetki **yok
sayılır** ve teslimat normal yoldan yetki kontrolüne girer.

Yapılandırma yoksa (JWK-set URI boş) doğrulayıcı **kapalıdır** ve her şey
normal yoldan gider — eksik yapılandırma hiçbir şeyi gevşetmez.

## Canlı kabul kaydı (2026-07-31, test)

`notify.notification_delivery` üç satırda önce/sonrayı gösteriyor:

| saat | durum | sebep |
|---|---|---|
| 12:26 | `BLOCKED_BY_AUTHZ` | `authz_deny: no_tuple` |
| 14:03 | `BLOCKED_BY_AUTHZ` | `authz_deny: no_tuple` — imajlar yeni, **JAR eski** |
| 14:07 | sağlayıcıya ulaştı | `dlr jetsms code=3` |

14:03 satırı kuralın kendisini kanıtlıyor: grant istenmediğinde teslimat
olağan yetki yolundan gider ve reddedilir — eksik yapılandırma hiçbir şeyi
gevşetmez. 14:07'de `intent` satırında `delivery_class=AUTHENTICATION_CHALLENGE`
ve dört kanıt kolonu da dolu (`grant_recipient_hash` 64 hane, pencere
`created_at`'in ilerisinde); `uq_notification_intent_grant_jti` tekrar
oynatmayı engelliyor.

`dlr code=3` beklenen: kanarya numarası **Ofcom'un +447700900xxx kurmaca
aralığında** — hiçbir aboneye tahsis edilmez. Platform tarafı kanıtlanmıştır;
ahize tarafı bilinçli olarak denenmemiştir (owner-gated).

## Doğrulama katmanları (D29 disiplini)

- **Up**: KC healthy + provider listede.
- **Functional**: `requires-mfa` taşıyan test persona ile browser login →
  "Try another way" SMS seçeneği görünür; seçince auth-service log'unda mint
  200, notify log'unda intent 202 + delivery row `provider=netgsm`.
- **Gerçek teslim (owner-gated)**: owner'ın numarası KC `phoneNumber`
  attribute'una yazılır → login → telefona kod gelir → kod girilir → giriş.
  Yanlış kod ×3 → oturum reddi; resend ×2 sınırı.

## Rotasyon (iki taraf birlikte!)

`FORCE_ROTATE=1` ile seed script'i (session scratchpad `seed-sms-otp-secret.sh`
kalıbı) her iki tarafı aynı değerle günceller; ardından:
ESO refresh (annotate force-sync) + auth-service rollout restart + KC restart.
Tek tarafı döndürmek mint'i 401'e düşürür — belirti: SMS seçildiğinde
"kod gönderilemedi" formu, auth-service log'da `invalid_client`.

## Rollback

- **Anında durdurma (stop-gap)**: `--deactivate` → `browserFlow=browser` (her
  zaman güvenli; SMS dahil tüm privileged-MFA zorunluluğu düşer). Gerekirse
  SPI JAR'ını kaldır + KC restart → provider kaybolur.
- **Tam geri çekilme (kalıcı, GitOps-doğru)**: `kubectl delete -k ...` TEK
  BAŞINA YETMEZ — parent overlay (`kustomize/overlays/test/kustomization.yaml`)
  `activation/keycloak-sms-otp` girdisini koşulsuz içerdiğinden ArgoCD
  (app `platform-test`, k3d-prod/argocd ns, selfHeal=true) bir sonraki
  reconciliation'da 5 kaynağı yeniden yaratır. Kalıcı yol:
  1. Overlay'den `- activation/keycloak-sms-otp` satırını (ve auth-service
     env patch'indeki `SERVICE_CLIENT_KEYCLOAK_SMS_OTP_SECRET` bloğunu)
     kaldıran PR'ı merge et;
  2. ArgoCD sync sonrası beş exact kaynağın YOKLUĞUNU fail-closed doğrula
     (isim-grep YETMEZ — NodePort adlarında "sms-otp" geçmez; context'siz
     komut yanlış cluster'ı sorgulayabilir, hata da "boş çıktı" gibi okunur):
     ```
     kubectl --context k3d-test -n platform-test get \
       externalsecret/auth-service-sms-otp-secret \
       service/auth-service-nodeport \
       service/notification-orchestrator-nodeport \
       networkpolicy/allow-keycloak-sms-otp-to-auth-service \
       networkpolicy/allow-keycloak-sms-otp-to-notification-orchestrator \
       --ignore-not-found -o name
     ```
     Komut exit 0 VE çıktı tamamen boş olmalı; herhangi bir satır = o kaynak
     hâlâ canlı (reconcile bekle ya da overlay revert'i doğrula);
  3. Compose'dan providers mount/secret satırlarını revert + JAR sil +
     `docker compose --profile manual up -d --force-recreate keycloak`.
  Acil pencerede stop-gap + kalıcı PR birlikte yürütülür; yalnız delete ile
  bırakmak reconcile'da sessizce geri gelir.

## Bilinen sınırlar

- Prod: SPI/secret/flow **yok** — owner-gated promosyon (D30 sonrası ayrı iş).
- Telefon kaynağı KC `phoneNumber` attribute'u; panelden yönetimi gitops#3211.
- NodePort şeridi yalnız docker-network içi; LAN'a hiçbir port yayınlanmaz.
