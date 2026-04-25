# ADR-0003 – Service To Service HTTP Client Standardization

ID: ADR-0003  
Status: Accepted  
Tarih: 2026-03-05  
Sahip: Halil K.

## Context

- Repo içinde servisler arası HTTP istemcisi tek değildir.
- `auth-service` ve `user-service` içinde `RestTemplate` tabanlı istemciler bulunur.
- `variant-service` içinde `WebClient` tabanlı istemci bulunur.
- Bu ikili yapı timeout, tracing, retry, auth propagation ve test davranışlarını bölmektedir.

Hedef: Bundan sonraki servis geliştirmelerinde tek bir service-to-service HTTP istemci baseline'ı kullanmak.

## Decision

- Yeni veya dokunulan service-to-service HTTP kodunda `WebClient` kullanılacaktır.
- Yeni `RestTemplate` kullanımı eklenmeyecektir.
- Mevcut `RestTemplate` kullanan akışlar kademeli geçiş süresince legacy olarak tutulabilir.
- Bu karar:
  - `auth-service`
  - `user-service`
  - `variant-service`
  - gelecekte eklenecek tüm backend servisleri
  için baseline kabul edilir.

## Consequences

Artılar:
- Tek istemci standardı oluşur.
- Yeni servislerde tracing ve auth propagation davranışı daha öngörülebilir olur.
- Test ve timeout yönetimi daha tutarlı hale gelir.

Eksiler:
- Legacy `RestTemplate` kullanan akışlar bir süre daha taşınmak zorunda kalacaktır.
- Geçiş tamamlanana kadar repo içinde karma model devam eder.

## Linkler

- As-is analiz: `docs/02-architecture/INDEX.md`
- Communication matrix: `docs/02-architecture/runtime/service-communication-matrix.md`
- Stil kuralı: `docs/00-handbook/STYLE-BE-001.md`
- Layout kuralı: `docs/00-handbook/BACKEND-PROJECT-LAYOUT.md`
