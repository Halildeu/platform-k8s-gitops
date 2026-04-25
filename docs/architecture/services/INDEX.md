# Services Architecture Index

Bu doküman, `docs/02-architecture/services/` altındaki servis dokümanlarının
runtime beklentisini ve plan statüsünü özetler.

Kaynak dosya:
- `docs/02-architecture/services/service-doc-status.v1.json`

## Aktif Runtime Servis Dokümanları

- `api-gateway`
- `auth-service`
- `core-data-service`
- `discovery-server`
- `permission-service`
- `user-service`
- `variant-service`

## Destek / Doküman Servisleri

- `backend-docs`

## Plan-Only Servis Dokümanları

- `approval-system`
- `ethics-case-management`
- `fleet-operations`
- `ops`
- `theme-system`

Not:
- Plan-only servisler mevcut runtime modülüymüş gibi yorumlanmaz.
- `scripts/check_arch_vs_code.py` yalnız `runtime_expected=true` servisleri zorunlu tutar.
