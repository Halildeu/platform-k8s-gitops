# RB-gh-cli-auth-and-pr – GH CLI Token Auth + PR Create (Kopyasız)

ID: RB-gh-cli-auth-and-pr  
Service: github-cli  
Status: Draft  
Owner: @team/platform

-------------------------------------------------------------------------------
1. AMAÇ
-------------------------------------------------------------------------------

GitHub PR açma işlemini kopyalama yapmadan CLI üzerinden çalıştırmak:
- `gh auth login` (token ile, non-interactive)
- `gh pr create` (body-file ile)

-------------------------------------------------------------------------------
2. KAPSAM
-------------------------------------------------------------------------------

- Host: `github.com`
- Tooling: `gh` CLI
- Token scope minimumu:
  - `repo`, `read:org`, `gist`
- Script’ler:
  - `scripts/ops/gh_auth_with_token.sh`
  - `scripts/ops/gh_pr_create_from_body.sh`

-------------------------------------------------------------------------------
3. BAŞLATMA / DURDURMA
-------------------------------------------------------------------------------

### 3.1 Auth (Token ile, kopyasız)

Token kaynağı önceliği:
1) Env: `GH_TOKEN` (session only)
2) Env: `GITHUB_TOKEN`
3) macOS Keychain: service=`github.com`, account=`$USER`
4) Vault KV v2 (opsiyonel): `GH_AUTH_VAULT_PATH` + `GH_AUTH_VAULT_FIELD`

Komut:
- `bash scripts/ops/gh_auth_with_token.sh`

Keychain’e kaydet (interactive) + login:
- `bash scripts/ops/gh_auth_with_token.sh --store-keychain`

Vault (KV v2) ile (kopyasız) login:
- `export GH_AUTH_VAULT_PATH="secret/stage/ops/github"`
- `export GH_AUTH_VAULT_FIELD="GH_TOKEN"` (veya kurumunuzdaki field adı)
- `bash scripts/ops/gh_auth_with_token.sh`

### 3.2 PR Create (body-file ile)

Body dosyası hazırla:
- `/tmp/pr_body.md`

PR aç:
- `bash scripts/ops/gh_pr_create_from_body.sh --repo Halildeu/platform-ssot --base main --head <branch> --title "<title>" --body-file /tmp/pr_body.md`

### 3.3 Logout (opsiyonel)

- `gh auth logout --hostname github.com`

-------------------------------------------------------------------------------
4. GÖZLEMLEME / LOG / METRİKLER
-------------------------------------------------------------------------------

- Auth doğrulama:
  - `bash scripts/ops/gh_token_preflight.sh`
  - (alternatif) `gh api rate_limit`
  - Not: `gh auth status` “not logged in” görünebilir; bu tek başına hata değildir.
- PR doğrulama:
  - `gh pr view --repo <owner/repo> --head <branch>`
  - `gh pr list --repo <owner/repo> --head <branch>`
- Lokal kanıt (gate):
  - `.autopilot-tmp/execution-log/execution-log.md`

-------------------------------------------------------------------------------
5. ARIZA DURUMLARI VE ADIMLAR
-------------------------------------------------------------------------------

- [ ] Arıza senaryosu 1 – Token bulunamadı:
  - Given: `GH_TOKEN/GITHUB_TOKEN` set değil ve Keychain entry yok  
    When: `bash scripts/ops/gh_auth_with_token.sh`  
    Then: Script fail eder → çözüm:
    - `export GH_TOKEN="..."` (session) veya
    - `bash scripts/ops/gh_auth_with_token.sh --store-keychain`
    - (Vault) `export GH_AUTH_VAULT_PATH=... GH_AUTH_VAULT_FIELD=...` + `bash scripts/ops/gh_auth_with_token.sh`

- [ ] Arıza senaryosu 2 – gh authenticated değil:
  - Given: `bash scripts/ops/gh_token_preflight.sh` FAIL (veya `gh api rate_limit` FAIL)  
    When: `bash scripts/ops/gh_pr_create_from_body.sh ...`  
    Then: PR açılmaz → önce auth:
    - `bash scripts/ops/gh_auth_with_token.sh` (persist login) veya
    - `export GH_TOKEN=...` / Vault pointer set ederek `bash scripts/ops/gh_token_preflight.sh` PASS

- [ ] Arıza senaryosu 3 – PR zaten var:
  - Given: aynı `--head <branch>` için açık PR vardır  
    When: `bash scripts/ops/gh_pr_create_from_body.sh ...`  
    Then: Script mevcut PR URL’ini yazıp exit 0 döner.

-------------------------------------------------------------------------------
6. ÖZET
-------------------------------------------------------------------------------

- Token asla echo/print/loglanmaz; sadece stdin ile `gh auth login --with-token` komutuna verilir.
- PR `--body-file` ile açılır; token yoksa UI fallback kullanılır.

-------------------------------------------------------------------------------
7. LİNKLER (İSTEĞE BAĞLI)
-------------------------------------------------------------------------------

- Template: `docs/99-templates/RUNBOOK.template.md`
- Script: `scripts/ops/gh_auth_with_token.sh`
- Script: `scripts/ops/gh_pr_create_from_body.sh`
- Compare (örnek): `https://github.com/Halildeu/platform-ssot/compare/main...docs/guides-migration-v0.1?expand=1`
