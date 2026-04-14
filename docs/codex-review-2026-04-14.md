# Codex Mimari İstişaresi — 2026-04-14

İki turlu istişare. Amaç: `platform-k8s-gitops` için 20 FINAL kararı ve
mimariyi ikinci bir LLM'e eleştirtmek, itiraz + uzlaşı üzerinden sağlamlaştırmak.

## Özet

- **Tur 1**: PLAN.md + consult-brief.md verildi, 8 soruya cevap + 3 ek eksik + skorkart + PoC önerisi alındı.
- **Tur 2**: 1 itiraz + 4 netleştirme sorusu Codex'e döndü, UZLAŞI METNİ (D1-D26) üretildi.
- **Sonuç**: D21-D26 yeni kararlar eklenip PLAN.md 2. committe uzlaşıya göre refactor edilecek.

## Skorkart (Tur 1)

| Alan | Puan | Kısa not |
|---|---:|---|
| Mimari | 4/5 | Pragmatik ve uygulanabilir, karar drift'i temizlenmeli |
| Kapasite | 3/5 | RAM iyi, CPU ve non-heap eksik |
| İzolasyon | 4/5 | Güçlü ama HA değil |
| Gözlenebilirlik | 3/5 | Kapsam biraz fazla agresif |
| Operasyon | 3/5 | Restore/upgrade/runbook eksik |
| Güvenlik | 3/5 | Vault auth, admin erişimi, cert operasyonu açık |

## Codex'in Yakaladığı Benim Kaçırdığım 3 Eksik

1. **HPA — metrics-server çelişkisi**: Plan `--disable=metrics-server` diyor ama HPA CPU %70 hedefliyor → HPA çalışmaz. Karar D21: MVP'de HPA yok.
2. **CPU bütçesi yok**: Sadece RAM tablosu vardı. Codex tahmini: steady 1.6-2.2 vCPU, spike 3.4-4.0 vCPU. Karar D22 eklendi.
3. **Stateful storage + node bakım**: PVC/StorageClass/backup/restore/runbook tanımsız. Karar D23 (runbook zorunlu) eklendi.

## Codex'in "YAPMA" Listesi (Uzlaşıldı, D26)

- MetalLB'yi MVP'ye sokma
- GraalVM migration scope'una alma
- Eureka'yı geçici bile olsa K8s'te tutma
- Aynı hosttaki iki cluster'ı DR/HA gibi sunma
- Admin UI'ları aynı hostname altında sertleştirmeden bırakma

## İtiraz + Uzlaşı

| Konu | Codex 1. tur | İtiraz | Uzlaşı |
|---|---|---|---|
| Cert renewal | Manuel Sectigo, otomasyon kovalama | HTTP-01 bir kez test edilmeli (ucuz) | İki aşamalı: manuel + Faz 12'de dry-run |
| JVM flags | `-Xmx` belirleyici | MaxRAMPercentage kaldır? | Evet kaldır, sadece `-Xmx384m` |
| HPA | metrics-server çelişkisi | MVP'de HPA kaldır? | Onay, r=2 sabit |
| CPU | Tahmin yok | Tahmin ver? | 1.6-2.2 / 2.0-2.8 / 3.4-4.0 vCPU |
| PoC | En az bağımlı servis | auth-service? | Onay: `api-gateway + auth-service` |

## Final Karar Seti (D1-D26)

Tam metin: PLAN.md Bölüm 1 (FINAL KARARLAR).

## Eklenen Yeni Kararlar (D21-D26)

- **D21**: MVP'de HPA yok, metrics-server kapalı, prod r=2/test r=1
- **D22**: CPU bütçesi 1.6-2.2 vCPU steady, 3.4-4.0 vCPU spike; request dar/limit cömert
- **D23**: RPO prod 24h / RTO 4h; test RPO 24h / RTO 1 iş günü; off-host backup zorunlu
- **D24**: JVM `-Xmx384m` explicit; MaxRAMPercentage kaldırıldı; ağır servislere override
- **D25**: PoC dilim `api-gateway + auth-service` → `user-service` → filo çoğaltma
- **D26**: YAPMA listesi (MetalLB/GraalVM/geçici Eureka/2-cluster=DR iddiası yok)

## PLAN.md Drift Temizliği

Codex'in işaretlediği 5 satır düzeltildi (Tur 2'de):
- L14: D1 "tek cluster" → "2 k3d cluster"
- L29: D16 "Docker-in-Docker" → "Docker container'larda ayrı k3s"
- L107: TLS "manuel K8s Secret" → "host nginx'te termine"
- L517: Faz 4 "ExternalName + Endpoints" → "Service + Endpoints (D19)"
- L640: Risk "Eureka single-replica" → "Eureka KALDIRILDI, risk pasif"

## PoC Dilimi — Kabul Kriteri

İlk dilim: `api-gateway + auth-service`

- Gateway route `lb://` olmadan K8s service DNS'e dönecek
- `auth-service` Eureka'sız kalkacak (`@EnableEurekaClient` silinmiş)
- Keycloak/DB host köprüsü (Service+Endpoints) çalışacak
- Smoke test: `/auth/actuator/health` 200 + e2e login akışı

Yeşil olmadan tam filo manifest çoğaltmasına **geçilmez**.

## Ham Cevaplar

- Tur 1 full output: bu dosyada aşağıda (kaynak: /tmp/codex-consult-output.md)
- Tur 2 full output: bu dosyada aşağıda (kaynak: /tmp/codex-round2-output.md)

---

## Tur 1 — Codex Ham Cevabı

## Genel Değerlendirme

Planın omurgası sağlıklı; tek host, düşük kaynak ve canlı geçiş baskısı altında gereksiz “enterprise” karmaşıklığa kaçmadan makul kararlar alınmış. Özellikle host dışında bırakılan stateful servisler, test için `scale-to-zero`, prod/test ayrımı ve rollback düşüncesi doğru. İlk izlenimim şu: bu mimari küçük ekip için çalışır, ama dokümanda eski karar parçaları hâlâ durduğu için implementasyon öncesi tek doğru modeli temizlemek şart. Şu an en büyük risk teknolojik eksikten çok karar drift’i: bazı bölümler hâlâ tek cluster, in-cluster TLS, geçici Eureka gibi önceki tasarımları anlatıyor.

## 8 Sorunun Cevabı

1. **2 k3d cluster vs tek cluster 2 namespace**  
Ben bu bağlamda `2 k3d cluster` kararını korurdum. Tek cluster + iki namespace kaynak paylaşımı için yeterlidir, ama sizin asıl korkunuz kaynak değil blast radius ve control-plane etkisi; onu tek cluster çözmez. Aynı host üzerinde olduğu için bu bir HA tasarımı değildir, host giderse ikisi de gider. Buna rağmen ayrı API server, ayrı etcd, ayrı CNI ve ayrı network, test tarafındaki kötü bir Helm/CRD/NetworkPolicy denemesinin prod’u bozma ihtimalini ciddi düşürür. RAM overhead mevcut bütçede taşınabilir görünüyor; test kapalıyken elde kalan rezerv buna izin veriyor. Sadeleştirme gerekirse ilk vazgeçeceğim şey iki cluster değil, test tarafındaki gözlenebilirlik ve ikinci dalga özellikler olur.

2. **Host nginx SNI vs MetalLB + cluster SSL**  
Tek host ve k3d için host-level nginx daha doğru seçim. MetalLB burada size gerçek bir platform kazanımı sağlamıyor; buna karşılık L2 davranışı, ek chart, ek failure mode ve iki cluster’a ayrı TLS secret yönetimi getiriyor. Sertifika yenileme host nginx’te daha basit, çünkü private key tek yerde durur, reload tek noktadadır, rollback de tek prosedürle yapılır. Ayrıca `test.acik.com` intranet-only olduğu için cluster içi ACME otomasyonu zaten daha kırılgan olacaktır. Bu modelde dikkat edilmesi gereken şey, `X-Forwarded-*`, websocket, upload size, timeout ve access log ayarlarını net yapmak. Çok node’lu gerçek k3s’e geçerseniz TLS termination’ı cluster içine alma seçeneğini o zaman yeniden değerlendirin.

3. **Eureka kaldırma riski**  
Asıl risk Eureka’yı kaldırmak değil, yarım kaldırmak. Ben bunu tek seferde tüm filo için değil, çağrı grafına göre dilimleyerek yapardım: önce bir servis, onu çağıranlar ve gateway route’u birlikte taşınmalı. `@EnableEurekaClient`, `@LoadBalanced` client’lar ve `lb://` route’lar aynı dilimde temizlenmeli; Eureka’yı K8s içinde geçici yaşatmak ikili discovery yaratır ve hata ayıklamayı zorlaştırır. K8s Service size sabit DNS ve kube-proxy load balancing verir, ama retry, timeout, connection pool ve circuit breaker davranışlarını artık açık şekilde yönetmeniz gerekir. İlk PoC’yi en az bağımlı servislerden biriyle yapın ve servisler arası çağrıları smoke test ile doğrulamadan genellemeyin. “Geçici olarak K8s içinde tek replica Eureka çalıştıralım” yaklaşımını ben önermem.

4. **Sectigo cert renewal**  
`2026-10-01` için mevcut topolojide en düşük riskli yol manuel Sectigo renewal. `ai.acik.com` için HTTP-01 teorik olarak çalışabilir, ama bunun için dış L4 proxy’nin `/.well-known/acme-challenge` akışını bozmadan size iletmesi gerekir; bu teyit edilmeden otomasyona güvenmem. `test.acik.com` intranet-only olduğu için aynı model iki hostname için simetrik olmayacak. Wildcard gerekiyorsa Let’s Encrypt tarafında DNS-01 gerekir; Windows AD DNS otomasyonu yoksa cert-manager burada sizi kurtarmayabilir. Ben şimdi otomasyon kovalamak yerine host nginx’te tek sertifika rotasyon script’i, reload prosedürü ve `60/30/7 gün` uyarı takvimi koyardım. Orta vadede en temiz çözüm, `_acme-challenge` için otomasyona açık ayrı DNS delegasyonu almaktır.

5. **JVM heap bütçesi**  
`8 x 384 MB` başlangıç için makul, ama doğrulanmış üretim kapasitesi değil. Buradaki kritik nokta şu: `-Xmx384m` ile `-XX:MaxRAMPercentage=75` birlikte verildiğinde pratikte `-Xmx` belirleyici olur; otomatik heap davranışı beklemeyin. Ayrıca heap dışında metaspace, direct buffer, thread stack ve JIT cache var; `512Mi` limitte bazı servisler heap dolmadan da `OOMKilled` olabilir. Ben ortak varsayılanı korur, ama ağır 2-3 servise ayrı limit override planlardım; herkese aynı heap vermek uzun vadede doğru değil. GraalVM’e bu migration içinde girmezdim; şu aşamada scope creep ve operasyonel risk üretir. Önce yük testi altında RSS, GC ve p95 latency ölçülmeli, sonra servis bazlı heap tablosu çıkarılmalı.

6. **Monitoring uzun vade**  
Bu stack bugünkü ölçekte sığar, ama “14 gün retention ile 12 ay rahat gider” varsayımına güvenmem. Tek host ve 10 servis için Prometheus + Grafana + Loki sürdürülebilir; Tempo ise örnekleme ve kısa retention olmazsa CPU/disk tüketimini hızlı büyütür. Ben başlangıçta Prometheus’u `7-10 gün`, Loki’yi `7 gün`, Tempo’yu `24-72 saat` ile açar, gerçek ingest ölçümünden sonra artırırdım. Thanos/Cortex ancak `30+ gün` saklama, host dışı object storage veya HA beklentisi geldiğinde anlamlı olur; bugün için erken. Şu an asıl ihtiyaç uzun vadeli dağıtık observability değil, retention sınırı, disk alert’i, log cardinality disiplini ve alert routing’in netleşmesi. Kısacası monitoring tarafını MVP’de biraz daraltmak daha güvenli.

7. **Backup / DR (RPO/RTO)**  
RPO/RTO yazılı değilse bu tasarım operasyonel olarak tamam değildir. Ben prod için başlangıç hedefini `RPO <= 24 saat`, `RTO <= 4 saat`; test için `RPO <= 24 saat`, `RTO <= 1 iş günü` olarak kilitlerdim. `pg_dump` iyi bir başlangıçtır ama tek başına zayıf kalır; en azından off-host kopya ve düzenli restore provası gerekir. Vault raft snapshot da aynı şekilde host dışına çıkmalı. K3d/k3s state için etcd snapshot alınabilir, ama GitOps dünyasında cluster’ı yeniden kurup veriyi geri dönmek çoğu zaman daha temizdir; asıl kritik olan PVC verisi, host compose state’i, cert ve Vault/PG yedekleridir. Eğer iş ihtiyacı `RPO < 1 saat` veya “aynı gün içinde garantili geri dönüş” istiyorsa, tek fiziksel host üstünde bu mimari zaten yetersizdir.

8. **Genel eksik/risk veya “YAPMA” uyarısı**  
En büyük eksik, dokümanın bazı yerlerinde iki farklı mimariyi aynı anda anlatması. `PLAN.md` içinde tek cluster vs iki cluster, cluster TLS secret vs host TLS, Eureka kaldırıldı vs geçici Eureka gibi stale parçalar duruyor ve bunlar yanlış manifest üretir: [PLAN.md:14](/Users/halilkocoglu/Documents/platform-k8s-gitops/PLAN.md:14), [PLAN.md:29](/Users/halilkocoglu/Documents/platform-k8s-gitops/PLAN.md:29), [PLAN.md:107](/Users/halilkocoglu/Documents/platform-k8s-gitops/PLAN.md:107), [PLAN.md:517](/Users/halilkocoglu/Documents/platform-k8s-gitops/PLAN.md:517), [PLAN.md:640](/Users/halilkocoglu/Documents/platform-k8s-gitops/PLAN.md:640). Daha basit alternatif elbette tek cluster + iki namespace, ama sizin geçmiş blast radius kaygınız nedeniyle ben bunu önermem. Benim “YAPMA” listem kısa: MetalLB’yi bu MVP’ye sokmayın, GraalVM’i bu migration’a bağlamayın, Eureka’yı geçici de olsa K8s’e taşımayın. Aynı host üstündeki iki cluster’ı DR gibi de sunmayın; bu sadece izolasyondur, süreklilik değildir. Admin UI’ları aynı hostname altında açıyorsanız erişim kontrolünü ayrıca sertleştirmeden bırakmayın.

## Benim Fark Ettiğim 3 Eksik Konu

- **HPA yolu net değil.** Plan `metrics-server`’ı kapatıyor ama sonra HPA hedefliyor; bu haliyle autoscaling çalışmaz. Ya HPA’yı MVP’den çıkarın ya da `metrics-server` / `Prometheus Adapter` kararını netleştirin.
- **CPU bütçesi RAM kadar çalışılmamış.** 4 vCPU host üzerinde quota toplamları, JVM GC, Prometheus compaction ve Loki ingest aynı ana denk gelirse throttle kaçınılmaz olabilir. RAM hesabı iyi, CPU hesabı eksik.
- **Stateful storage ve node bakım senaryosu tanımsız.** OpenFGA, Prometheus, Loki, Tempo ve ArgoCD için PVC/StorageClass/backup/restore/runbook tarafı açıkta. Tek node’da PDB ve iki replica gerçek HA sağlamaz; reboot, kernel patch ve disk arızası senaryosu ayrıca yazılmalı.

## Skorkart

| Alan | Puan | Kısa not |
|---|---:|---|
| Mimari | 4/5 | Pragmatik ve uygulanabilir, ama karar drift’i temizlenmeli |
| Kapasite | 3/5 | RAM iyi modellenmiş, CPU ve non-heap tarafı eksik |
| İzolasyon | 4/5 | Aynı host için güçlü izolasyon, ama HA değil |
| Gözlenebilirlik | 3/5 | Araç seçimi iyi, kapsam biraz fazla agresif |
| Operasyon | 3/5 | Fazlar iyi, ama restore/upgrade/runbook eksik |
| Güvenlik | 3/5 | Yön doğru, ama Vault auth, admin erişimi ve cert operasyonu açık |

## Bir Sonraki Somut Adım

Ben projenin sahibi olsaydım sonraki adım olarak tam manifest çoğaltmaya geçmezdim; önce ince bir PoC dilimi yapardım. Hedefim `2 k3d cluster + host nginx + host PG bridge + api-gateway + 1 backend` ile uçtan uca çalışan bir akış kurmak ve bu dilimde Eureka’yı tamamen kaldırmak olurdu. Bu tek adım D16, D18, D19 ve D7’yi aynı anda doğrular; geçmezse erken döner, geçerse kalan manifest’leri güvenle çoğaltırsınız. PoC’den önce de `PLAN.md` içindeki stale satırları temizleyip tek doğru mimariyi bırakırdım.
---

## Tur 2 — Codex Ham Cevabı

**1. Cert renewal itirazına cevap**

Bu maddede sen haklısın; beni ikna ettin. İki aşamalı yaklaşımı kabul ediyorum. Benim önceki sert itirazım, bunu MVP önceliği yapmama yönündeydi; senin önerdiğin model ise MVP’yi bozmadan ucuz bir doğrulama ekliyor. Sınır net: Faz 12’de yapılacak HTTP-01 dry-run yalnız `ai.acik.com` hattını doğrular; `test.acik.com` intranet-only kaldığı sürece bu deney onu kapsamaz. Bugünkü ana karar yine manuel Sectigo disiplini, sonraki karar ise “otomasyon denenir, kanıt varsa geçilir” şeklindedir.

**2. NOKTA 1-2-3-4 net cevaplar**

**NOKTA 1 — JVM flags çelişkisi**  
Onay. `-Xmx384m` varken `-XX:MaxRAMPercentage=75` sadece gürültü üretir ve yanlış beklenti yaratır. Bu plan explicit heap planıdır, yüzde tabanlı otomatik heap planı değildir. Varsayılanı sadece `-Xmx384m` yap, ağır 2-3 servise ayrı override ver.

**NOKTA 2 — HPA karar (MVP’de)**  
Onay: `B`. MVP’de HPA yok, `metrics-server` kapalı kalır. Prod’da sabit `replica: 2`, test açıldığında `replica: 1`; gerekirse manuel scale yapılır. HPA’yı ancak ilk gerçek CPU/latency grafikleri toplandıktan sonra geri açarız.

**NOKTA 3 — CPU bütçesi tahmini**  
Test kapalı tipik steady-state için gerçekçi bant `1.6-2.2 vCPU`, test açıkken `2.0-2.8 vCPU`’dur. `Prometheus` compaction, `Loki` flush/ingest, rollout ve JVM warm-up çakışırsa `3.4-4.0 vCPU` bandına vurur; dar limitli podlarda throttling başlar, limitsiz durumda ise node saturasyonu ve latency artışı görürsün. Politika `request dar ama gerçekçi, limit cömert` olmalı; `request=limit` bu hostta yanlış. Varsayılan backend için `150m` request, ağır servislerde `250-300m`, gateway’de `250m` mantıklı; limit `750m-1000m` bandında tutulur ya da kritik podlarda hiç konmaz.

**NOKTA 4 — PoC dilim servis seçimi**  
Onaylıyorum: ilk backend `auth-service`. Bu çift, `api-gateway -> auth-service -> Keycloak/DB` hattını doğrular ve Eureka temizliğini minimum servisler-arası bağımlılıkla test eder. `user-service` ikinci dilim olmalı; çünkü daha bağlı ve ilk doğrulamayı gereksiz zorlaştırır. `api-gateway` tek başına seçilmez; PoC değeri gerçek bir backend ve host-level bağımlılık hattını kanıtlamasındadır.

**3. PoC dilimi final kararı**

Başlangıç çifti `api-gateway + auth-service`. Sıra şu olsun: `api-gateway + auth-service` → `api-gateway + user-service` → kalan backend’ler bağımlılık grafına göre. İlk dilimin kabul kriteri net: gateway route `lb://` olmadan K8s service DNS’e dönecek, `auth-service` Eureka’sız kalkacak, Keycloak/DB host köprüsü çalışacak, smoke test yeşil olacak.

**4. UZLAŞI METNİ**

- D1: Deployment hedefi staging-sw üzerinde aynı hostta iki ayrı `k3d` cluster’dır: `prod` ve `test`; bu karar HA/DR değil, izolasyon kararıdır.
- D2: Namespace stratejisi cluster-bazlıdır; prod cluster `platform-prod`, `ingress-nginx`, `external-secrets`, `argocd`, `monitoring` çalıştırır, test cluster `platform-test`, `ingress-nginx`, `external-secrets` çalıştırır; prod ve test aynı cluster’ı paylaşmaz.
- D3: Lokal geliştirici makinesinde de aynı iki-cluster modeli kullanılır.
- D4: GitOps motoru `ArgoCD`’dur; tek instance prod cluster’dadır ve test cluster’ı multi-cluster olarak yönetir.
- D5: Manifest yönetimi `Kustomize` (base + overlay) ve `Helm` (3. parti chart’lar) ile yapılır.
- D6: PostgreSQL, Keycloak ve Vault Kubernetes dışında Docker Compose ile host’ta çalışır; prod ve test ayrı instance’tır.
- D7: Service discovery olarak Eureka kaldırılır; geçiş servis-bazlı dilimler halinde yapılır; her dilimde backend + onu çağıranlar + gateway route’u birlikte temizlenir; geçici Eureka yoktur.
- D8: TLS host-level nginx’te terminate edilir; MVP’de Sectigo wildcard manuel rotasyon, rotasyon script’i, `60/30/7 gün` uyarı ve panel erişim doğrulaması zorunludur; Faz 12 sonrası yalnız `ai.acik.com` için LE HTTP-01 dry-run yapılır, başarılıysa otomasyon ayrıca kararlandırılır, başarısızsa manuel Sectigo sürer.
- D9: Secret yönetimi `External Secrets Operator + Vault` ile yapılır; Vault source-of-truth olarak kalır.
- D10: Observability stack `kube-prometheus-stack + Loki + Tempo`dur; başlangıç retention değerleri Prometheus `10 gün`, Loki `7 gün`, Tempo `48 saat`tir.
- D11: Image registry `GHCR`’dır; mevcut image push akışı korunur.
- D12: Lokal `.git` aktiftir, remote yoktur; canlıya geçerken private GitHub repo açılır.
- D13: Yaklaşım atılabilir deneme değil, doğrudan canlı-ready yapıdır.
- D14: Ana repodaki `application-k8s.yml`, Dockerfile ve kod temizliği işleri manifest yazımıyla eş zamanlı yürütülür.
- D15: CNI olarak `Calico` kullanılır; NetworkPolicy garantisi için Flannel seçilmez.
- D16: Cluster topolojisi aynı hostta iki ayrı `k3d` cluster’dır; ayrı API server, etcd, CNI, Docker network, Pod CIDR ve Service CIDR kullanılır.
- D17: Test ortamı scale-to-zero’dur; test cluster control plane açık kalır, workload replica varsayılan `0`’dır, host-level test PG/KC/Vault de kapalı varsayılır.
- D18: Host-level nginx SNI reverse proxy `80/443`’ü alır; `ai.acik.com` prod `:30080`’e, `test.acik.com` test `:31080`’e yönlenir; cluster içindeki ingress-nginx HTTP-only çalışır.
- D19: Host servis köprüsü `Service + Endpoints` ile ve host IP `10.9.10.53` pin’lenerek kurulur; `ExternalName` kullanılmaz.
- D20: Mevcut host portları (`5432`, `8081`, `8200`) prod’a, yeni portlar (`5433`, `8082`, `8201`) test’e ayrılır; prod veri migrasyonu yapılmaz.
- D21: MVP’de HPA yoktur; `metrics-server` kapalı kalır; prod sabit `replica: 2`, test açıldığında `replica: 1` çalışır; manuel scale gerekirse operasyonel olarak yapılır.
- D22: CPU bütçesi test kapalı steady-state `1.6-2.2 vCPU`, test açık `2.0-2.8 vCPU`, kısa spike `3.4-4.0 vCPU` olarak planlanır; CPU request’leri dar ama gerçekçi, limitler cömert tutulur; `request=limit` yapılmaz.
- D23: DR hedefi prod için `RPO <= 24 saat` ve `RTO <= 4 saat`, test için `RPO <= 24 saat` ve `RTO <= 1 iş günü`dür; off-host backup, düzenli restore provası ve stateful/node bakım runbook’u zorunludur.
- D24: JVM bellek politikası ortak explicit heap’tir; varsayılan `-Xmx384m`, ağır 2-3 serviste override, test overlay’inde daha düşük heap kullanılır; `-XX:MaxRAMPercentage` kaldırılır.
- D25: İlk PoC dilimi `api-gateway + auth-service`’tir; ikinci dilim `user-service`’tir; PoC yeşil olmadan tam filo manifest çoğaltmasına geçilmez.
- D26: MVP kapsamında MetalLB yoktur, GraalVM migration scope’una alınmaz, K8s içinde geçici Eureka kurulmaz ve aynı hosttaki iki cluster hiçbir metinde DR/HA gibi sunulmaz.