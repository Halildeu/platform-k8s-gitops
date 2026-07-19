# Faz 35 — Etik Speak ürün charter'ı

> **Owner:** ES-000 / [#2646](https://github.com/Halildeu/platform-k8s-gitops/issues/2646)
>
> **Status:** Accepted product baseline; source-ready değildir, runtime kabulü değildir
>
> **Date:** 2026-07-18
> **Customer-first slice:** public bildirim → kalıcı kayıt → erişim bilgisi → yetkili çalışan yanıtı → bildirim sahibinin mailbox takibi

## 1. Ürün vaadi ve sınırı

Etik Speak, çalışanların ve üçüncü tarafların hesap açmadan güvenli bildirim
yapabildiği; yetkili etik/uyum ekibinin bildirimi çıkar çatışması kuralları altında
yönetebildiği; bildirim sahibinin kimliğini açıklamadan iki yönlü iletişimi
sürdürebildiği ayrı satılabilir bir üründür.

İlk sürüm iki public marka girişini tek hizmet olarak sunar:

- `etik.acik.com`: canonical public adres;
- `speakup.acik.com`: aynı byte-identical public artifact'ı kullanan tam işlevli
  alias;
- `testai.acik.com/ethic`: test ortamındaki kimliği doğrulanmış yönetici MFE'si;
- `ai.acik.com/ethic`: yalnız test acceptance ve production gate'leri
  tamamlandıktan sonra production yönetici MFE'si.

Public reporter uygulaması suite shell, Keycloak oturumu ve suite çerezlerinden
bağımsızdır. Yönetici MFE'si mevcut suite shell, SSO, ortak tasarım sistemi ve
product-scoped authorization sözleşmelerine entegredir. İki yüzey ayrı artifact,
ayrı API route ve ayrı hata alanıdır.

## 2. Hedef kullanıcılar ve ilk tamamlanan işler

| Persona | Bu fazda tamamlayabildiği gerçek iş | Doğrulanabilir sonuç |
|---|---|---|
| Anonymous reporter | Kimlik vermeden bildirim gönderir | Kalıcı commit sonrası bir receipt ve yalnız kullanıcıda kalan erişim sırrı |
| Confidential reporter | İletişim bilgisi paylaşır fakat görünürlüğünü sınırlar | Identity compartment erişimi policy ile kısıtlanmış case |
| Named reporter | Kimliğini beyan ederek bildirim gönderir | Kimlik verisi narrative/evidence'dan ayrılmış case |
| Ethics triager | Yetkili olduğu kurumdaki case'i listeler, inceler ve atar | Audit outbox'a yazılan durum/atama değişikliği |
| Case handler | Reporter'a mesaj yollar ve iç not ekler | Mailbox'ta görülen kalıcı mesaj ve ayrı internal note |
| Reporter | Erişim sırrıyla mailbox'a girer, yanıtı okur ve cevaplar | Aynı case'e bağlı, idempotent ve kalıcı message |
| Auditor | PII içermeyen custody/audit zincirini doğrular | WORM hedefe idempotent teslim edilmiş event |

İlk müşteri teslimatı, sentetik reporter'ın public hostların her birinden bildirim
göndermesi, yetkili test kullanıcısının `testai.acik.com` üzerinden yanıtlaması ve
reporter'ın public mailbox'tan yanıtı görmesiyle kanıtlanır. Mock ekran, source
merge, CI green veya pod `Ready` tek başına teslimat değildir.

## 3. Pazar giriş sınıflandırması

### 3.1 CORE-MUST — satılabilir baseline

| Kontrol / yetenek | Owner issue | Acceptance | Evidence |
|---|---|---|---|
| Anonymous, confidential ve named intake | ES-103 / ES-105 | DB commit olmadan success yok; retry duplicate oluşturmaz | API contract, DB integration test, browser trace |
| High-entropy receipt/access secret | ES-103 / ES-201 | Raw secret serverda saklanmaz; URL/log/analytics'e düşmez | hash assertions, log scan, browser network capture |
| Accountless two-way mailbox | ES-201 / ES-205 | Enumeration/replay/rate-limit negatif testleri ve durable message | API/browser tests, security events |
| SSO + org/product scoped case management | ES-202 / ES-204 | Cross-org, technical admin ve product dışı token fail-closed | authz matrix, browser deny evidence |
| Conflict-of-interest/recusal | ES-203 | Conflicted actor narrative görmeden deny | negative authorization tests, immutable event |
| Attachment quarantine ve sanitized derivative | ES-104 / ES-206 | Staff normal rolde sealed original göremez | malware/metadata/custody tests |
| Tamper-evident audit outbox | ES-207 | Sink outage intake'ı bozmaz; backlog görünür; duplicate yok | retry/DLQ/WORM evidence |
| Redacted asynchronous notification | ES-208 | Provider outage commit'i bozmaz; subject/body case içeriği taşımaz | template scan, DLQ test |
| Retention, hold ve deletion state machine | ES-302/303 | Legal hold fail-closed; irreversible adım named gate'e bağlı | policy tests, redacted evidence |
| WCAG 2.2 AA kritik yol | ES-105/205/307 | Keyboard, screen reader, axe ve browser path geçer | axe/Playwright/manual evidence |
| TR baseline, EN-ready localization | ES-105/307 | User-visible stringler sözlükten; receipt/mailbox TR tam | locale tests, screenshots |
| Product-cell isolation ve rollback | ES-002/101/209 | DB/authz/storage/netpol/resource/rollback ayrı | rendered manifests, D29, rollback drill |

### 3.2 CORE-CONFIG — müşteriye göre parametre

- kategori, kanal ve öncelik sözlükleri;
- triage ekipleri, COI/recusal ve escalation matrisi;
- case durumları ve izin verilen geçişler;
- locale, marka metni, yardım/aydınlatma metni ve erişilebilir tema;
- mevzuata/kurum politikasına göre retention, legal hold ve SLA sayaçları;
- notification provider ve redacted template;
- attachment boyutu/türü, scanner ve storage sınıfı;
- kurum ve ürün bazlı entitlement.

Konfigürasyon hiçbir zaman public API'yi case listeler hale getiremez, suite
tokenını public credential'a çeviremez veya sealed evidence erişimini normal
case rolüne açamaz.

### 3.3 FEATURE — baseline sonrası ayırt edici yetenekler

- multilingual guided intake ve konuya göre akıllı soru akışı;
- redacted AI summary, duplicate/theme clustering ve investigator copilot;
- düzenleyici takvim/SLA intelligence ve risk heatmap;
- bağımsız standalone yönetici shell'i;
- müşteri kontrollü data residency / external ombudsman routing;
- ethics program benchmarking ve anonim trend analytics;
- doğrulanabilir export/data-room paketleri.

Bu özellikler CORE kapalı döngü browser acceptance tamamlanmadan yeni aktif iş
olarak başlatılmaz. AI özelliği raw PII'yi varsayılan olarak dış sağlayıcıya
göndermez ve insan kararının yerine geçmez.

### 3.4 INTEGRATION — mevcut platformla sözleşmeli bağlar

- suite shell: yalnız manager MFE host/remote contract;
- Keycloak/auth-cookie: yalnız staff yüzeyi;
- OpenFGA: ayrı Etik Speak store/model ve product-scoped relation'lar;
- Vault/ESO: ayrı secret path ve service account;
- PostgreSQL: ayrı role/schema/database boundary;
- object storage, WORM audit, notification ve observability: ayrı credentials,
  queue/backlog ve redaction politikası;
- API gateway: public ve staff için çakışmayan route/auth policy;
- GitOps: ayrı workload, NetPol, resource budget, immutable digest ve rollback.

Paylaşılan platform bileşeni arızası public intake'ın durable commit'ini
engellememelidir. Public workload arızası suite'in diğer modüllerinde white-screen
veya auth bootstrap hatası üretmemelidir.

## 4. Sektör standardı ve mevzuat kontrol matrisi

Bu matris hukuki görüş değildir; ürün/engineering acceptance baseline'ıdır.
Ülke ve müşteri bazlı hukuk/DPO onayı ayrıca alınır.

| Referans | Ürüne çevrilen kontrol | Owner | Acceptance / kanıt |
|---|---|---|---|
| ISO 37002:2021 whistleblowing management | trust, impartiality, protection; intake-assessment-address-close döngüsü | Product + Legal | lifecycle/role matrisi, COI tests, case audit |
| EU Directive 2019/1937 | güvenli kanal, gizlilik, follow-up, yetkili erişim | Legal + Product | iki yönlü mailbox, confidentiality compartment, SLA config |
| GDPR Art. 5/25/32 ve KVKK ilkeleri | minimization, purpose limitation, privacy by design, security | DPO + Security | data map, retention/hold, encryption, redaction, DSAR gate |
| ISO/IEC 27001:2022 ve 27002 | access control, logging, incident, supplier/crypto/backup controls | Security + Platform | authz deny tests, audit, restore/rollback evidence |
| ISO/IEC 27701 | controller/processor privacy controls ve records | DPO + Security | processing inventory, role boundary, evidence register |
| SOC 2 security/confidentiality/availability | logical access, change, monitoring, availability evidence | Platform + Audit | CI/GitOps provenance, D29, alert/restore drills |
| OWASP ASVS 4.x / API Security Top 10 | authn/authz, input, rate limit, logging/secret handling | AppSec | SAST/DAST, BOLA/BFLA/enumeration/abuse tests |
| WCAG 2.2 AA / EN 301 549 | accessible public and staff critical paths | Web + QA | axe, keyboard, screen-reader/manual evidence |
| NIST SP 800-63B ilkeleri | secret entropy, throttling, replay resistance | Security | access-secret generation/hash/rate-limit tests |
| OpenTelemetry semantic conventions | redacted operational telemetry | Platform | allowlisted attributes; narrative/identity/secret absence scan |

Normatif kaynaklar:

- <https://www.iso.org/standard/65035.html>
- <https://eur-lex.europa.eu/eli/dir/2019/1937/oj>
- <https://eur-lex.europa.eu/eli/reg/2016/679/oj>
- <https://www.kvkk.gov.tr/Icerik/6649/Kisisel-Verilerin-Korunmasi-Kanunu>
- <https://owasp.org/www-project-application-security-verification-standard/>
- <https://www.w3.org/TR/WCAG22/>
- <https://pages.nist.gov/800-63-4/sp800-63b.html>

## 5. Rakip baseline'ı ve farklılaşma sınırı

Rakip adları ürün kapsamını taklit etmek için değil, alıcının beklediği kategori
baseline'ını kaçırmamak için kullanılır. Satın alma öncesi güncel paket/özellik
doğrulaması satış ekibi tarafından ayrıca yapılır.

| Pazar örneği | Kategori beklentisi | Etik Speak ES-1/ES-2 yanıtı | Sonraki farklılaşma |
|---|---|---|---|
| EQS Integrity Line | anonymous intake, case management, compliance workflow | dual-host intake, accountless mailbox, staff MFE | platform modülleriyle entitlement ve workflow entegrasyonu |
| NAVEX / EthicsPoint | çok kanallı reporting, mature case operations | durable intake, assignment/status, audit | yerel deployment/data residency seçenekleri |
| OneTrust Ethics | privacy/compliance suite integration | isolated product cell + suite MFE | privacy/retention controls ile birleşik governance |
| SpeakUp | trusted anonymous dialogue ve multilingual experience | secure receipt/mailbox, TR baseline | müşteri kontrollü localized guided intake |
| FaceUp | kolay public reporting ve case collaboration | accessible public artifact + manager MFE | standalone veya suite paketleme esnekliği |

Ayırt edici ana tez: Etik Speak bağımsız satılabilir ve ayrı arıza alanında
çalışırken, gerektiğinde mevcut AÇIK platformunun kimlik, yetki, meeting, ETS ve
endpoint ürünleriyle yalnız versioned contracts üzerinden birleşir. Bir ürünün
arızası diğerini devre dışı bırakmaz.

## 6. Veri ve güven sınırları

- `org_id` authoritative, `product_id=etik-speak` explicit'tir.
- Narrative, reporter identity/link, mailbox credential, attachment ve audit
  ayrı compartment'lardır.
- Raw access secret browserda güvenli RNG ile üretilir, başarılı receipt
  ekranında yalnız kullanıcıya gösterilir ve identical retry dışında yeniden
  gönderilmez; server hiçbir response'ta secret döndürmez, yalnız yavaş KDF
  hash'i ve doğrulama metadata'sı saklar.
- Public API write-mostly'dir; case listesi, kimlik okuma, staff note ve sealed
  evidence sunmaz.
- Staff API SSO + product entitlement + OpenFGA kararı olmadan içerik döndürmez.
- Suite bearer/cookie public route'ta credential sayılmaz; public credential
  staff route'ta reddedilir.
- Hiçbir cookie `Domain=.acik.com` kullanmaz. Public hostlar cookie-minimal,
  analytics-free ve üçüncü taraf CDN-free baseline ile çıkar.
- IP, user-agent, referrer veya TLS metadata'sı case/reporter kimliğiyle
  korelasyon anahtarı olarak saklanmaz.
- Secret, PII ve narrative log, trace, metric label, issue veya CI artifact'ına
  yazılmaz.

## 7. Satılabilirlik, paketleme ve SLO baseline'ı

İlk paket `Etik Speak Core`dur: dual public reporter + suite manager MFE +
isolated backend/product cell. Standalone admin, advanced analytics ve AI ayrı
feature/edition'dır. Müşteri ETS, Meeting veya Endpoint ürününü almak zorunda
değildir.

İlk test acceptance hedefleri:

- public intake ve mailbox availability ölçümü staff suite'ten ayrı;
- accepted request için own-DB durable commit ve idempotent receipt;
- RPO/RTO değerleri ES-009 capacity/DR çalışmasında sayısallaştırılana kadar
  satış dokümanında rakam taahhüdü yok;
- public ve staff D29 kanıtı ayrı: `Up`, `Functional`, `Secured`, `Durable`,
  `Recoverable` tek bir green etikete indirgenmez.

## 8. Açıkça kapsam dışı / insan kapıları

- production DNS/ingress switch, gerçek production secret ve certificate owner
  onayı;
- müşteri adına hukuki dayanak, aydınlatma metni veya retention süresi seçmek;
- gerçek PII ile pilotu AI reviewer veya sentetik test adına çalıştırmak;
- telefon hotline/call-center operasyonu;
- AI ile otomatik suçluluk, disiplin veya case closure kararı;
- ES-4 standalone admin ve advanced feature set'i CORE kabulünden önce yapmak.

## 9. Kabul merdiveni

1. **Charter accepted:** bu belge ve ADR/API contract review edilir.
2. **Source-ready:** üç canonical repo CI/contract/security testleri geçer.
3. **Desired-state-ready:** test overlay secret içermeden render edilir.
4. **Deployed:** immutable digest test cluster'da live evidence ile eşleşir.
5. **Functional:** dual public host + `testai` staff closed loop tamamlanır.
6. **Secured:** cookie/API/authz/privacy negatif testleri kabul edilir.
7. **Recoverable:** rollback/restore ve queue backlog davranışı kanıtlanır.
8. **Pilot-ready:** named product/legal/security gate'leri ve sentetik pilot
   acceptance tamamlanır.
9. **Production-ready:** ayrı production change, owner approvals ve atomic
   switch; bu charter tek başına production yetkisi vermez.
