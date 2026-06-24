# RB — Faz 22.6 #548 Hardware-Attestation Gap Audit + Concrete Runbook

> **Amaç:** `GATE_B1_4_HARDWARE_ATTESTATION` (platform-backend#548) için "kod hazır mı, broker
> acceptance'a tam bağlı mı?" sorusunu **no-ambiguity** hale getirmek; kalıcı (strong-hardware)
> yolu ile bounded-pilot risk-accept yolunu dürüstçe ayırmak. Üzeri-kapama DEĞİL.
>
> **3-AI consensus** (Claude impl + Codex review, owner Halil Koçoğlu): #1901 kapalı (kritik-path
> değil), #1580 insanlı pilot bekliyor, **#548 koddan netleştirilecek tek agent-doable belirsizlik**.

## 0. Üç sert ayrım (her bulguda korunur)

| Ayrım | Anlamı |
|---|---|
| **vTPM/swtpm ≠ hardware secure element** | vTPM gerçek kripto/interop kanıtı verir; ama `positive_matrix: hardware-attested-device` marker'ı için fiziksel TPM/secure element ile **aynı güvence sınıfı değildir**. vTPM kanıtı = "bounded-lab TPM evidence". |
| **machine cert enrollment ≠ hardware attestation** | Broker'ın `MACHINE_CERT_ENROLLMENT` modu = enrollment kimliği; **donanım anahtar attestation'ı değildir** (kodun kendi ifadesi). |
| **source proof (kod/test) ≠ acceptance marker** | TPM pipeline kodu/test'leri gerçek olabilir; bu marker'ı kapatmaz. Marker = canlı broker kabul + field matrix + named-owner + issue body. |

## 1. 8 soru — koddan cevap (file:line)

> Repo'lar: `platform-backend` (verifier + broker), `platform-agent` (Go prover).

### Q1 — Agent hangi TPM evidence'ı üretiyor?
`platform-agent/internal/tpmenroll/tpmdevice_windows.go` (Windows TBS, go-tpm v0.9.8): EK create (`:56`),
AK restricted RSA-2048 (`:67`), device-key EC-P256 (`:81`), ActivateCredential (`:128`), Quote (`:145`),
Certify (`:161`), device-key CSR PoP (`:269`). **Gerçek kripto.**
**[GAP-1] EK-cert NV-read STUBBED** — `EndorsementKey()` (`:107-113`) `certDER=nil` döndürür; yorum: "backend
V2 EK-chain config-pinned + off-by-default, disabled-by-default pilot için boş cert kabul edilebilir."
→ **Sınıf: [agent-doable code]**, ama bkz Q-EK altında "gate-zorunlu mu?" ayrımı.

### Q2 — Backend enrollment endpoint hangi evidence'ı doğruluyor?
`endpoint-admin-service/.../tpmattest/TpmEnrollmentController.java` (`/nonce`=leg1, `/attest`=leg2) +
`tpmattest/` paketi: V1 nonce anti-replay, V2 EK→manufacturer-root chain (`TpmEkChainValidator.java:78`,
PKIX), V3 AK↔EK binding, V4 Certify (`TpmAttestationVerifier.java:37`), V5 Quote+nonce (`:63`), V6 PCR,
V9 CSR-key, V10 MakeCredential (`TpmMakeCredential.java:72`), V11 AK-restricted, V12 algo/key-bits.
**Hepsi gerçek, fail-closed, uniform-403.** Stub/simülasyon-bypass yok. → **Sınıf: [done]**.

### Q3 — Enrollment sonucu broker `deviceTrusted=true` kararına nasıl bağlanıyor? → **BAĞLANMIYOR (ANA GAP)**
Broker per-session device-trust'ı **ayrı** bir yoldan geçer:
`remoteaccess/bridge/orchestrator/SessionDeviceTrustVerifier` (factory ile seçilir). TPM enrollment
pipeline'ı (Q2) bir **cert issuance** akışı; broker'ın session HELLO'sundaki `device=true` kararını
beslemiyor. Codex 019efada ek kanıt:
- `TransportBoundPeerEvidenceParser.java:34` — mevcut `AgentHello.attestationEvidenceB64` **SLSA/build
  provenance** olarak çözülüyor; `deviceKey` **kasıtlı boş bırakılıyor** (wire-contract device-key taşımıyor).
- `TrustEvidenceAssembler.java:18` — broker device-trust'ı attestation ledger'ından değil, injected
  `SessionDeviceTrustVerifier`'dan (session/enrollment bağlamı) alıyor.
- `DeviceIdentityVerifier.java:29` — **offline** attestation statement doğruluyor; canlı challenge-response
  ayrı transport slice (replay/freshness boşluğu).

Canlı kanıt: `HELLO_VERIFIED:cert=true,attestation=true,device=false` (current-state.md:1797).
→ **Sınıf: [wire-contract feature gap]** — enrollment ↔ session-device-trust köprüsü yok; HELLO wire-contract
device-key taşımıyor; broker offline-statement ile canlı-session-trust arasında köprü kurmuyor.

### Q4 — `MACHINE_CERT_ENROLLMENT` ↔ hardware attestation sınırı nerede?
`SessionDeviceTrustVerifierFactory.java:11-19` (Javadoc) + `:74-79` (reject): `MACHINE_CERT_ENROLLMENT`
= "session peer = aktif enrolled machine cert; **enrollment identity, NOT hardware key attestation**;
production-like profile'da YASAK." `MachineCertEnrollmentDeviceTrustVerifier.java` aynı şeyi açıkça söyler.
→ **Sınıf: [done — ama sadece enrollment-trust; hardware değil]**.

### Q5 — `DEVICE_KEY_ATTESTATION_REAL` gerçekten yok mu, başka isimle mi var? → **YOK**
`SessionDeviceTrustVerifierFactory.java:25`: `enum VerifierType { FAIL_CLOSED, MACHINE_CERT_ENROLLMENT }`
— **sadece 2 mod**. `:20-21` Javadoc: *"Future modes (`DEVICE_KEY_ATTESTATION_REAL`,
`REQUIRE_ENROLLMENT_AND_DEVICE_KEY`) arrive only once the agent wire contract carries a real device-key
attestation."* → **Sınıf: [wire-contract feature gap]** — bu mod **inşa edilmeli**. Bu, #548'in gerçek
kalıcı boşluğu: mükemmel TPM koşusu bile bu mod olmadan `device=false` bırakır.

### Q6 — Vault PKI / root-policy canlı path'i nerede, hangi drill ile kanıtlanıyor?
`tpmattest` Vault PKI issuance client implement + hardened, **ama canlı Vault'a karşı hiç koşulmadı**
(gate-5 operator drill pending). EK-chain root-policy = `TpmAttestProperties.java:25` operator-pinned
manufacturer roots (`manufacturer-root-pems` + `-sha256`); boş anchor → startup fail-closed
(`TpmEnrollmentConfig.java:66`). → **Sınıf: [operator drill — live Vault]** + config.

### Q7 — Strong hardware marker için positive/negative matrix hangi komutlarla üretilecek?
Bugün kanıtlanan tek şey **verifier-only crypto**: `endpoint-admin-service/src/test/resources/tpmattest/
swtpm-golden-repro.sh` + `TpmGoldenVectorTest.java:57` (swtpm + lab-CA-pinned EK → pass; farklı fingerprint
→ fail-closed). **Canlı wire-level positive/negative matrix (broker accept/deny) ÜRETİLEMİYOR** çünkü Q3/Q5
köprüsü+modu yok. → **Sınıf: [blocked-until Q3/Q5 done], sonra real-hardware run]**.

### Q8 — vTPM kullanılırsa marker dili ne; fiziksel TPM gerekiyorsa hangi cihaz?
vTPM/swtpm + lab-CA-pinned EK → **"bounded-lab TPM evidence"** (marker'da AÇIKÇA böyle etiketlenir;
`positive_matrix: hardware-attested-device` veya `tpm_or_secure_element: present` İDDİA EDİLEMEZ).
Strong marker için **fiziksel TPM 2.0** gerekir — mevcut: `SRB-AIDENETIMPC` (gerçek domain Win
workstation, firmware TPM), AgentPC1/PC2. → **Sınıf: [real-hardware run + dürüst marker dili]**.

## 2. Dürüst hüküm

- **TPM enrollment pipeline (Q1-Q2) GERÇEK ve büyük ölçüde tamam.** Ama bu bir cert-issuance akışı.
- **#548'in gerçek boşluğu broker tarafında (Q3+Q5):** session device-trust'ı besleyen bir
  **device-key-attestation wire-contract + `DEVICE_KEY_ATTESTATION_REAL` verifier modu YOK.** Bu yüzden
  canlı `device=false`. Bu "küçük Go + bir koşu" değil; **bir feature slice**.
- Dolayısıyla #548'i "hardware-attested" olarak dürüstçe kapatmak için **A yolu** gerekir. **B yolu**
  (risk-accept) gate'i kapatır ama hardware'i kanıtlamaz — yalnızca açıkça etiketli interim.

## 3. İki yol (dürüst)

### A — KALICI (strong-hardware) — önerilen
Sıralı, çoğu agent-doable:
1. **[agent-doable code]** Agent wire-contract: session HELLO'ya device-key attestation evidence ekle
   (Quote+Certify+AK-Name+EK-ref). Gerekirse GAP-1 (EK-cert NV-read) bu noktada kapatılır — bkz Q-EK.
2. **[agent-doable code]** Broker: `VerifierType.DEVICE_KEY_ATTESTATION_REAL` modunu inşa et
   (`SessionDeviceTrustVerifierFactory` + yeni `DeviceKeyAttestationDeviceTrustVerifier`) — enrollment
   sonucu/attestation evidence'ını doğrulayıp `deviceTrusted=true` üretir. Codex cross-review.
3. **[operator drill]** Q6: canlı Vault PKI issuance + manufacturer-root pin (strong) veya lab-CA pin (bounded).
4. **[real-hardware run]** Fiziksel TPM'li cihazda (SRB-AIDENETIMPC) end-to-end: HELLO `device=true`;
   positive matrix `hardware-attested-device` + negative matrix `missing,stale,replay,wrong-device,wrong-tenant`.
5. **[marker]** #548'i strong marker ile kapat. Sözleşme-zorunlu alanlar (`device_key_evidence: present`,
   `tpm_or_secure_element: present`, `agent_wire_contract: present`, `broker_verifier: pass`, `root_policy:
   pass`, `field_evidence: attached`, `positive_matrix: hardware-attested-device`, `negative_matrix:
   missing,stale,replay,wrong-device,wrong-tenant`, named owner). **+ Codex 019efada sertleştirmesi** (offline
   statement ↔ canlı session-trust köprüsünü ispatla, replay'i kes):
   - `live_device_key_possession: pass` / `fresh_session_challenge: pass` — canlı possession/freshness
     (sadece offline attestation statement replay'e açık yorumlanmasın; bkz `DeviceIdentityVerifier.java:29`).
   - `attested_device_key_matches_session_mtls_or_permit_binding: pass` — `deviceId` ↔ cert thumbprint ↔
     enrollment id ↔ TPM device-key/CSR-key ↔ canlı peer-key zinciri kurulu.
   - `ek_cert_chain_source: tpm-nv-or-approved-device-ca` + `manufacturer_or_device_root_policy: pass` —
     EK-cert NV-read kapatıldı + root pinlendi (bounded path'te boş EK kabul; strong path'te zorunlu).

### B — bounded-pilot risk-accept (orchestrator'ın önerdiği) — yalnız açık-etiketli interim
`F22_6_B1_4_RISK_ACCEPTANCE: v1` (#548 OPEN kalır): `accepted_gap=no-real-tpm-attestation`,
`risk_scope=bounded-pilot-enrollment-backed-trust`, `forbidden_claims` (tpm-complete, hardware-attestation-
complete, production, broad-rollout, 5/50/800-device), named owner + expiry. **`device=false`, hardware
İDDİA EDİLMEZ.** Gate'i kapatır ama A yolundaki feature slice'ı yapmaz → kalıcı değil.

## Q-EK — EK-cert NV-read: gate-zorunlu mu, kalite-sertleştirmesi mi?
GAP-1 (agent EK-cert NV-read stub) siyah-beyaz "eksik" değil:
- **Bounded/pilot path:** backend EK-chain config-pinned + off-by-default → EK cert boşluğu kabul edilebilir.
- **Strong-hardware path:** EK cert chain → pinned manufacturer/lab root **ZORUNLU**; marker'daki
  `root_policy: pass` bunu ispatlar. → A yolu seçilirse GAP-1 kapatılır; B yolu için zorunlu değil.

## 4. Bağlam — diğer gate'ler (non-gating burada)
- **#1901 release-lineage: KAPALI / `F22_6_RELEASE_LINEAGE=pass` / `WAIVER=not_required` / v0.3.1 immutable.**
  Kritik-path değil. Tek izlem: v0.3 immutable-release enforcement script'lerinin main'de olması (varsa
  worktree'de) **non-gating regression-guard follow-up** — #1901 kapanışını GERİ AÇMAZ.
- **#1580 view-only:** çekirdek kod var; canlı attended product-channel pilot + **KVKK attended signoff
  (insan, indirgenemez)** + HTTPS evidence manifest gerekiyor. Ayrı runbook.

## 5. Acceptance
`faz22-6-completion-audit.sh` #548'i ancak issue body'de geçerli marker (A=strong CLOSED veya B=risk-accept)
ile pass eder. Marker/issue-body verifier'dan geçmeden `F22_6_COMPLETION=pass` beklenmez.

## Referans
- 3-AI consensus thread (bu PR Cross-AI bloğu)
- `RB-faz22.6-autonomous-completion-contract.md` (marker schema §4 + owner-decision §7)
- platform-backend `tpmattest/`, `remoteaccess/bridge/orchestrator/SessionDeviceTrustVerifierFactory.java`
- platform-agent `internal/tpmenroll/`
