# Policy — Alphanumeric Password (Geçici)

> **Belge tipi**: Policy (geçici, S2 root-cause fix sonrası gevşetilir)
> **Scope**: Vault `kv/platform/*` altındaki `db_password` / benzeri credential alanları
> **İlgili initiative**: PERF-INIT-V2 (PMD §4.1 PR-S1)
> **Replaces**: yok (yeni)
> **Replaced by**: PR-S2 sonrası genişletilmiş policy

---

## 1. Politika

Aşağıdaki şartları sağlamayan password Vault'a yazılmaz / mevcut password rotate edilir:

- Sadece `A-Z`, `a-z`, `0-9` karakterlerinden oluşur
- Minimum **24 karakter** entropi
- Tek bir Vault path için (örn. `kv/platform/report-service`) tek password — birden çok servis tarafından paylaşılan user (`platform`) için **tek bir canonical** değer

**Yasak karakterler** (Spring/Hibernate/YAML/bash quoting çakışmalarına neden olur):

| Karakter | Çakışma kaynağı |
|---|---|
| `$` | Spring `${...}` placeholder parser, bash variable expansion |
| `{` `}` | Spring placeholder, JSON parsing |
| `\` | YAML escape, shell escape |
| `"` `'` | YAML/JSON/shell quoting |
| `:` | YAML key separator, JDBC URL separator |
| `/` `\` | URL path separator |
| `@` | JDBC URL `user@host` parser |
| `#` | Comment marker |
| `?` `&` `=` | URL query string parser |
| `<` `>` | XML/HTML/shell redirect |
| `|` `;` | Shell pipe/separator |
| space `\t` `\n` | YAML/JSON parsing, shell args |
| Unicode `>U+007F` | UTF-8 encoding tutarsızlıkları |

---

## 2. Generate komutu

Operator tarafından kullanılacak canonical generator:

```bash
# 48-char alphanumeric (yüksek entropi, Vault standart)
openssl rand -base64 64 | tr -d '/+=' | head -c 48
```

Veya `pwgen` ile:

```bash
pwgen -s -y 48 1 | tr -dc 'A-Za-z0-9' | head -c 48
```

---

## 3. Rotation prosedürü

```bash
# 1. Yeni password üret
NEW_PASS="$(openssl rand -base64 64 | tr -d '/+=' | head -c 48)"

# 2. Vault'a patch
docker exec -e VAULT_TOKEN="${VAULT_TOKEN}" platform-vault-test \
  vault kv patch kv/platform/<service> db_password="${NEW_PASS}"

# 3. PG + ESO + pod rotate
bash scripts/ops/rotate-pg-vault-user.sh <service> --cluster k3d-test
```

`scripts/ops/rotate-pg-vault-user.sh` Step 2'de alphanumeric check fail olursa exit 3; manuel rotate gerek.

---

## 4. Neden bu policy geçici?

Bu policy **workaround**. Root-cause `platform-backend` repo'da Spring config fix ile çözülür (PR-S2 paralel iz):

- `application-k8s.yml` içinde `SPRING_DATASOURCE_PASSWORD` ayrı env var; JDBC URL'de password gömme yok
- ESO template'lerinde `${...}` escape (`$$`) syntax
- Helm/kustomize placeholder collision audit
- Password validation Spring boot bootstrap'ta (URL-safe + percent-encoding)

PR-S2 merged + her servise uygulandıktan sonra özel karakter destek tekrar etkinleştirilebilir. O zaman bu policy şuna evrilir:

- URL-safe percent-encoding zorunlu
- Vault'ta plain text (encoded değil)
- ESO template encode-on-render

Geçiş tarihi: PR-S2 tüm 8 servise uygulanıp regression smoke geçtikten sonra.

---

## 5. Mevcut Vault entries audit

`scripts/ops/rotate-pg-vault-user.sh` her çağrıldığında Vault'taki password'ün alphanumeric olduğunu doğrular. Audit log:

- Pass: `~/.claude/logs/pg-vault-rotation.log` "alphanumeric OK"
- Fail: `exit 3` + policy violation log + operator manual rotate

Periyodik audit (CronJob drift detector — PR-S1.b/conditional sonraki PR):

```bash
for svc in $(docker exec -e VAULT_TOKEN platform-vault-test vault kv list -format=json kv/platform | jq -r '.[]'); do
  PW=$(docker exec -e VAULT_TOKEN platform-vault-test \
    vault kv get -mount=kv -format=json "platform/${svc}" \
    | jq -r '.data.data.db_password // empty')
  if [[ -n "${PW}" && ! "${PW}" =~ ^[A-Za-z0-9]+$ ]]; then
    echo "POLICY VIOLATION: kv/platform/${svc} contains non-alphanumeric password"
  fi
done
```

---

## 6. İstisnalar

Aşağıdaki Vault path'leri bu policy'den **muaf**:

- `kv/platform/keycloak/smoke-client` — bearer token (zaten URL-safe base64)
- `kv/gitops/ghcr-token` — GitHub PAT (kendi formatı)
- `kv/platform/openfga` — store/model ID (UUID + plain string mix)
- `kv/platform/alertmanager-fallback` — SMTP/Slack webhook URL'leri

Bu alanlar Spring placeholder veya JDBC URL'de kullanılmaz; başka istemcilerin format kuralları geçerli.

---

## 7. İlgili dokümanlar

- `docs/RB-pg-vault-secret-parity.md` — recovery runbook
- `scripts/ops/rotate-pg-vault-user.sh` — policy enforcement script
- `docs/performance/PERF-INIT-V2-plan.md` PR-S1, PR-S2
- ADR-0010 §2.5 — credential boundary
