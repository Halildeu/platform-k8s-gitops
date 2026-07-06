# Faz 22.9 - Endpoint Security Telemetry / Detection Extension

> **Status**: PLANNING / MATRIX TODO.
> **Created**: 2026-06-09
> **Board / issue authority**:
> - platform-k8s-gitops [#1388](https://github.com/Halildeu/platform-k8s-gitops/issues/1388) - sensitive endpoint ops governance gate
> - platform-k8s-gitops [#1400](https://github.com/Halildeu/platform-k8s-gitops/issues/1400) - OSS-only build-vs-buy decision matrix
> - platform-k8s-gitops [#1404](https://github.com/Halildeu/platform-k8s-gitops/issues/1404) - osquery/YARA/Sigma/Wazuh telemetry matrix

Bu doküman, Faz 22 endpoint-admin görünürlük hattını güvenlik telemetrisi ve
bounded detection kabiliyetleriyle genişletme adaylarını tanımlar. Faz 22.9 bir
runtime endpoint scan yetkisi değildir; önce açık kaynak karar matrisi,
lisans/güvenlik sınırı ve #1388 governance gate'i gerekir.

## 1. Amaç

- Endpoint-admin envanter/compliance verisini güvenlik telemetrisi için
  genişletilebilir hale getirmek.
- Hafif ve denetlenebilir scanner/query bileşenlerini değerlendirmek.
- SIEM/HIDS gibi ayrı control-plane ürünlerini endpoint-admin core içine
  taşımadan entegrasyon sınırını belirlemek.

## 2. Faz Sınırı

| Kapsam | Faz | Karar |
|---|---:|---|
| Software inventory, compliance, diagnostics, app-control visibility | 22.5 | Mevcut software deployment / visibility hattı |
| Endpoint backup, offboarding, forensic collection | 22.8 | Endpoint Data Protection hattı |
| Security telemetry / detection extension | 22.9 | Bu dokümanın kapsamı |
| Full SIEM/HIDS platform adoption | Future / separate charter | Faz 22.9 core hedefi değil |

## 3. OSS-only Karar Matrisi

> **Canonical karar:** Bu matris artık [ADR-0036](./adr/0036-faz-22-oss-build-vs-buy.md) tarafından konsolide edilmiştir (owner kararı 2026-06-09: "Kategori 1 ve 2 tamamını biz yazalım"). Özet: **posture telemetri zaten in-house** (AG-035/037/038/039/040 probe hattı); **YARA** yalnız dosya-içerik IOC/malware/imza taraması gerçekten gerektiğinde wrap edilir (ayrı scanner sınırı + #1388 + DPA/lisans); **osquery/Sigma/Wazuh skip** (posture zaten toplanıyor; Sigma DRL 1.1 lisans-gated, standart OSS değil; Wazuh full SIEM/HIDS = ikinci control plane, reject-as-core). Aşağıdaki tablo gerekçe referansı olarak korunur; bağlayıcı karar ADR-0036'dadır.

| Araç / yaklaşım | Lisans sinyali | Karar | Gerekçe | Takip |
|---|---|---|---|---|
| osquery-style query/table model | Apache-2.0 project signal; packs/extensions separately reviewed | **SKIP** (ADR-0036) | Posture telemetri zaten in-house toplanıyor (AG-035/037/038/039/040); ayrı fleet manager/query motoru gereksiz | #1404 |
| YARA | BSD-3-Clause | **WRAP-only-if-scan** (ADR-0036) | Yalnız dosya-içerik IOC/malware/imza scan gerektiğinde wrap; secret/credential-scan AYRI scanner sınırı olabilir; bounded job + resource cap + audit | #1404 |
| Sigma rules | DRL 1.1 | **SKIP** (ADR-0036; license-gated) | DRL 1.1 standart permissive OSS değil; attribution/legal gate olmadan rule reuse yok | #1404 |
| Wazuh | GPL-2.0 family | **SKIP / reject-as-core** (ADR-0036) | Full SIEM/HIDS stack = ikinci control plane + ağır ops footprint | #1404 |
| Velociraptor | AGPL-3.0 | **reactivation-trigger only** (ADR-0036) | Yalnız DFIR artifact-collection/live-hunt landerse (22.8C clean-room + legal #1403) re-evaluate; standing server YOK | #1403 |

## 4. Non-goals

- Wazuh veya başka bir SIEM/HIDS ürününü endpoint-admin core control plane
  olarak almak.
- Endpoint üzerinde #1388 kabulü olmadan scan/runtime action çalıştırmak.
- Paid/proprietary/SaaS veya source-available ama OSS olmayan detection
  bileşenlerine bağımlı olmak.
- Sigma rule'larını lisans/attribution kararı olmadan ürün içine taşımak.
- Security telemetry'yi kullanıcı dosyası toplama veya forensic evidence copy
  ile karıştırmak.

## 5. İlk Güvenli Slice

> Build-vs-buy karar matrisi artık [ADR-0036](./adr/0036-faz-22-oss-build-vs-buy.md) ile **decision-closed**: posture in-house (AG-*), YARA wrap-only-if-scan, osquery/Sigma/Wazuh skip. Bu bölümdeki "ilk güvenli slice" artık "matrisi karar bağla" değil; **scan kabiliyeti gerçekten landerse** çalışacak runtime scanner kontratı tasarımıdır:

1. Posture telemetri zaten in-house (AG-035/037/038/039/040) — yeni motor gerekmez.
2. **YARA wrap** ancak dosya-içerik IOC/malware/imza scan kabiliyeti devreye alınırsa: runtime scan açmadan bounded scan/job packaging modeli + lisans/kullanım sınırı tasarlanır (ayrı ADR + #1388 + DPA).
3. Resource caps, denylist, redaction ve audit event kontratı belirlenir; secret/credential-scan AYRI scanner sınırı olarak ele alınır.
4. SIEM/HIDS (Wazuh) ve Sigma reuse'u **skip** — adoption gerekirse ayrı charter/ADR (ADR-0002 §7.1 kaynak bütçesi).

Bu slice endpoint üzerinde scan çalıştırmaz ve agent binary değişikliği
gerektirmez.

## 6. D29 Acceptance Model

| Katman | Kanıt |
|---|---|
| **Up** | Matrix ve contract issue'ları Project #2'de canonical; runtime disabled |
| **Functional** | Bounded query/scan contract fixtures ve negative cases tanımlı |
| **Secured** | #1388 RBAC, dual-control, audit, redaction, resource cap ve retention kararları scan/runtime action için enforce edilebilir |

22.9 için "security telemetry var" iddiası yalnız bu katmanlar ayrı
kanıtlandığında kurulabilir.

## 7. Board Mapping

| Issue | Rol | Status yorumu |
|---|---|---|
| gitops #1388 | Sensitive Endpoint Ops Governance Gate | Runtime scan/action ön koşulu |
| gitops #1400 | OSS-only build-vs-buy decision matrix | **DECISION-CLOSED by ADR-0036** (Cat1+2 in-house) |
| gitops #1404 | 22.9 telemetry/security matrix | **CLOSED by ADR-0036**: posture in-house (AG-*), YARA wrap-only-if-scan, osquery/Sigma/Wazuh skip; runtime scanner kontratı yalnız scan kabiliyeti landerse |
