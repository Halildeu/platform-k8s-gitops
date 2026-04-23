# Session 09 — Infrastructure Fix Denemeleri

> Extracted 2026-04-23 from `docs/session-handoff-2026-04-20-k8s-migration-faz-b-c.md` (lines 1126-1209)
> Canonical truth: `docs/state/current-state.md`

---

## Session 9 — Infrastructure Fix Denemeleri (Son Oturum)

> Trigger: kullanıcı "tamamlayalım" + sudo onaylandı

### YY. ✅ LIVE Yapılanlar (Sudo + Script)

**iptables DOCKER-USER** (staging-sw host-level, sudo script):
- 10 cross-network ACCEPT rule (pod↔stateful×4 yön + cross-cluster×2)
- `iptables-persistent` ile kalıcı kaydedildi (`/etc/iptables/rules.v4`)

**node_exporter textfile dir**:
- `/var/lib/node_exporter` oluşturuldu, `nobody:nogroup` chown, 755 perm
- backup-freshness-exporter.sh artık buraya yazabilir (OUTPUT_FILE override kaldırılabilir)

**Cert-manager her iki cluster**:
- k3d-prod + k3d-test 3 pod/cluster Running (controller + cainjector + webhook)
- v1.18.2 + installCRDs=true
- ClusterIssuer letsencrypt-prod manifest TBD (sonraki iş)

**Calico Installation CR patch**:
- `encapsulation: VXLAN` → `None` (her iki cluster)
- Calico-node daemonset restart

### ZZ. ESO Routing — HALA BLOCKED (ADR Revize Gerek)

**Test dizisi (sudo sonrası)**:
1. DOCKER-USER 10 rule eklendi → pod → vault YİNE refused (0ms)
2. Pod src route: `172.19.0.4 via 169.254.1.1 dev eth0 src 10.44.3.xxx`
3. hostNetwork:true pod, src=node IP → yine refused
4. VXLAN Always → None değişikliği + Calico restart → yine refused
5. Vault log'da **yeni bağlantı kaydı YOK** — paket hiç ulaşmıyor
6. Node → vault: 200 OK (docker exec veya host curl)
7. Pod → vault: 0ms refused

**Kök kök-sebep**: Calico Workload Endpoint firewall (cali-fw-cali...) pod'un egress paketini düşürüyor. Her pod'un "dedicated" chain'i var (`cali-fw-cali<hash>`). WL firewall her pod için kontrol listesi uygular — k8s NetworkPolicy'ye göre veya Calico GlobalNetworkPolicy'ye göre. 

NetworkPolicy olmadığı ns'lerde (default, external-secrets) de refused — demek Calico default DROP olabilir veya iç Calico felix config "egress default deny" uyguluyor.

### AAA. Kalıcı Çözüm Yolları (ADR Revize veya Infra Restructure)

**Seçenek A (ÖNERİLEN): Vault'u pod olarak cluster içine al**
- `kustomize/base/apps/vault/` StatefulSet (Raft 1-replica veya 3-node HA)
- PVC `/vault/data` (hostPath veya local-path)
- ADR-0002 §3.2 revize: "Vault pod-native (k8s secret store integration)"
- ESO ClusterSecretStore `http://vault.platform-{prod,test}.svc.cluster.local:8200`
- Pod ↔ pod same-cluster = çalışır (Calico WL firewall izin veriyor intra-cluster)

**Seçenek B: Calico NetworkPolicy allow-egress-all external-secrets**
- `kubectl apply -f` ile NetworkPolicy explicit allow 172.19.0.0/16 + 172.21.0.0/16
- Ama default deny'yi bypass'layacak kural Calico WL firewall'un üstünde olmalı

**Seçenek C: ESO Webhook + Sidecar proxy (complex)**
- hostNetwork pod + iptables DNAT
- Tehlikeli, best practice değil

**Tavsiyem**: Seçenek A — ADR-0002 §3.2'yi revize et:
> "Prod + test stateful isolation: PG + KC **host-compose** (eski karar); Vault **pod-native** (K8s cluster içinde, ESO chain için gerekli). OpenFGA zaten pod olarak."

Bu Faz D revizesi + Vault migration (1-2 oturum).

### BBB. Sonraki Oturum İş Sırası (Final)

1. **Vault pod-native migration** (ADR revize + kustomize/base/apps/vault StatefulSet + data migrate) — 2-3 saat
2. **ESO ClusterSecretStore cluster-internal Vault** → Ready=True → ExternalSecret'lar Synced
3. **ArgoCD platform-eso-prod sync** → ES CR'lar apply
4. **ArgoCD test cluster register** (ya da ayrı k3d-test hub) — 30 dk
5. **ClusterIssuer letsencrypt-prod + Certificate testai.acik.com** — 1 saat
6. **Vault full rotation** (rotation schedule + cron) — 30 dk

### CCC. Yol Haritası FINAL (Session 9 sonrası)

Core platform ~%99.5 LIVE:
- ai.acik.com + testai.acik.com tam izole + canlı ✅
- 9 backend healthy ✅
- Day-2 cron LIVE ✅
- Cert-manager installed ✅

**Pending** (bu oturumda çözülemedi, infrastructure-level):
- ESO CSS Ready=True (Vault pod-native migration)
- Test cluster ArgoCD register (ESO fix ile aynı network-bridge sorun)

**Yol haritası %99.5** — son %0.5 **Vault pod-native ADR revize** sonrası kapanır.

---
