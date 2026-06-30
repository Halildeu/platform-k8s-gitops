# Faz 26 — Governed Process & Work Platform (Süreç-Yönetişim Platformu) Canonical Plan

> **Status**: LOCKED (strateji) — Cross-AI consensus 2026-06-30 + owner "persist" onayı.
> Stratejik yön **AGREE** (Codex/OpenAI 3-iter ping-pong); kalan: owner final ürün sign-off + ADR'ler + 26B+27 ölçülebilir acceptance kriterleri + board instantiation.
>
> **İzolasyon (HARD RULE)**: Bağımsız ürün — Faz 1-24 ile **karışmaz**. Ayrı namespace + ayrı board/project + ayrı ADR serisi + ayrı OpenFGA store + ayrı WORM bucket + ayrı Vault path. **Paylaşılan** yalnız: GPU compute host (ollama/whisper), Keycloak SSO, GitOps deseni.
>
> **Mutabakat trail**: Claude (Anthropic, karar/implementer) + Codex `019f180a` (OpenAI, reviewer — iter-1 REVISE → iter-2 strateji-AGREE/scope-REVISE → iter-3 **AGREE**). Mavis (MiniMax) denendi; kanal 401-down (auth), non-blocking — HARD RULE Cross-AI minimumu (farklı sağlayıcı review) Codex ile karşılandı.

---

## 1. Vizyon & Konumlandırma

On-prem, KVKK-uyumlu, izin-farkında, AI-native **süreç-merkezli entegre yönetişim + work platformu**. Tek bağlı (graph) model: `süreç ↔ adım ↔ kişi/rol ↔ risk ↔ kontrol ↔ KPI ↔ doküman ↔ kural ↔ görev ↔ çerçeve`. Herhangi düğümden gir → bağlı her şeyi gör → karma/serbest filtre → **izin-farkında** → her noktada on-prem AI (sor/özetle/otomatize).

**Konumlandırma cümlesi (kilitli):**
> "Regüle/on-prem kurumlarda süreç, kontrol, risk, kanıt ve aksiyonları **tek izin-farkında graph** üzerinde **günlük iş akışına** bağlayan sistem."

Bu cümle ürünü Work-OS'tan da (Monday/ClickUp), GRC'den de (MetricStream/ServiceNow), EA/BPM'den de (ARIS/Signavio/Appian) ayırır: hiçbiri "derin governance + modern work surface + on-prem AI"yı tek izin-farkında graph'ta birleştirmez.

## 2. İlk Dikey & Pazar Stratejisi (NET)

**İlk dikey = TR kamu / regüle holding — İç Kontrol + KVKK + ISO/COSO + kanıt yönetimi.**

Gerekçe (Codex iter-2/3 + owner governance vurgusu): on-prem zorunluluğu, KVKK, **Kamu İç Kontrol Standartları (COSO-temelli)**, COSO/ISO crosswalk, audit evidence + WORM, izinli graph ve kamu uyum dili aynı anda anlam kazanır. Finans/P2P daha hızlı para getirebilir ama kalabalık + ERP/workflow vendor'larının güçlü olduğu alan → "Workcube üstü satınalma workflow'u" algı riski.

**P2P kapsam dışı değil ama wedge değil:** ilk 12 ayda yalnız **kanıt/kontrol senaryosu** (yetki matrisi, onay kanıtı, görev ayrılığı/SoD, KVKK/ISO control evidence). Automation wedge **değil**.

Yatay çekirdek **çok-dikey-yetenekli** kalır; derinleşme tek dikeyden (kamu) başlar. Ek dikeyler (finans/hukuk) Faz 32.

## 3. Rakip Arenası (6 kamp) + Köprü Tezi

| Kamp | Temsilci oyuncular | Güçlü | Zayıf |
|---|---|---|---|
| A · Süreç/EA | ARIS, Signavio, HOPEX, ADONIS, iGrafx | modelleme + mining | yürütme zayıf, model dokümantasyon olup kopabilir |
| B · GRC/IRM | MetricStream, ServiceNow, OpenPages, AuditBoard | risk/kontrol/denetim derinliği | süreç+doküman UX zayıf, pahalı/ağır |
| C · BPM yürütme | Appian, Pega, Camunda, Bizagi | BPMN/RPA/agent orkestrasyon | governance/risk/KPI ikincil |
| D · Entegre IMS | Interfacing EPC, Ideagen | QMS+BPM+DMS+GRC tek çatı (en yakın) | global/EN, on-prem-AI/KVKK/EBYS zayıf |
| E · Work-OS | Monday, ClickUp, Asana, Atlassian/Jira | görev/plan/izleme + AI ajan | **bulut**, governance/risk yok |
| **F · Biz** | — | **birleşik + on-prem AI + izin-farkında + TR-uyum** | yeni, derinlik kazanılacak |

**Köprü tezi:** Üst yarı (governance: risk/kontrol/uyum/denetim) B/D'nin; alt yarı (iş/verimlilik: görev/plan/izleme) E'nin. **İkisinde birden güçlü + on-prem AI + izin-farkında kimse yok.** Wedge = iki yarıyı tek izin-farkında graph'ta köprüle. (Detay matris: bkz. konuşma kaydı + ileride `docs/faz-26-feature-matrix.md`.)

## 4. Mevcut Altyapı Reuse Haritası

| Mevcut bileşen | Yeni üründe karşılığı | Reuse tipi |
|---|---|---|
| OpenFGA + permission-service | izin-farkında her node/mercek | pattern + ayrı store |
| Keycloak + M365 broker | kimlik/SSO | paylaşılan servis |
| Vault + ESO | secret/şifre | paylaşılan/pattern |
| 7-yıl WORM (MinIO) + hash-chain audit | records/evidence + audit izi | pattern + ayrı bucket |
| on-prem ollama (llama3.1) | RAG/özet/IDP/agentic | paylaşılan GPU host |
| whisper + citation/RAG deseni | "sürecine/belgene sor" + meeting köprüsü | pattern |
| notification orchestrator | uyarı/SLA/onay bildirimi | paylaşılan servis |
| Workcube ERP + schema-service | süreç besleme + ERP aksiyon + master data | entegrasyon |
| Frontend MFE + AG-Grid | çiçek/explorer/pano/tablo | komponent/pattern |
| GitOps + ArgoCD + k3d (on-prem) | on-prem dağıtım + multi-tenant | paylaşılan pattern |
| Prometheus/Grafana/Loki | canlı izleme temeli | pattern |
| Meeting Intelligence (özet/karar/aksiyon) | toplantı→görev/süreç köprüsü | entegrasyon |

**Net:** Faz 26A çoğunlukla reuse (izin/kimlik/secret/audit/AI-compute/dağıtım hazır). Asıl YENİ emek: ① bağlı-veri/ontology + pivot motoru ② sade BPMN ③ governance/crosswalk motoru ④ work-OS katmanı ⑤ AI-otomasyon/agentic.

## 5. 🔒 Kilitli Faz Planı (Board Epic Yapısı)

Her faz = bağımsız RELEASABLE modül + D29 kanıtlı + tarayıcı smoke. Her faz = board **epic**; alt-bileşenler = issue. Her faz ritüeli: charter → ADR → board epic → issue → cross-AI review → D29 release.

| Epic | Ad | İçerik | Release |
|---|---|---|---|
| **26A** | Internal Foundation | ontology v1 + OpenFGA model + evidence ledger + WORM binding + **records stub-model** + UI shell + **execution primitive tam set** + leak-hardened RAG iskeleti | iç (foundation) |
| **26B** | First Closed Loop | TEK kamu iç-kontrol alanı + import/adoption pipeline (Excel/doküman/EBYS/M365/Workcube → önerilen graph → kullanıcı doğrula) + **gap→action→owner→evidence→reviewer-accept** + basit routing + audit trail | ⭐ public |
| **27** | Public Wedge Experience | süreç haritası (sade BPMN) + çiçek/pivot + framework/control/risk/evidence/owner görünürlüğü | ⭐ public |
| — | **PUBLIC İLK RELEASE** | **= 26B + 27 birleşik** (içeride 26A foundation ayrı; müşteriye foundation satılmaz) | 🚀 satılabilir |
| **28** | Governance Deepening | çerçeve+risk+kontrol+**crosswalk**+olgunluk/gap+records-mgmt full (retention/disposition/e-discovery/legal-hold case/classification)+audit pack export | release |
| **29** | Work-OS + Live Monitoring | görev/iş planı/OKR↔KPI + board/list/grid/calendar/Gantt + canlı izleme + uyarı | release |
| **30** | Workflow-Lite Expansion | 26-27 basit routing üstüne: conditional branching, reusable templates, Workcube trigger orchestration, multi-step approval, compensation/rollback, complex routing | release |
| **31** | Full DMN + Agentic | full DMN + tool-using on-prem agent (guardrail'li) | release |
| **32** | Verticals + TR Uyum + Paketleme | ek dikeyler (finans/hukuk) + e-imza/KEP/EBYS/e-Fatura + multi-tenant/lisanslama/beyaz-etiket | release |

### 5.1 Faz 26A — Execution Primitive Tam Set (Codex iter-2 absorbe)
`task` · `owner` · `due` · `status` · **`approval` (basit 1-2 adım)** · `comment` · `evidence-attach` · `decision-record` · `change-history` · `assignment/delegation` · `SLA/escalation stub` · `watcher/subscriber` · `notification-event` · `closure-reason/acceptance-marker` · `evidence-sufficiency-status`.
> Karmaşık onay (paralel/conditional matrix/DMN/delegation chains) → Faz 30/31.

### 5.2 Faz 26A — Records Stub-Model (Codex iter-2: "yanlış model kurma")
Faz 26'da **şart**: `record/evidence ayrımı` · `retention-class alanı` · `legal-hold flag` · `immutable evidence ID` · `hash-chain/object-lock ref` · `custody/event log` · `disposition policy placeholder` · `exportable audit trail`.
> Full retention schedule / disposition workflow / e-discovery / legal-hold case mgmt / classification automation / destruction cert → Faz 28.

### 5.3 Faz 26-27 — Basit Routing (Codex: 30'a bekletme)
Minimum: `submit→review→approve/reject→close` · `gap→action→owner→evidence→reviewer-accept` · `deadline→escalation-event` · `status→notification-event`.

## 6. Cross-cutting Workstreams (faz değil; sürekli)

1. **Permission-leak hardening** — her graph traversal / arama / RAG / AI özet çıktısı **izin-filtreli** (Codex: en büyük gizli risk).
2. **Records-mgmt** — doğru model (26) → derinleşme (28).
3. **AI guardrails** — eval harness, tool-permissioning, prompt-injection savunması, human-in-loop approval, rollback, action audit (ilk AI özelliğinden itibaren).
4. **Ontology + import/adoption** — canonical şema + glossary + event modeli + import yolu (26'da anchor, dikey başına genişler). "Boş graph" tuzağına karşı.

## 7. 12-Ay Sınırı (kapsam patlamasına karşı kilit)

- ✅ **YAP:** TR kamu/regüle holding için **tek seçili iç-kontrol alanında** süreç-kontrol-risk-kanıt-görev graph'ını import edip, izinli AI desteğiyle **gap→action→evidence→review** döngüsünü **WORM audit iziyle** günlük kullanıma sokmak.
- ⛔ **YAPMA:** genel-amaç Work-OS, full BPM/DMN suite, full records-management ürünü, çok-dikey paketleme, derin ERP transaction automation, otonom agentic action platformu.

## 8. Acceptance (26B+27 pilot) — placeholder (Codex'in işaret ettiği sıradaki iş)

D29-tarzı ölçülebilir pilot kabul kriterleri ayrı dokümanda netleşecek (`docs/faz-26-26b-27-acceptance.md`). Çekirdek "wow" metriği:
> "Mevcut Excel/doküman/EBYS/M365/Workcube verisini içeri al → AI önerisiyle süreç-kontrol-risk-kanıt-görev graph'ına çevir → kullanıcı doğrulasın → çiçekte her düğümden bağlı risk/kontrol/kanıt/görev görsün → izinli AI özet üretsin → aksiyon ata → kanıtı WORM audit iziyle bağla."

Katmanlar (D29 uyarlama): **Up · Functional · KVKK-safe · Permission-enforce (leak yok) · Records-model-correct · Browser-smoke**.

## 9. Açık Kararlar & Riskler

- **İsim**: provisional "Süreç-Yönetişim Platformu / Governed Process & Work Platform". Owner kararı bekliyor.
- **Board/project**: yeni bağımsız project (Meeting Intelligence Project #4 deseni) vs Project #2 içinde izole label. İzolasyon kuralı → ayrı project tercih.
- **Risk — kapsam**: en büyük başarısızlık riski teknik değil, **ürün kimliği bulanıklığı**; 12-ay sınırı + tek-kapalı-döngü ile mitige.
- **Risk — reuse**: OpenFGA graph/RAG izin-leak; WORM≠records; agentic guardrail eksikliği (bkz. §6).

## 10. Cross-AI Mutabakat Trail

| Tur | Kanal | Verdict | Özet |
|---|---|---|---|
| iter-1 | Codex `019f180a` (OpenAI) | REVISE | execution öne, Faz 26 = Governed Evidence Workspace, tek dikey, ontology+import eksik |
| iter-2 | Codex (aynı thread) | strateji AGREE / scope REVISE | Faz 26 → 26A+26B böl, public=26B+27, primitive/records/routing detay, ilk dikey NET=kamu |
| iter-3 | Codex (aynı thread) | **AGREE** | "stratejik olarak kilitlenebilir; sıradaki iş 26B+27 acceptance kriterleri" |
| — | Mavis (MiniMax) | N/A | kanal 401-down (auth); non-blocking |

## 11. Sonraki Adımlar

1. **26B+27 acceptance kriterleri** (Codex'in işaret ettiği sıradaki iş) — ayrı doküman.
2. **ADR'ler**: KVKK boundary (DMS/governance), topology (on-prem + GPU host reuse), AI-agent guardrail, izin-leak hardening contract.
3. **Board instantiation**: 9 epic (26A/26B/27/28/29/30/31/32 + cross-cutting) — ayrı project.
4. **Faz 26A başlangıç**: ontology v1 + OpenFGA model + evidence ledger.

## References
- Cross-AI thread: Codex `019f180a-9eaf-79a2-a7ca-4bb834ad91c5` (3-iter, AGREE final)
- Mevcut platform reuse: ADR-0002 (dual-cluster), ADR-0042 (WORM audit-archive), ADR-0021 (M365 SSO), ADR-0030/0031 (Meeting Intelligence KVKK + two-server — reuse deseni)
- Global HARD RULE: Cross-AI Peer Review (provider seviyesinde) + Plan Consensus Autonomy + No Fake Work + Uzun Vadeli Kalıcı Çözüm + Türkçe cevap + diğer-fazlarla-karışmama (izolasyon)
- Faz 24 plan deseni: `docs/faz-24-meeting-intelligence-plan.md`
