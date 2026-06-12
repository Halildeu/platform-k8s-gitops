# RB-22-6 — Remote-Bridge Red-Team Drill Runbook (ADR-0034 §11/D10-11)

> **Amaç:** ADR-0034 §11/D10'un **11. maddesi** (red-team drill report) için senaryo
> matrisi + pass/fail kriterleri. Her senaryonun **design-time otomatik test kanıtı**
> (merged) listelenir; bunların üstüne **pilot-ortamı CANLI drill** adımı eklenir.
> İkisi birden yeşil olmadan ilgili D10 maddesi pilot-complete sayılmaz.
> **Status:** senaryo matrisi HAZIR (design-time kanıtlar merged); CANLI drill koşumu
> **Faz B ön-şartı** (T-4 wiring + 11/11 D10 + DPO/Hukuk imzası sonrası — bkz.
> [pilot-flip runbook](RB-22-6-remote-bridge-pilot-flip.md) §B0).
> **Bu runbook'u CANLI koşmak owner kararıdır** (exposure + saldırı simülasyonu).
> **Referans:** [ADR-0034 §11/D10](adr/0034-1388-sensitive-endpoint-ops-owner-decision.md) ·
> [ADR-0033 §7/§10 threat model](adr/0033-faz-22-6-remote-access-bridge-broker.md) ·
> [acceptance package §11.4 kanıt haritası](faz-22-6-1388-acceptance-package.md)

---

## 0. Drill prensipleri

- **İki katman:** her senaryonun (a) **design-time** kanıtı bir otomatik testtir (CI'da
  her PR'da koşar — regression guard); (b) **live** kanıtı pilot broker'ında elle
  tetiklenen bir saldırıdır. Design-time yeşil ≠ live yeşil; ikisi ayrı kapı (D29-EA
  disiplini: Up ≠ Functional ≠ Secured).
- **Fail-closed beklentisi:** her saldırının doğru sonucu **reddedilme / kill / no-permit**'tir.
  Bir saldırı "çalışırsa" (permit alındı / session ayakta kaldı / handshake geçti) drill
  FAIL — pilot BLOCKED, kök neden düzeltilene kadar.
- **Kanıt toplama:** her live drill için broker log + audit hash-chain kaydı + (varsa)
  metrik (KILL latency, DENIED count) arşivlenir; acceptance package §11.3'e işlenir.
- **İzolasyon:** live drill yalnız pilot test cihazları + pilot broker'ında; gerçek
  endpoint'lere saldırı YASAK. Test persona kullanılır (kullanıcı login user'ı değil).

---

## 1. Broker-compromise simülasyonu (D10-11 #1, threat: ADR-0033 §7 G7)

**Saldırı modeli:** broker process'i ele geçirilmiş varsayılır — saldırgan broker'dan
sahte permit basmaya, audit'i bozmaya, recorder'ı atlamaya çalışır.

| Katman | Kanıt / adım | Beklenen |
|---|---|---|
| Design-time | `RemoteBridgePermitSignerTest.aDifferentKeyDoesNotVerifyAndATamperedFieldIsRejected` | Asimetrik anahtar: agent yalnız broker-public ile doğrulanan permit'i kabul eder; **başka** bir anahtarla (compromised endpoint / foreign signer) imzalanan veya signed-field'ı oynanan permit reddedilir. (NOT: broker process'i **signing authority ile** ele geçirilirse permit mint edebilir — o senaryonun mitigasyonu out-of-band audit + recorder-before-permit + key custody (HSM/KMS, no-shell image) + live drill'dir, tek başına bu test değil) |
| Design-time | `RemoteBridgeBrokerTest.aRecordingFailureBlocksPermitIssuanceButNotAKill` | Recorder atlatılırsa permit BASILMAZ (durable-record-before-permit) |
| Design-time | Out-of-band audit (D10-2): hash-chain anchor signer/verifier — broker compromise altında integrity doğrulanabilir | Audit zinciri broker'dan bağımsız doğrulanır |
| **Live** | Pilot broker pod'una exec → signing key custody'sini test et (no-shell/distroless image + exec RBAC-deny + key HSM/KMS-backed VEYA secret-as-file değil) + sahte audit event enjekte et | Key process-dışı custody ile sızılamaz / shell yok; enjekte audit hash-chain'i kırar → out-of-band verifier yakalar |

**Fail sinyali:** agent broker-forged permit'i kabul ederse · recorder atlanıp permit basılırsa · audit tampering hash-chain'de yakalanmazsa.

## 2. jti replay + atomic single-use (D10-11 #2, D10-4)

**Saldırı modeli:** saldırgan geçerli bir session token'ı (jti) yakalar, aynı jti'yi
tekrar kullanmaya / eşzamanlı iki yerde consume etmeye çalışır.

| Katman | Kanıt / adım | Beklenen |
|---|---|---|
| Design-time | `DbCasTokenLifecycleStorePostgresIntegrationTest.consumeAcceptsOnceThenReplayDenied` · `RemoteSessionNegativeTest.replayedTokenIsDenied` · `TokenLifecycleStoreTest.firstConsumeAcceptedThenReplayDenied` | İlk consume kabul, replay deny |
| Design-time | `TokenLifecycleStoreTest.concurrentConsumeOfSameJtiAcceptsExactlyOnce` · `DbCasConcurrencyPostgresIntegrationTest.conflictConsumeAcceptsExactlyOnceUnderRealConcurrency` (64-thread DB-CAS) | Gerçek concurrency'de tam-bir-kez kabul |
| Design-time | `DbCasConcurrencyPostgresIntegrationTest.simultaneousConsumeAndRevokeRaceNeverDoubleAcceptsAndRevokeWins` | Consume-vs-revoke yarışında çift-kabul YOK, revoke kazanır |
| Design-time | Permit seq monotonic (`RemoteBridgeConnectServiceTest.controlFrameSeqMustBeStrictlyMonotonicFromZero`) | Eski seq'li permit replay reddedilir |
| **Live** | Pilot oturumda permit'i yakala (mTLS-içi, test harness) → aynı permit'i ikinci kez gönder + iki paralel agent'tan aynı jti consume | İkisi de tam-bir-kez; replay DENIED |

**Fail sinyali:** aynı jti iki kez kabul edilirse · eski-seq permit ikinci kez işlenirse.

## 3. Recorder-down → fail-closed (D10-11 #3, ADR-0034 D3)

**Saldırı modeli:** saldırgan recorder/WORM sink'i düşürür (DoS) ve oturumun
kayıt-olmadan devam etmesini umar.

| Katman | Kanıt / adım | Beklenen |
|---|---|---|
| Design-time | `RemoteBridgeBrokerTest.aRecordingFailureBlocksPermitIssuanceButNotAKill` | Recorder fail → permit YOK (ama KILL yine fırlar — safety > audit) |
| Design-time | `SessionRecorderTest.anchoringAnUnhealthyRecorderIsRefused` | Sağlıksız recorder anchor reddedilir → ACTIVE olamaz |
| Design-time | `BrokerControlPlaneTest.aDownRecorderNeverBlocksTheSafeOutcome` | Recorder down iken consent-denial/local-abort yine işler (fail-safe) |
| **Live** | Pilot oturum ACTIVE iken WORM sink'i durdur → yeni operation iste | `RECORDING_READY` düşer → yeni permit DENIED; mevcut oturum kill veya no-new-permit |

**Fail sinyali:** recorder down iken yeni permit basılırsa · oturum kayıt-olmadan ACTIVE kalırsa.

## 4. Token theft + cert-binding (D10-11 #4, B1.1)

**Saldırı modeli:** saldırgan bir cihazdan token çalar, BAŞKA bir cihaz/cert ile kullanır.

| Katman | Kanıt / adım | Beklenen |
|---|---|---|
| Design-time | `RemoteSessionHeartbeatTest.boundTokenWithMismatchedPresentedThumbprintKills` · `boundTokenWithMissingPresentedThumbprintKills` | Cert-bound token farklı/eksik thumbprint ile → KILL |
| Design-time | `CertBindingStoreTest.consumePinsThumbprintAtomically` · `CertBoundConsumeGateTest.presentedThumbprintIsPinnedAtomicallyWithTheConsume` | Thumbprint consume anında atomik pinlenir (sonradan değiştirilemez) |
| Design-time | `RemoteSessionNegativeTest.certBindingLossBlocksActiveFailClosed` | Oturum-içi cert binding kaybı → ACTIVE fail-closed |
| **Live** | Cihaz-A'nın token'ını cihaz-B'nin client cert'i ile broker'a sun | mTLS peer fingerprint ≠ token-bound thumbprint → KILL; oturum açılmaz |

**Fail sinyali:** çalınan token başka cert ile çalışırsa · binding kaybı oturumu öldürmezse.

## 5. NTP / clock skew (D10-11 #5)

**Saldırı modeli:** saldırgan cihaz saatini kaydırarak expired token/permit/lease'i
"taze" göstermeye çalışır.

| Katman | Kanıt / adım | Beklenen |
|---|---|---|
| Design-time | `OperatorStepUpPolicyTest.clockSkewIsFailClosed` · `corruptedNegativeTimestampsAreFailClosed` | Operator step-up freshness: skew/negatif timestamp fail-closed |
| Design-time | `RemoteSessionNegativeTest.expiredTokenIsDenied` | Expired session token consume reddedilir |
| Design-time | `RemoteSessionRevocationReconcilerTest.pushMeasuresEventVsStoreClockSkew` · `pushNegativeLatencyIsFlaggedNotCounted` | SLO **DB-anchored** (`revoked_at`), event clock'a güvenilmez; negatif latency sayılmaz |
| Design-time | `OperationPermitTest.freshnessIsBoundedByTheIssuedAndExpiryWindow` · `RemoteBridgePermitSignerTest.anExpiredOrWrongKidPermitIsRejected` | Permit freshness penceresi + kid agent-side enforce |
| Design-time | `aZeroOrPastExpiryGrantIsRefusedNeverEscalated` | proto3 default-0 expiry grant'i escalate etmez |
| **Live** | Pilot cihaz saatini +1h/-1h kaydır → expired permit/token sun | Trusted/monotonic clock (broker-side) reddeder; skew TTL'i yenmez |

**Fail sinyali:** saat kaydırarak expired artifact kabul ettirilirse.

> **NOT (D10-3 kalanı):** trusted/monotonic clock kaynağının kendisi (broker-side, NTP'den
> bağımsız) T-4 operasyon işidir; bu drill onu **kanıt-gerektiren** olarak işaretler.

## 6. Key leak / rotation (D10-11 #6, B1.1 PKI lifecycle)

**Saldırı modeli:** permit-signing key veya device-CA key sızar; rotation sonrası eski
key ile imzalı artifact'lar reddedilmeli, CRL revoke yakalanmalı.

| Katman | Kanıt / adım | Beklenen |
|---|---|---|
| Design-time | `RemoteBridgePermitSignerTest.anExpiredOrWrongKidPermitIsRejected` | kid-mismatch (rotation sonrası eski key) → reddedilir |
| Design-time | `CertPathTrustEvaluatorTest.aStaleCrlPastItsNextUpdateIsUnknownFailClosed` · `PkiMaterialParsingTest.aMalformedAnchorIsFailClosed` | CRL stale/malformed anchor → fail-closed (revoke kaçmaz) |
| Design-time | T-2c `RemoteBridgeMtlsTest.aClientFromTheWrongCaFailsTheHandshakeAndNothingReachesTheSeam` | Yanlış-CA (rotation sonrası eski device-CA) → handshake fail |
| **Live** | (a) permit-signing key rotate → eski kid'li permit sun; (b) bir device cert'i CRL'e ekle → o cihazla bağlan | (a) eski-kid reddedilir; (b) revoked cihaz CRL ile yakalanır → KILL |

**Fail sinyali:** rotation sonrası eski-key artifact kabul edilirse · CRL'deki revoked cert geçerse.

## 7. Transport saldırıları (T-2 yüzeyi — D10-1/6/8 takviyesi)

| Senaryo | Design-time kanıt | Live drill | Beklenen |
|---|---|---|---|
| Anonim/cert'siz bağlantı | `RemoteBridgeMtlsTest.aCertlessClientFailsTheHandshakeAndNothingReachesTheSeam` · `RemoteBridgeConnectServiceTest.anonymousControlIsRefusedBeforeAnyPayload` | cert'siz `openssl s_client` | handshake FAIL, seam'e ulaşmaz |
| Agent broker-yetkisi enjekte | `agentCannotSendBrokerOriginatedPayloadsInbound` · `BrokerControlPlaneTest.nonAllowlistedInboundAuditTypesAreRefused` | agent'tan Kill/Permit/`ALLOW_DECISION` gönder | directional allowlist reddeder |
| KILL latency under DATA saturation | `RemoteBridgeConnectServiceTest.killOnControlLandsSubSecondWhileDataIsSaturated` | DATA stream'i doldur + revoke→kill | KILL CONTROL'de <1s |
| Cross-peer consent/abort | `consentRefusalsAreFailClosed` (wrong-peer) · `aForeignPeerCannotLocalAbortAnotherDevicesSession` | cihaz-B, cihaz-A'nın session'ına consent/abort | wrong-peer reddedilir |
| Capability escalation | `RemoteOperationGuardTest.aNonPilotCapabilityIsRefusedUnderPilotStrictnessEvenIfGranted` · `controlPayloadOnTheDataStreamIsRefused` | pilot-dışı capability/operation iste | default-deny |

## 7b. Oracle / enumeration / retry-DoS (D10-11 ↔ D10-4 + ADR-0033 §10)

**Saldırı modeli:** saldırgan farklı DENY sebeplerinden bilgi sızdırmaya (oracle),
geçerli id'leri saymaya (enumeration) veya retry ile servisi yormaya (DoS) çalışır.

| Katman | Kanıt / adım | Beklenen |
|---|---|---|
| Design-time | `RemoteSessionNegativeTest.everyDenyReasonCollapsesToUniformClientDenied` | Tüm deny sebepleri tek tip `DENIED`'e çöker — sebep sızmaz (oracle yok) |
| Design-time | `RemoteAccessRateLimiterTest.sessionAxisThrottles` · `operatorAxisThrottlesEvenWithFreshNetworkAndSession` · `networkAxisThrottlesAcrossDifferentOperators` | Katmanlı rate-limit (session/operator/network ekseni) — retry-DoS + enumeration sınırlı |
| **Live** | Pilot broker'a farklı-sebep DENY senaryoları + yüksek-hız retry gönder | Yanıtlar tek-tip/sabit-zamanlı; rate-limit tetiklenir; timing/enum oracle yok |

**Fail sinyali:** DENY sebepleri ayrışırsa (oracle) · rate-limit tetiklenmezse · timing farkı id sızdırırsa.

## 8. Coercion / endpoint-user UX (D10-11 ↔ D10-6/7)

| Senaryo | Design-time kanıt | Live drill | Beklenen |
|---|---|---|---|
| Local abort her zaman kazanır | `ConsentLeaseTest.aLocalAbortKillsTheLeaseEvenWithinTheWindow` · `BrokerControlPlaneTest.localAbortAbortsTheLeaseAndKillsTheSession` | oturum ortasında endpoint user abort | ≤5s graceful kill |
| Indicator kaybı = abort | `BrokerControlPlaneTest.indicatorLossAbortsTheLeaseAndKillsLikeALocalAbort` | indicator'ı zorla kapat | session kill (kullanıcı görmüyorsa devam etmez) |
| Approver ≠ requester | engine anti-coercion invariant (maker≠checker) | requester kendi oturumunu onaylamaya çalış | self-approval DENIED |

---

## 9. Drill raporu şablonu (her CANLI koşumdan sonra doldurulur)

```
Drill tarihi: ____  ·  Pilot broker: ____  ·  Operatör (test persona): ____
| # | Senaryo | Design-time (CI) | Live sonuç | Kanıt (log/audit/metric ref) |
|---|---------|------------------|------------|------------------------------|
| 1 | Broker-compromise | PASS | ____ | ____ |
| 2 | jti replay | PASS | ____ | ____ |
| 3 | Recorder-down | PASS | ____ | ____ |
| 4 | Token theft | PASS | ____ | ____ |
| 5 | Clock skew | PASS | ____ | ____ |
| 6 | Key rotation | PASS | ____ | ____ |
| 7 | Transport | PASS | ____ | ____ |
| 7b | Oracle / enum / retry-DoS | PASS | ____ | ____ |
| 8 | Coercion UX | PASS | ____ | ____ |
Genel verdict: [ ] 9 satırın tümü PASS → D10-11 live-complete  ·  [ ] FAIL (#__) → pilot BLOCKED, kök neden: ____
```

> **D10-11 kapanışı:** yukarıdaki kategorilerin **hem design-time hem live** kolonu PASS
> olduğunda **D10-11** (drill report maddesi) item-level yeşil; sonuç acceptance package
> §11.4 haritasına işlenir. Herhangi bir FAIL → pilot BLOCKED.
>
> **ÖNEMLİ — drill ≠ tüm gate:** Bu runbook D10-11'i (drill raporu) kapatır; D10'un
> **diğer 10 maddesi AYRI bloklardır**. Özellikle bu drill'in dokunduğu ama
> KAPATMADIĞI iki madde: **D10-4** (uniform constant-time `DENIED` + layered rate-limit —
> §7b drill *kanıt* üretir ama maddenin kendi acceptance'ı ayrı) ve **D10-9** (operator-channel
> hardening: FIDO2/CSRF/nonce/no-bearer/re-auth — operator console T-4'te, bu drill kapsamı
> DIŞINDA). 9 drill satırının tümü PASS olsa bile **D10 11/11 yeşil olmadan pilot BLOCKED**
> (ADR-0034 §11: "pilot BLOCKED without each").
