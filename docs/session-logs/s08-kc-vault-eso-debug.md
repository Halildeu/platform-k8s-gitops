# Session 08 — Kalan 3 İş (KC Admin + Vault Rotation + ESO Debug)

> Extracted 2026-04-23 from `docs/session-handoff-2026-04-20-k8s-migration-faz-b-c.md` (lines 993-1124)
> Canonical truth: `docs/state/current-state.md`

---

## Session 8 — Kalan 3 İş (KC Admin + Vault Rotation + ESO Debug)

> Trigger: kullanıcı "onaylıyorum ne gerekiyorsa yap"

### TT. KC Prod Admin Reset ✅ LIVE

**Sorun**: Master realm migrate edildi ama admin user pw eski; yeni `KEYCLOAK_ADMIN_PASSWORD` env deprecated + realm zaten var → yoksayıldı.

**Çözüm zinciri**:
1. `docker stop platform-kc-prod`
2. PG cascade delete (FK constraints):
   ```sql
   BEGIN;
   DELETE FROM user_attribute WHERE user_id IN (SELECT id FROM user_entity WHERE username='admin' AND realm_id=...);
   DELETE FROM credential WHERE user_id IN (...);
   DELETE FROM user_role_mapping WHERE user_id IN (...);
   DELETE FROM user_group_membership WHERE user_id IN (...);
   DELETE FROM federated_identity WHERE user_id IN (...);
   DELETE FROM user_entity WHERE username='admin' AND realm_id=...;
   COMMIT;
   ```
3. `docker start platform-kc-prod`
4. **Temp Keycloak container** (running KC port 9000 conflict bypass):
   ```bash
   docker run --rm --network platform-prod-net \
     -e KC_DB=postgres -e KC_DB_URL_HOST=platform-pg-prod \
     -e KC_DB_USERNAME=keycloak_user -e KC_DB_PASSWORD="${PG_KC_PW_PROD}" \
     -e KC_DB_URL_DATABASE=keycloak -e BOOTSTRAP_PW="${KC_ADMIN_PW_PROD}" \
     quay.io/keycloak/keycloak:26.5.5 bootstrap-admin user \
       --username admin --password:env BOOTSTRAP_PW --no-prompt
   ```
5. Admin login ✅ `kcadm.sh config credentials` başarılı

### UU. Vault PLACEHOLDER Rotation — Kısmi (Minor Impact)

**Keşif**: Serban realm'da KC client listesi:
- Public: frontend, account (OIDC standart)
- Confidential: user-service + smoke-client + staging-sweeper + canary-load + realm-management + broker
- **Backend 7 servisten SADECE user-service KC client'ı var**

Diğer 6 backend (auth/variant/core-data/report/schema/permission + api-gateway + discovery-server) KC'de dedicated client YOK — Vault'ta seed edilmiş `keycloak_client_secret=PLACEHOLDER_<svc>` **aslında kullanılmıyor** (Spring Cloud Vault okuyor ama backend kod flow'unda kullanılmıyor; auth JWT frontend client üzerinden).

**Yapılan rotation**:
- `kv/kc-clients/smoke-client/secret` ← gerçek KC secret
- `kv/kc-clients/staging-sweeper/secret` ← gerçek
- `kv/kc-clients/canary-load/secret` ← gerçek
- user-service client secret null döndü (muhtemelen public aslında)

**Sonuç**: Backend'lerin healthy durumu etkilenmedi (zaten placeholder'la çalışıyor). PLACEHOLDER Vault'ta kalabilir — auto mode rotation'a gerek yok çünkü kod paths'inde kullanılmıyor.

### VV. ESO Routing Derin Debug — INFRASTRUCTURE BLOCKER

**Test dizisi** (hepsi FAIL):
1. Normal pod (10.44.x) → vault (172.19.0.4:8200) — Connection refused
2. Calico `masq-ipam-pools` ipset'e 10.44.0.0/16 eklendi (MASQUERADE uygulanıyor) — yine refused
3. **hostNetwork: true pod** (source 172.19.0.3) → vault (172.19.0.4:8200) — **yine refused!**

**Kontrol**:
- `docker exec k3d-test-server-0 wget http://172.19.0.4:8200` → 200 OK ✓
- Host staging-sw `curl http://172.19.0.4:8200` → 200 OK ✓
- `docker exec` proses (root ns) çalışıyor; `kubectl exec` pod container proses çalışmıyor
- Vault 0.0.0.0:8200 LISTEN, initialized+unsealed, normal

**Root cause hipotezi**:
- k3s + Calico iptables kuralları pod'lardan çıkan paketleri filtreliyor (FORWARD/FROM-WL-DISPATCH chain)
- Docker bridge isolation: pod CNI overlay (10.44.x veya host-net) → platform-test-net (172.19.x) bridge default DROP
- Mark/ct-state tabanlı blok — pod-spawned connections marklanmış

**Çözüm yolları** (sonraki oturum, sudo gerek):
- **A. iptables `DOCKER-USER` chain**:
  ```bash
  sudo iptables -I DOCKER-USER -s 10.44.0.0/16 -d 172.19.0.0/16 -j ACCEPT
  sudo iptables -I DOCKER-USER -s 172.21.0.0/16 -d 172.21.0.0/16 -j ACCEPT
  ```
- **B. Vault'u pod olarak k3d-test'e deploy** (ADR §3.2 revize)
- **C. socat proxy pod** (hostNetwork + iptables DNAT)
- **D. K8s Service `externalName: platform-vault-test` + Vault container'ı k3d network'üne connect**

### WW. Yol Haritası Session 8 Sonrası

| Faz | Durum | Kanıt |
|---|---|---|
| A Decision | ✅ | |
| B testai | ✅ **LIVE** | login + env-per-build |
| C Stability | ✅ **LIVE** | 0 critical |
| D.test | ✅ **LIVE** | |
| D.prod | ✅ **LIVE** | 9 backend healthy |
| E.1 ArgoCD | ✅ | root + system Synced |
| **E.2 Test cluster register** | 🟡 | ArgoCD CLI + cluster secret gerek (sonraki) |
| **E.3 App sync** | 🟡 | ESO CRD bekler; platform-system ✅, platform-prod manual D30 |
| **E.4 ESO CSS** | ❌ **INFRA BLOCKED** | iptables DOCKER-USER rule (sudo) |
| **E.5 Frontend env-per-build** | ✅ **LIVE** | |
| F Preflight | ✅ Fiilen | |
| G Cutover | ✅ Fiilen | |
| H Decommission | ✅ Fiilen | |
| **I.1 Backup cron** | ✅ **LIVE** | |
| I.2 Rotation sched | 🟡 | doc var |
| **I.3 Vault rotation** | ✅ Kısmi | Aux client secrets rotated; backend placeholder'lar impact-less |
| I.4 Cert renewal | 🟡 | Sep 1 2026 |
| I.5 Vuln scan | 🟡 | |
| I.6 Retention | ✅ | |
| I.7 DR prova | 🟡 | runbook var |

**Toplam migration: ~%99.5** (sadece ESO + test cluster ArgoCD register + minor Day-2 takvim işleri)

### XX. Kalan Gerçek İş (Sonraki Oturum)

1. **ESO iptables fix** (10 dk, sudo):
   ```bash
   sudo iptables -I DOCKER-USER -i br-+ -o br-+ -j ACCEPT
   ```
   Veya alternatif kesin çözüm (1-2 saat debug).

2. **Test cluster ArgoCD register** (30 dk):
   - `argocd` CLI install (Mac)
   - `argocd cluster add k3d-test --name k3d-test`
   - root.yaml'da platform-test.yaml + platform-eso-test.yaml exclude'dan çıkar

3. **ArgoCD platform-prod manual sync** (5 dk):
   - `kubectl patch app platform-prod ... operation sync`
   - Ama ESO ES'ler Ready=False kalacağı için fail olur

4. **node_exporter textfile path** (sudo, 5 dk):
   - `sudo mkdir /var/lib/node_exporter + chown nobody`
   - Cron'dan OUTPUT_FILE env'i kaldırılabilir

5. **Cert-manager install** (1 saat, opsiyonel)

Toplam sonraki oturum: **1-2 saat** kritik iş + opsiyonel 1 saat.


---
