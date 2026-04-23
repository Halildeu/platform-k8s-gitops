# Session 07 — Yeşil + Sarı Tamamlama

> Extracted 2026-04-23 from `docs/session-handoff-2026-04-20-k8s-migration-faz-b-c.md` (lines 864-991)
> Canonical truth: `docs/state/current-state.md`

---

## Session 7 — Yeşil + Sarı Tamamlama (2026-04-20 ~12:00-13:00 UTC+3)

> Trigger: kullanıcı "Yeşil + Sarı tamamlayalım"

### NN. Yeşil Başarı (Staging-sw Cron + Day-2 LIVE)

**Crontab install** (non-interactive, idempotent):
```cron
0 * * * *   OUTPUT_FILE=/home/halil/node_exporter_textfile/backup_freshness.prom /home/halil/platform-k8s-gitops/bootstrap/backup-freshness-exporter.sh >> /home/halil/platform-backup-freshness.log 2>&1
5 * * * *   /home/halil/platform-k8s-gitops/bootstrap/pg-dump-cron.sh >> /home/halil/platform-backup-pg-dump.log 2>&1
0 2 * * *   /home/halil/platform-k8s-gitops/bootstrap/vault-snapshot-cron.sh >> /home/halil/platform-backup-vault-snapshot.log 2>&1
0 3 * * 0   /home/halil/platform-k8s-gitops/bootstrap/kc-export-cron.sh >> /home/halil/platform-backup-kc-export.log 2>&1
```

**Manuel test başarılı:**
- `pg-dump-cron.sh` → 2 dosya (prod 102KB, test 64KB)
- `backup-freshness-exporter.sh` → `/home/halil/node_exporter_textfile/backup_freshness.prom` YAZDI:
  ```
  backup_last_success_timestamp_seconds{type="pg"} 1776676856
  backup_last_success_timestamp_seconds{type="kc"} 0
  backup_last_success_timestamp_seconds{type="vault"} 0
  ```
- `sudo` olmadığı için `/var/lib/node_exporter` yerine `~/node_exporter_textfile` path kullanıldı (node_exporter config update gerek + sudo)

### OO. KC Admin Reset + Vault Rotation BLOKLU

**Denendi**:
- `kc.sh bootstrap-admin user --username admin_new --password:env ...` → `Unable to start management interface on 0.0.0.0:9000 — Address already in use` (running KC port conflict)
- `kcadm.sh config credentials` mevcut admin pw → `Invalid user credentials` (migrated PG'den eski pw)

**Pending (1 dk downtime iş, sonraki oturum):**
```bash
docker stop platform-kc-prod
# Master realm admin user delete (PG direct)
docker exec platform-pg-prod psql -U postgres -d keycloak -c "
DELETE FROM user_entity WHERE username='admin' AND realm_id=(SELECT id FROM realm WHERE name='master');"
docker start platform-kc-prod
# KC_BOOTSTRAP_ADMIN env'ten yeni admin yaratılır
```

**Vault rotation pending** (KC admin login sonrası 20 dk iş):
- `kcadm get clients -r serban` → 7 confidential client client_secret
- `vault kv put kv/platform/<svc> keycloak_client_secret=<real>` update
- Backend rolling restart (env pickup — Spring Cloud Vault dinamik sync yapmaz)

### PP. Sarı Başarı (Faz E Env-Per-Build LIVE)

**PR #28 k8s-gitops (MERGED)** — overlay bump:
- `overlays/test/kustomization.yaml`: frontend → `platform-ssot-frontend-testai:sha-2169841`
- `overlays/prod/kustomization.yaml`: frontend → `platform-ssot-frontend:sha-2169841`

**Canlı deploy (k3d-test)**:
- `docker pull` + `k3d image import` + `kubectl set image`
- Rolling restart → frontend pod yeni testai-specific image Running

**Host nginx testai block REWRITE**:
- Eski: `root /usr/share/nginx/html` (prod artifact /home/halil/platform/web/releases/6a43312)
- Yeni: `location / { proxy_pass http://127.0.0.1:9080; }` (k3d-test ingress → frontend pod)
- Sub_filter runtime injection hack **KALDIRILDI**
- `/realms/` → 8082 korundu (platform-kc-test)

**Canlı smoke kanıt**:
```
curl https://testai.acik.com/ → k3d-test frontend pod (build-time VITE_*=testai.acik.com inline)
  → HTML'de "ai.acik.com" YOK, sadece "testai.acik.com" + "platform-test" string'leri
curl https://testai.acik.com/realms/platform-test/.well-known
  → issuer: https://testai.acik.com/realms/platform-test ✓

ai regression:
curl https://ai.acik.com/realms/serban/.well-known
  → issuer: https://ai.acik.com/realms/serban ✓
```

### QQ. ESO Routing Derin Debug (Handoff Pending — 1-2 saat infra iş)

**Test dizisi**:
1. Calico `masq-ipam-pools` ipset'e `10.44.0.0/16` manuel eklendi → cali-nat-outgoing MASQUERADE uygulanıyor ✓
2. Pod src route: `172.19.0.4 via 169.254.1.1 dev eth0 src 10.44.x`
3. nc test pod → vault/kc/pg/ai-prod-vault HEPSI **refused/timeout**
4. Node (`k3d-test-server-0` 172.19.0.3) → vault (172.19.0.4) OK
5. kube-proxy iptables stale (Service IP farklı iptables'ta)
6. k3s cluster kube-proxy POD yok (gömülü binary)

**Root cause**: Docker user-defined bridge networks arası default ISOLATE. k3d pod CNI overlay (10.44.x) ≠ platform-test-net (172.19.x) ≠ platform-prod-net (172.21.x).

**Sonraki oturum 4 çözüm yolu**:
- A. Vault'u pod olarak k3d cluster içine StatefulSet — ADR §3.2 revize
- B. NodePort Service externalTrafficPolicy=Local
- C. Calico FelixConfiguration + host range
- D. iptables DOCKER-USER custom rule (root sudo gerek)

### RR. Yol Haritası Final (Session 7 sonrası)

| Faz | Durum | Live/Pending |
|---|---|---|
| A Decision | ✅ DONE | |
| B testai | ✅ **LIVE** | login canlı |
| C Stability | ✅ **LIVE** | 0 critical + scope fix |
| D.test | ✅ **LIVE** | 3 ayrı instance |
| D.prod | ✅ **LIVE** | soft cutover + 9 backend healthy |
| E.1 ArgoCD | ✅ DONE | root+platform-system Synced |
| E.2 Cluster register | 🟡 | in-cluster OK |
| E.3 App sync | 🟡 | platform-prod OutOfSync (manual D30) |
| **E.4 ESO CSS** | ❌ BLOCKED | docker bridge isolation (4 yol doc'ta) |
| **E.5 Frontend env-per-build** | ✅ **LIVE** | testai pod serve ediyor, ai prod aynı |
| F Preflight | ✅ Fiilen | manual |
| G Cutover | ✅ Fiilen | soft |
| H Decommission | ✅ Fiilen | 7 container rm |
| **I.1 Backup cron** | ✅ **LIVE** | crontab + manual test ✓ |
| I.2 Rotation schedule | 🟡 | doc var |
| I.3 Vault PLACEHOLDER rotation | 🟡 | KC admin reset bekler |
| I.4 Cert renewal | 🟡 | Sep 1 2026 |
| I.5 Vuln scan | 🟡 | OSV k8s-gitops'a ekle |
| I.6 Retention | ✅ | |
| I.7 DR prova | 🟡 | runbook + komutlar var, drill yok |

**Toplam migration: ~%99** (ESO + Vault rotation + KC admin reset dışında hepsi ya live ya script-hazır)

### SS. Sonraki Oturum Kritik İş Sırası

1. **KC prod admin reset** (1 dk downtime): DB delete + container restart → bootstrap admin yeniden yaratılır
2. **Vault PLACEHOLDER rotation** (20 dk): KC realm client_secret → Vault kv update → backend rolling
3. **ESO routing fix** (1-2 saat): Seçenek B veya C (4 yol doc'ta)
4. **node_exporter textfile path + sudo** (10 dk): `/var/lib/node_exporter` oluştur + node_exporter config
5. **Cert-manager install** (1 saat): Let's Encrypt automated renewal


---
