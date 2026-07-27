# Faz 35 Etik Speak — privacy, anonymity ve insider threat model

> **Owner:** ES-003 / #2650
>
> **Kapsam:** anonim reporter modu, TEST-first engineering contract
>
> **Makine kaynağı:**
> [`faz35-privacy-no-collect/v1`](../contracts/faz35-privacy-no-collect.v1.json)
>
> **Hukuki sınır:** Bu belge Legal/DPO kabulü, mevzuat uygulanabilirliği,
> sertifikasyon veya production go-live yetkisi değildir.

## 1. Güvenlik hedefi

Etik Speak'in anonim moddaki hedefi, uygulamanın kontrol ettiği hiçbir
identity veya transport metadata'sını report, receipt ya da mailbox ile kalıcı
olarak ilişkilendirmemesidir. Kimlik alanı yoksa platform operatorü, DBA, case
worker veya backup operatorü sonradan ürün verisinden reporter kimliği
çıkaramamalıdır.

Bu hedef “internet üzerinde görünmezlik” iddiası değildir. Reporter cihazı,
browser eklentisi, ISP, DNS resolver, public CA ve upstream network operatorü
bağlantı metadata'sını görebilir. Serbest metin ve ek dosya da reporter'ın kendi
kimliğini açıklamasına yol açabilir. Bu residual riskler production öncesi named
Security, DPO ve Product kabulü ister.

## 2. Veri minimizasyonu

### Asla toplanmaz

- ad, e-posta, telefon, çalışan kimliği ve suite kullanıcı kimliği;
- advertising/device fingerprint;
- durable client IP, user-agent, referrer veya TLS session metadata;
- anonim report ile ilişkilendirilebilen identity foreign key.

### Asla log/trace edilmez

- raw access secret, mailbox cookie ve Authorization header;
- receipt ID, narrative, attachment adı veya içeriği;
- client IP, `X-Forwarded-For`, `X-Real-IP`, user-agent ve referrer;
- suite cookie veya staff bearer;
- case/receipt ile join edilebilen hassas URI.

### Yalnız volatile kullanılabilir

Client IP, public edge'de abuse/rate-limit için process-memory penceresinde
kullanılabilir. Hash'lenmez, durable store'a veya observability yüzeyine
yazılmaz ve report/receipt ile join edilmez. TLS metadata'sı yalnız bağlantı
kurulumu süresince tutulabilir.

### İzinli operasyon telemetry'si

Servis adı, identifier içermeyen route template, bounded error/status class,
aggregate latency histogram, aggregate request count, coarse time bucket,
deployment digest ve queue depth. High-cardinality reporter/case label'ı yoktur.

## 3. Compartment modeli

Narrative, mailbox verifier, attachment, redacted audit ve volatile abuse state
ayrıdır. Anonymous modda identity compartment **yoktur**. Confidential/named
mode gelecekte açılırsa ayrı key, schema, OpenFGA relations ve human-gated
policy gerektirir; bu çalışma onları aktive etmez.

| Compartment | Anonymous mod | Normal case worker |
|---|---|---|
| Case narrative | allowed | yalnız org/product/recusal allow |
| Reporter identity | forbidden | erişemez |
| Mailbox verifier | verifier-only | erişemez |
| Attachment | quarantine kabulüne kadar fail-closed | sealed original yok |
| Audit | redacted event | content browse yok |
| Transport abuse state | volatile-only | erişemez |

## 4. Trust boundary ve insider modeli

- **Reporter → public edge:** TLS, volatile rate limit, access log disabled,
  no-third-party analytics.
- **Public edge → UI/API:** client identity forwarding headers stripped,
  `no-referrer`, host-only/minimal cookie.
- **Public API → database:** anonymous identity columns absent/null, own-DB
  atomic report+outbox commit.
- **Manager → staff API:** suite SSO + org/product entitlement + OpenFGA +
  recusal.
- **Runtime → observability:** structured allowlist; payload ve client identity
  yok.
- **Database → backup:** encrypted product-cell backup, ayrı key custody,
  named restore ceremony.

Case worker, platform operator, DBA, observability operator, backup operator ve
key custodian kendi görev alanlarında trusted; narrative/identity/authorization
alanında trusted değildir. Teknik admin rolü case yetkisi üretmez.

## 5. Ana tehditler ve kontroller

| Threat | Kontrol | Kanıt |
|---|---|---|
| Edge log correlation | ingress access log off, client headers strip, identifier-free URI/metric | rendered config + live NGINX config + sentinel leak scan |
| App log/trace exfiltration | structured allowlist, secret-safe errors, payload tracing off | bounded log scan + error tests |
| DBA identity linkage | identity/transport columns forbidden, verifier separated | schema contract + negative query |
| Authorized insider overreach | org/product OpenFGA, recusal, technical-admin deny | wrong-org/deny/recusal tests |
| Parent-domain cookie replay | no `Domain=.acik.com`, suite cookie reject | Set-Cookie + credential confusion test |
| Timing correlation | public request log yok, coarse aggregate bucket | telemetry/export field contract |
| Backup/key collusion | separate key custody, encrypted backup, named restore | restore role matrix + manifest |
| Client-side disclosure | secret URL/localStorage'da yok, CSP, no-third-party | browser URL/console/storage scan |

## 6. Negative acceptance

#2658 runtime gate en az şunları fail-closed kanıtlar:

1. public ingress access log kapalı;
2. upstream `X-Forwarded-For`, `X-Real-IP`, `Forwarded`, user-agent ve referrer
   identity kanalı boşaltılmış/allowlist dışı;
3. sentetik IP/UA/referrer sentinel'i bounded edge/app log ve trace yüzeylerinde
   yok;
4. raw secret, receipt ve narrative telemetry'de yok;
5. `Domain=.acik.com` cookie yok; suite cookie public API'de reddediliyor;
6. anonymous DB satırında identity/transport kolonları yok veya null;
7. wrong-org, OpenFGA-denied ve recusal existence-hiding çalışıyor.

Test sentinelleri kişisel veri değildir ve gerçek receipt/access secret
kullanmaz. Kanıt ham log dump'ı yayınlamaz; yalnız bounded scanner sonucu,
zaman penceresi, allowlist ve redacted sayım taşır.

## 7. Production insan kapıları

- DPO residual-risk ve data map kabulü;
- Legal yayınlanacak notice/legal basis kabulü;
- Security public edge/upstream-provider boundary kabulü;
- owner-supplied retention parametreleri; yoksa refuse-to-store;
- real-user pilot iletişimi ve consent;
- production secret owner ve atomic switch onayı.

Bu kapılar eksikken TEST sentetik yolculuğu geliştirilebilir; production legal
go veya gerçek anonimlik garantisi iddia edilemez.
