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
- **Docs truth closure**: Canlı gerçek değiştiyse, sonraki karar öncesi canonical dokümanlarda drift notu bırakılır.
- **Board canonical (aktif iş)**: Aktif iş durumu, açık risk/issue, milestone/gate `Status`'ü [platform Roadmap board](https://github.com/users/Halildeu/projects/2) (Project #2)'da canonical. Agent oturum başında board'u okur + uygun işi claim eder (`scripts/board-sync.sh`); çalışırken `In Progress` + kanıt comment'i; bitince acceptance sonrası deliberate close → `Done`. Executable iş **gerçek issue** olur (draft item değil). PR-merge runtime issue'yu otomatik `Done` yapmaz — runtime issue'da `Tracked by #N` kullanılır, `Closes/Fixes/Resolves` değil. İş sırasında keşfedilen scope-dışı iş/sorun `board-sync.sh backlog-add` ile `Backlog` statüsünde yakalanır (kaybolmaz; triage'da `Todo` olur) — ephemeral `spawn_task` chip tek başına yetmez. Protokol: [docs/board-protocol.md](./docs/board-protocol.md).

## 4. Çalışma Disiplini

- Canlı ortam değişikliği öncesi hedef, kanıt ve rollback etkisi net yazılır.
- README ve index dokümanları yol göstericidir; kural üretmez, canonical kurala referans verir.
- Bir çelişki varsa önce `AGENTS.md` + `docs/context-priority-rules.md`, sonra live evidence, sonra `current-state` izlenir.
