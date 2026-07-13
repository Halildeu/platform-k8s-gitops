# AGENTS.md — platform-k8s-gitops

Bu dosya repo içindeki en yüksek öncelikli giriş yüzeyidir. Yeni bir agent veya oturum bu repoda bağlam toplarken önce bu dosyayı, hemen ardından [docs/context-priority-rules.md](./docs/context-priority-rules.md) dosyasını okur.

## 1. Okuma Sırası

Kural ve öncelik çözümü için:
1. `AGENTS.md`
2. `docs/context-priority-rules.md`

Soru tipine göre otoriter kaynak:
- **Canlı truth / blocker / sayaç**: `docs/state/current-state.md` + mümkünse doğrudan live evidence (`ssh`, `kubectl`, `curl`, `docker`)
- **Aktif mimari karar**: `docs/adr/0002-single-host-dual-cluster.md`
- **Roadmap / faz / done kriteri**: `PLAN.md`
- **Aktif iş durumu / claim / sıradaki iş**: [platform Roadmap board](https://github.com/users/Halildeu/projects/2) (Project #2) — protokol [docs/board-protocol.md](./docs/board-protocol.md)
- **Uygulama adımı / operasyon**: ilgili runbook

Navigator ama karar kaynağı olmayan yüzeyler:
- `README.md`
- `docs/README.md`
- `CLAUDE.md` (agent-özel tamamlayıcı)
- `docs/session-handoff-*.md` ve diğer handoff belgeleri

## 2. Repo Kimliği

- Bu repo `platform-k8s-gitops` için **desired-state ve operasyon repo**'sudur.
- Uygulama kaynak kodu, image build ve runtime artifact üretimi canonical kaynak repo'larda yapılır — backend `platform-backend`, frontend `platform-web`. (`platform-ssot` 2026-04-25'ten beri DEPRECATED, audit-only — HARD RULE.)
- Bu repo bir uygulama feature backlog'u değil; manifest, bootstrap, GitOps, secret delivery, cutover ve runtime governance repo'sudur.

## 3. HARD RULE

- **Live truth > optimistic doc**: Doğrudan canlı kanıt, eski handoff veya iyimser plan cümlesinden üstündür.
- **No closure language**: Kullanıcı açıkça bitirmedikçe "bitti/kapandı/tamamlandı" dili kullanılmaz.
- **D29**: `Up != Functional != Zanzibar-ready`; tek kelimelik "green" yasaktır.
- **D30 immutable artifact**: moving tag kanıt değildir; digest/imageID eşleşmesi gerekir.
- **D30 atomic cutover**: weighted DNS yok; atomic switch + `72h` rollback-window vardır.
- **Test authoritative before prod**: `testai.acik.com` kanıtlanmadan `ai.acik.com` cutover hazır sayılmaz.
- **Faz 24 KVKK legal-track parallelism**: KVKK/VERBIS/hukuk owner acceptance mühendislik completion blocker'ı değildir; owner bildirimi kayda alındıktan sonra mühendislik fail-closed, parametrik retention/consent/deletion kontrolleriyle ilerler. Süreler owner-supplied parametredir; sabit süre, eksik owner kararı veya hukuk track'i mühendislik blocker'ı yapılmaz **yalnız** fail-closed/refuse-to-store default aktifse. Legal acceptance, VERBIS güncelliği veya production legal go yalnız owner/legal kanıtıyla söylenir; agent/CI/PR bunu iddia etmez. Mimari karar tetikleyicileri ve cross-AI + ADR kuralı için canonical kaynak: `ADR-0030` D6.
- **Faz 24 ERP/CRM-agnostic product contract**: Meeting Intelligence belirli bir ERP/CRM markasına göre tasarlanmaz. Belirli marka adları yalnız tarihsel kaynak kanıtı, ilk müşteri pilotu veya adapter örneği olarak anılabilir; ürün adı, API/DTO, UI, acceptance gate, roadmap ve "done" dili vendor-specific olamaz. Yeni entegrasyon işi generic ERP/CRM adapter kontratı üzerinden yazılır ve marka-özel davranış core product contract'a gömülmez.
- **Test overlay GitOps-authoritative (ADR-0023)**: Shared `k3d-test` ana workload'ları (Deployment/StatefulSet) yalnız `kustomize/overlays/test` üzerinden değişir; ana workload'a doğrudan `kubectl set image` / `kubectl patch` / `kubectl edit` **YASAK** (overlay'i fiction'a çevirir). İstisna: `k3d-dev`, ADR-0022 transient smoke workload'ları, dört-koşullu break-glass (gerekçe+board issue + TTL + drift alarm + aynı-incident reconciliation PR). Image-dışı runtime artifact (OpenFGA yetkilendirme modeli vb.) `runtime-artifacts/` ledger'ı ile test→prod evidence-gate'li taşınır.
- **ArgoCD ignoreDifferences disiplini**: `kind: Application` manifest'inde `RespectIgnoreDifferences=true` syncOption ile birlikte **blanket `/metadata`**, `/metadata/managedFields`, ya da `/metadata/annotations`/`/metadata/labels` container'ı ignore etmek **YASAK** — ArgoCD canlı `managedFields`'i SSA gövdesine taşır ve `metadata.managedFields must be nil` ile tüm sync'i bozar. Yalnız targeted runtime field'lar (`/status`, `/spec/replicas`) ve `/metadata/annotations/<specific-key>` / `/metadata/labels/<specific-key>` / `/metadata/finalizers` izinlidir. Detay: [docs/operations/argocd-respect-ignore-diff-antipattern.md](./docs/operations/argocd-respect-ignore-diff-antipattern.md). Codex `019e41d7` / `019e4216`, PR [#850](https://github.com/Halildeu/platform-k8s-gitops/pull/850) + [#851](https://github.com/Halildeu/platform-k8s-gitops/pull/851). CI guard: `gate-argocd-respect-ignore-diff`.
- **Docs truth closure**: Canlı gerçek değiştiyse, sonraki karar öncesi canonical dokümanlarda drift notu bırakılır.
- **Board canonical (aktif iş)**: Aktif iş durumu, açık risk/issue, milestone/gate `Status`'ü [platform Roadmap board](https://github.com/users/Halildeu/projects/2) (Project #2)'da canonical. Agent oturum başında board'u okur + uygun işi claim eder (`scripts/board-sync.sh`); çalışırken `In Progress` + kanıt comment'i; bitince acceptance sonrası deliberate close → `Done`. Executable iş **gerçek issue** olur (draft item değil). PR-merge runtime issue'yu otomatik `Done` yapmaz — runtime issue'da `Tracked by #N` kullanılır, `Closes/Fixes/Resolves` değil. İş sırasında keşfedilen scope-dışı iş/sorun `board-sync.sh backlog-add` ile `Backlog` statüsünde yakalanır (kaybolmaz; triage'da `Todo` olur) — ephemeral `spawn_task` chip tek başına yetmez. **Claim-before-work**: önemli/çok-adımlı iş — kullanıcı ad-hoc atasa bile — çalışmadan önce claimed board issue olmalı (paralel-oturum çakışma guard'ı); oturum-başı ilk komut `board-sync.sh list`; trivial tek-seferlik fix istisna. Protokol: [docs/board-protocol.md](./docs/board-protocol.md).
- **Secret handling boundary**: Prod credential, private key, token, sertifika private material ve güvenlik bilgileri kritik kabul edilir; ham değerleri chat/Mavis/GitHub/repo/log/evidence/shell history içine yazmak YASAK ve prod secret değişikliği açık owner/operator onayı ister. Test/non-prod ortamda agent'lar teslimat için test secret/cert/Vault/ESO değerlerini oluşturabilir, rotate edebilir, seed edebilir ve doğrulayabilir; fakat ham değerleri yine yazdırmaz/yayınlamaz/commit'lemez. Kanıt dili presence/hash/status/secret-store path üzerinden kurulur.
- **Mavis CLI (lokal agent iletişimi)**: Multi-session koordinasyon, paralel agent handoff, tamamlanma bildirimi, async iş zinciri için standart kanal. **3 yol**: Session ID (en kesin) `mvs_<id>` / Agent name (daha portable, session crash'inde persist) `agent-<name>` / `peers` (discovery). Komut: `mavis communication send --to <id|name> --command prompt --content "..."` veya `mavis communication peers`. **Uygulama-penceresi yasağı / CLI-only istişare HARD RULE**: Faz/plan/PR ikinci-görüş ve review işleri hiçbir AI uygulama penceresinden (MiniMax/Mavis/Cursor dahil) yürütülmez. MiniMax/Mavis için yalnız gerçek `mavis` CLI/daemon/provider yolu; Cursor için yalnız CLI veya MCP kullanılır. Gerekli CLI/MCP, daemon veya credential gate hazır değilse UI fallback yapılmaz ve ilgili sağlayıcı istişaresi tamamlandı sayılmaz. **Redaction guard**: `--content` içine secret/JWT/token/webhook URL/cookie/private key/admin credential/PII/raw bearer **YASAK** (shell history, process list, Mavis log/queue, karşı peer transcript'ine düşebilir); gerekirse sadece redacted özet + evidence path/issue/PR linki gönderilir. **Acceptance gate bypass değil**: Mavis bildirimi board claim'ini, live evidence (D29 Up/Functional/Secured), browser smoke kanıtını veya PR/CI truth'u **yerine geçmez** — yalnız koordinasyon kanıtıdır (No Fake Work + Tarayıcıdan Sonuç Doğrulanmadan ile uyumlu). Detay: [CLAUDE.md](./CLAUDE.md) Ana Kurallar #0 + global `~/.claude/CLAUDE.md`.

## 4. Çalışma Disiplini

- Canlı ortam değişikliği öncesi hedef, kanıt ve rollback etkisi net yazılır.
- README ve index dokümanları yol göstericidir; kural üretmez, canonical kurala referans verir.
- Bir çelişki varsa önce `AGENTS.md` + `docs/context-priority-rules.md`, sonra live evidence, sonra `current-state` izlenir.
