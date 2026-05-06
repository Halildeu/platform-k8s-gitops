# Notify ESO Test Overlay (Faz 23 — Placeholder)

> **Status**: PENDING (Faz 23.1 implementation pending)
> **ADR**: [ADR-0013-notification-orchestration](../../../../docs/adr/0013-notification-orchestration.md)

Bu dizin Faz 23.1 Kernel implementation öncesi **placeholder**. ESO ExternalSecret manifest'leri Faz 23.1 sub-faz'ında Vault path populate sonrası eklenecek.

## Beklenen ExternalSecret'lar (Faz 23.1+)

```
externalsecret-notify-smtp.yaml         # Vault: kv/platform/notify/smtp
externalsecret-notify-slack.yaml        # Vault: kv/platform/notify/slack
externalsecret-notify-webhook.yaml      # Vault: kv/platform/notify/webhook (HMAC secret)
```

## Faz 23.3+ ek ExternalSecret'lar

```
externalsecret-notify-netgsm.yaml       # SMS primary
externalsecret-notify-iletimerkezi.yaml # SMS secondary
externalsecret-notify-fcm.yaml          # Faz 23.7 push
```

## Vault Path Plan

| Path | İçerik | Sub-faz |
|---|---|---|
| `kv/platform/notify/smtp` | host, port, username, password, dkim_key, from_address | 23.1 |
| `kv/platform/notify/slack` | webhook_url, bot_token (opsiyonel) | 23.1 |
| `kv/platform/notify/webhook` | hmac_secret | 23.1 |
| `kv/platform/notify/sms/netgsm` | username, password, msgheader | 23.3.1 |
| `kv/platform/notify/iletimerkezi` | api_username, api_password, sender_id | 23.3 |
| `kv/platform/notify/fcm` | service_account_json | 23.7 |
| `kv/platform/monitoring/fallback` | slack_webhook_url, smtp_user, smtp_password (D43 outage bypass — ayrı path) | 23.2 |

## Activation

1. Ops Vault populate (kullanıcı/operatör — `boundary-cross + credential-write`)
2. ExternalSecret manifest dosyaları bu dizine eklenir
3. `kustomization.yaml` oluşturulur (`resources: [...]`)
4. `kustomize/overlays/test/eso/kustomization.yaml`'a `../eso/notify` reference eklenir
5. `kubectl --context k3d-test apply -k kustomize/overlays/test/eso/notify`

Detay: `docs/runbooks/RB-faz-23-1-kernel-impl-checklist.md` Hafta 1 önkoşul.
