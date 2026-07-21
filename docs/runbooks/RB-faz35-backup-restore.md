# RB-faz35-backup-restore — Faz 35 Etik Speak durability drill

**Scope**: ES-309 (nightly backup) + restore rehearsal
**On-call trigger**: monthly rehearsal (owner-scheduled) OR incident-driven full restore
**Duration**: rehearsal ~20 min; incident restore per RTO/RPO 60 min / 24h
**Blast radius**: rehearsal = scratch namespace; incident = production Etik Speak cell

---

## 1. Ön koşullar

- Backup CronJob'ları aktif ve son 24 saatte başarılı: `kubectl -n platform-<env> get cronjob -l app.kubernetes.io/component=backup`
- 3 secret seed edilmiş: `etik-speak-backup-pg`, `etik-speak-backup-openfga`, `etik-speak-backup-vault`
- PVC durumu Bound: `kubectl -n platform-<env> get pvc etik-speak-backup-archive`
- Restore hedef DB rolü hazır (rehearsal için scratch DB ya da recovery için empty schema)

## 2. Durum kontrolü (backup sağlıklı mı?)

```bash
# Son 3 gün CronJob başarıları
kubectl -n platform-test get job -l app.kubernetes.io/component=backup \
  --sort-by=.metadata.creationTimestamp | tail -12

# Arşiv dolu mu?
kubectl -n platform-test debug -it \
  --image=busybox --profile=general --target=etik-speak-pg-dump-<pod> -- \
  ls -lh /archive/pg /archive/openfga /archive/vault
```

**Fail sinyali**: son 24 saat CronJob'ta 0 başarı → panic-alert Alertmanager tetikler
(`EtikSpeakAuditOutboxBacklog` benzeri; ES-311 sonrası `EtikSpeakBackupStale` eklenir).

## 3. Rehearsal restore (scratch namespace, üretim etkisiz)

```bash
kubectl create namespace faz35-rehearsal-$(date +%Y%m%d)
# 3a. PG restore
kubectl -n platform-test cp \
  etik-speak-pg-dump-<latest>:/archive/pg/ethics-<ts>.sql.gz /tmp/pg.sql.gz
gunzip -c /tmp/pg.sql.gz | \
  kubectl -n faz35-rehearsal-<date> exec -i deploy/postgres-rehearsal -- \
  psql -U rehearse -d ethics
# 3b. OpenFGA restore
# İlk store oluştur, sonra authorization-model + tuple pages import
# (script hazır: scripts/faz35-openfga-restore.sh)
# 3c. Vault snapshot restore (yalnız DR — canlı vault etkilenir; scratch cluster'da test)
vault operator raft snapshot restore /tmp/vault-raft-<ts>.snap
```

**Kabul kriteri**: restore edilen namespace'te tek reporter POST'u yapıldığında
201 alınır, receipt UUID döner, mailbox login çalışır. Bu smoke rehearsal
kanıtıdır — [`docs/faz-35-evidence/`] altına tarih-damgalı yazılır.

## 4. Incident restore (production)

**Owner-gated** — bu adımı tetiklemek için ES-311 imzalı runbook'ta belirtilen
on-call engineer (Reveal Officer + Business Owner iki-göz onayı) gerekir.

1. Trafik kesme: `kubectl -n platform-prod patch ingress etik-speak-public-api --type json \
   -p '[{"op":"replace","path":"/spec/rules/0/http/paths/0/backend/service/name","value":"maintenance-503"}]'`
2. Snapshot al (RPO korumak için son PG dump'ı doğrula)
3. RB §3 rehearsal adımlarını **production namespace'e** uygula (`platform-prod`)
4. Smoke doğrulama (RB-faz35-real-reporter-open.md §Adım 3-5)
5. Trafik aç
6. Post-mortem 24 saat içinde `docs/faz-35-evidence/` altına

## 5. Rollback (rehearsal başarısız)

Rehearsal namespace'i sil: `kubectl delete namespace faz35-rehearsal-<date>`.
Production'a hiç dokunulmamıştır.

## 6. Sık karşılaşılan hatalar

| Belirti | Neden | Fix |
|---|---|---|
| `pg_dump: error: connection to server` | ETIK_DB_PASSWORD rotate | `etik-speak-backup-pg` secret yenile |
| Vault snapshot 3KB döner | Vault token expired/policy revoked | Yeni policy = `path "sys/storage/raft/snapshot" { capabilities = ["read"] }` |
| OpenFGA 401 | Store token expired | Yeni store admin token, secret rotate |
| PVC full | Retention yetersiz | CronJob `find -mtime +N` günlerini düşür veya PVC 5Gi→20Gi genişlet |

## 7. Referans

- ES-309 CronJob manifests: `kustomize/base/apps/etik-speak/backup/`
- Prod overlay activation: `kustomize/overlays/prod/activation/etik-speak/kustomization.yaml` (ES-311 gate sonrası)
- Incident-response runbook: `RB-faz35-incident-response.md`
- Legal reveal runbook: `RB-faz35-legal-reveal-request.md`
