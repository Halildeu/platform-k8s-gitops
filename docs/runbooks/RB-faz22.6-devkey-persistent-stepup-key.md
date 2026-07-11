# RB — Faz 22.6 device-key VIEW_ONLY smoke: persistent step-up key (rollout-free)

> **Amaç**: `faz22-6-view-only-attended-smoke.sh`'in broker'ı **rollout-restart etmeden** çalışmasını sağlamak. Codex `019f515c` "C ana durable yol": broker baseline'ında **persistent** step-up public key + smoke matching private key → smoke `find_matching_step_up_private_key_or_generate` **preconfigured-private-key** mode'una girer, `apply_run_scoped_step_up_runtime_env_override` + rollout **hiç çalışmaz**.

## Neden gerekli (kök sorun)

Smoke default `STEP_UP_EPHEMERAL_KEY_ENABLED=1`: her run yeni ephemeral step-up keypair üretir → broker deploy'una `REMOTE_BRIDGE_STEP_UP_PUBLIC_KEY_PEM` patch'ler → **rollout-restart**. Bu:
- Agent'ın device-key stream'ini düşürür (2–5 dk reconnect backoff → `open` fail).
- Dolu node'da (max-pods=50) broker yeni-pod'u sığmayabilir → broker DOWN (2026-07-11 incident).
- Ardışık denemeler deploy'u thrash eder (generation 174), session/consent eşleşmesini bozar.

Persistent key ile bu üçü de **tümden ortadan kalkar** — broker hiç restart olmaz.

## Mekanizma (smoke kodu)

- `export_step_up_public_key` (script ~L638): broker'ın step-up public key'ini secret `endpoint-admin-remote-bridge-secrets`'ten (`REMOTE_BRIDGE_STEP_UP_PUBLIC_KEY_PEM`) okur.
- `candidate_private_keys` (~L645): önce `$STEP_UP_PRIVATE_KEY_PEM_PATH`, sonra sabit adaylar (ör. `/home/runner/remote-bridge-step-up-private-key.pem`, `/home/halil/codex-rb-smoke/keys/operator-step-up-private-key.pem`).
- `find_matching_step_up_private_key_or_generate` (~L658): her aday private'ın public'ini türetip broker public'iyle karşılaştırır. **Eşleşen varsa → `preconfigured-private-key` mode → RETURN (patch/rollout YOK)**. Eşleşme yoksa + ephemeral açıksa → generate + patch + rollout.

Broker (device-key) step-up'ı **kendi** secret'iyle (`endpoint-admin-remote-bridge-secrets-device-key`) doğrular; smoke public'i non-device-key secret'ten okur → **iki secret aynı public key'i taşımalı** (halihazırda eşleşiyor; ikisi de Vault kv `operator_step_up_public_key_pem`'den ESO ile gelir).

## Aktivasyon (tek seferlik, controlled — operator-gated)

> Broker'ın yeni public key'i yüklemesi için **tek bir controlled restart** gerekir (chicken-and-egg). Bu restart node dolu iken thrash-prone; **headroom + eşzamanlı-smoke-yok** ile temiz yap.

```bash
# 0) Ön koşul: eşzamanlı smoke YOK; headroom (gerekirse eski remote-bridge geçici scale-0).
# 1) Persistent EC P-256 keypair üret (staging-sw)
openssl genpkey -algorithm EC -pkeyopt ec_paramgen_curve:P-256 \
  -out /home/runner/remote-bridge-step-up-private-key.pem
chmod 600 /home/runner/remote-bridge-step-up-private-key.pem
PUB=$(openssl pkey -in /home/runner/remote-bridge-step-up-private-key.pem -pubout)

# 2) Public'i Vault kv'ye seed et (HER İKİ kaynak — device-key + non-device-key).
#    NOT (Codex 019f52d7): vault CLI 'key=-' stdin-sentinel'i ortam/sürüm-bağımlı,
#    literal '-' yazma riski taşır -> @file (ambiguity'siz) kullan + seed'i vault kv
#    get ile DOĞRULA. Bozuk key broker'ı fail-closed'a düşürür.
VT=$(jq -r .root_token /home/halil/bootstrap-drill/vault-init-test.json)
PUB_SHA=$(printf '%s' "$PUB" | openssl dgst -sha256 | awk '{print $2}')
for M in endpoint-admin-remote-bridge-device-key endpoint-admin-remote-bridge; do
  printf '%s' "$PUB" | docker exec -i platform-vault-test sh -c 'umask 077; cat > /tmp/subkey.pem'
  docker exec -e VAULT_ADDR=http://127.0.0.1:8200 -e VAULT_TOKEN="$VT" platform-vault-test \
    vault kv patch kv/platform/$M operator_step_up_public_key_pem=@/tmp/subkey.pem
  docker exec platform-vault-test rm -f /tmp/subkey.pem
  GOT=$(docker exec -e VAULT_ADDR=http://127.0.0.1:8200 -e VAULT_TOKEN="$VT" platform-vault-test \
    vault kv get -field=operator_step_up_public_key_pem kv/platform/$M)
  [ "$(printf '%s' "$GOT" | openssl dgst -sha256 | awk '{print $2}')" = "$PUB_SHA" ] \
    || { echo "FAIL: kv/platform/$M seed dogrulanamadi (value != PUB); RESTART ETME"; exit 1; }
done

# 3) ESO force-sync (ExternalSecret adları) + secret'ta taze key DOĞRULA (restart ÖNCESİ)
for ES in endpoint-admin-remote-bridge-secrets-device-key endpoint-admin-remote-bridge-secrets; do
  kubectl --context k3d-test -n platform-test annotate externalsecret "$ES" \
    force-sync="$(date +%s)" --overwrite
done
sleep 10
for S in endpoint-admin-remote-bridge-secrets-device-key endpoint-admin-remote-bridge-secrets; do
  K8S_PUB=$(kubectl --context k3d-test -n platform-test get secret "$S" \
    -o jsonpath='{.data.REMOTE_BRIDGE_STEP_UP_PUBLIC_KEY_PEM}' | base64 -d)
  [ "$(printf '%s' "$K8S_PUB" | openssl dgst -sha256 | awk '{print $2}')" = "$PUB_SHA" ] \
    || { echo "FAIL: secret/$S ESO sync dogrulanamadi (value != PUB); RESTART ETME"; exit 1; }
done

# 4) TEK controlled broker restart (yeni public key yüklenir; ancak 2+3 DOĞRULANDIYSA)
kubectl --context k3d-test -n platform-test rollout restart deploy/endpoint-admin-remote-bridge-device-key
kubectl --context k3d-test -n platform-test rollout status  deploy/endpoint-admin-remote-bridge-device-key --timeout=180s

# 5) Doğrula: smoke artık rollout ETMEMELİ
STEP_UP_EPHEMERAL_KEY_ENABLED=0 \
STEP_UP_PRIVATE_KEY_PEM_PATH=/home/runner/remote-bridge-step-up-private-key.pem \
  bash faz22-6-view-only-attended-smoke.sh
#   → log'da "Waiting for deployment ... rollout" GÖRÜNMEMELİ; step_up_key_mode=preconfigured-private-key.
```

`STEP_UP_EPHEMERAL_KEY_ENABLED=0` verilirse eşleşme yoksa **fail-closed** (`step-up-private-key-unavailable-or-public-mismatch`) — sessizce rollout'a düşmez, yanlış seed'i anında yakalar.

## Durum (2026-07-11)

- **Tasarım + prosedür hazır** (bu runbook). Codex `019f515c` C-onaylı.
- Aktivasyon **operator-gated** (tek controlled restart; sağlıklı proven broker'ı gereksiz restart etmemek için #1580 fully-green kanıtı alındıktan SONRA, ayrı controlled pencerede).
- İlişkili: `scripts/faz22-remote-ops/devkey-cert-autorenew.sh` (cert 24h TTL auto-renew — ayrı durable bridge), memory `faz22-6-devkey-cert-24h-renewal`.

## Kalıcı hedef (bu bridge'in ötesi)

Sektör-standardı (Codex): smoke'un step-up key'i **run-scoped ephemeral + broker rollout** yerine, broker restart hiç gerektirmeyen bir **runtime step-up key rotation API** (broker'a canlı key push, restart'sız). Ayrıca agent-side cert auto-renew (SPIFFE-style). Bunlar ayrı platform-backend/agent feature'ları.
