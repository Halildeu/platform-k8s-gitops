# RB ADR-0011 BG-1 — PR Boundary Declaration Runbook

> **Tetikleyici**: Her açılan/edit'lenen PR.
> **Authority**: PR submitter (agent veya operator) — boundary declaration'ı PR description'a doldurmalı.
> **CI Gate**: `.github/workflows/gate-pr-boundary-declaration.yml` (PR opened/edited/synchronize/labeled/unlabeled trigger).

## Amaç

ADR-0011 §2.3 boundary declaration matrix'i her PR için **zorunlu kılar**. Audit trail: hangi PR ne tip iş yapmış (credential, state mutation, cross-repo) ve user-approval gerekiyor mu — geriye dönük tek satırlık search.

## Boundary classes (ADR-0011 §2.3 + Codex `019dd409` revize)

| Class | Açıklama | User-approval gerekli mi? |
|---|---|---|
| `credential-read` | Vault token / secret / config-map secret okuma | ✅ Evet (Codex 019dd409 added) |
| `credential-write` | Yeni secret yazma / rotate / kv patch | ✅ Evet |
| `state-mutation (test cluster)` | k3d-test cluster state değişimi | ❌ Hayır (Codex consensus + Kural #7) |
| `state-mutation (production)` | k3d-prod cluster state değişimi | ✅ Evet (dual-clearance) |
| `boundary-cross` | Diğer repo'ya yazma (platform-backend, platform-web, vs) | ✅ Evet |
| `none of the above` | Read-only / docs / Codex consensus only | ❌ Hayır (varsayılan agent iş) |

## CI gate semantik (hard fail)

`scripts/governance/check_pr_boundary_declaration.py` 6 check:

1. `boundary_block_present` — exact heading `## Boundary declaration (ADR-0011 §2.3)` var mı
2. `seven_classes_present` — 7 expected class checkbox şablona uygun
3. `at_least_one_marked` — en az bir `[x]` işaret
4. `none_exclusivity` — `none of the above` ile başka class çakışmasın
5. `user_approval_evidence` — user-approval class işaretli ise `User-approval evidence: <link>` zorunlu (`N/A` reddedilir)
6. `user_approval_label` — user-approval class işaretli ise `user-approval-required` label zorunlu

Tüm check'ler hard gate. Failure CI red → PR merge bloklanır (branch protection required check ise).

## Kullanım

### Standart (none of the above) — agent Codex consensus iş

PR template default state. Sadece `none of the above` işaretle:

```markdown
## Boundary declaration (ADR-0011 §2.3)

This PR includes:
- [ ] credential-read
- [ ] credential-write
- [ ] state-mutation (test cluster)
- [ ] state-mutation (production)
- [ ] boundary-cross
- [ ] user-communication
- [x] none of the above (Codex consensus only)

User-approval evidence: N/A
```

### Test cluster state mutation (örn. ConfigMap apply)

```markdown
- [ ] credential-read
- [ ] credential-write
- [x] state-mutation (test cluster)
- [ ] state-mutation (production)
- [ ] boundary-cross
- [ ] user-communication
- [ ] none of the above

User-approval evidence: N/A
```

Label gerekmez. Codex consensus + Kural #7 agent yetkisi.

### User-approval gerektiren iş (örn. Vault rekey)

```markdown
- [x] credential-read
- [x] credential-write
- [x] state-mutation (test cluster)
- [ ] state-mutation (production)
- [ ] boundary-cross
- [ ] user-communication
- [ ] none of the above

User-approval evidence: https://github.com/Halildeu/platform-k8s-gitops/discussions/X#comment-Y
```

PR'a `user-approval-required` label eklenmeli (manuel via `gh pr edit ... --add-label user-approval-required`). CI gate label kontrol eder.

## Backfill (existing PRs grandfather YOK)

Codex `019dd409` direktifi: BG-1 landed sonrası mevcut açık PR'lar **grandfather edilmez**. Her açık PR'a manual backfill:

```bash
# 1. PR body alır
gh pr view <PR#> --json body --jq '.body' > /tmp/pr-body.md

# 2. PR template'i copy + boundary block ekle
cat .github/pull_request_template.md | tail -20 >> /tmp/pr-body.md

# 3. Düzenle (uygun class işaretle, evidence ekle)
$EDITOR /tmp/pr-body.md

# 4. PR body'yi güncelle
gh pr edit <PR#> --body "$(cat /tmp/pr-body.md)"

# 5. (User-approval class varsa) label ekle
gh pr edit <PR#> --add-label user-approval-required
```

CI gate `pull_request: edited` trigger ile otomatik re-run yapar. PASS ile PR yeniden mergeable hale gelir.

## Local test

```bash
# PR body'yi text dosyasına kaydet
cat > /tmp/pr-body.md <<'EOF'
## Boundary declaration (ADR-0011 §2.3)
- [x] credential-read
- [ ] credential-write
- [ ] state-mutation (test cluster)
- [ ] state-mutation (production)
- [ ] boundary-cross
- [ ] user-communication
- [ ] none of the above

User-approval evidence: https://example.com/issue/1
EOF

# Labels file
echo "user-approval-required" > /tmp/labels.txt

# Çalıştır
python3 scripts/governance/check_pr_boundary_declaration.py \
  --body-file /tmp/pr-body.md \
  --labels-file /tmp/labels.txt \
  --verbose
```

Beklenen: `BG-1 PR boundary declaration: PASS (6/6)`.

## CI workflow events

`pull_request_target:` trigger types (BG-1.1 update — Codex 019dd409 A-prime):
- `opened` — PR ilk açılış
- `edited` — body güncellemesi
- `synchronize` — yeni commit push
- `reopened` — closed → reopened
- `labeled` — `user-approval-required` label eklendiğinde
- `unlabeled` — label kaldırıldığında

Bu altı trigger BG-1'in label state değişimine reactive olmasını sağlar.

### Neden `pull_request_target` (BG-1.1)?

Initial BG-1 (PR #233) `pull_request` event kullanıyordu. Dependabot PR'larında
GitHub Actions security policy nedeniyle workflow fire **etmiyor**. Sonuç: BG-1
hard gate dependabot PR sınıfı için çalışmıyordu — coverage gap.

`pull_request_target` ile metadata (body + labels) event payload üzerinden
okunur; PR HEAD checkout edilmez, secrets kullanılmaz, write permissions yok.
Dependabot PR'larında da fire eder.

**Güvenlik kuralları (Codex 019dd409 A-prime)**:
- ✅ Base SHA checkout (`github.event.pull_request.base.sha`)
- ✅ Permissions: `contents: read`, `pull-requests: read`
- ❌ PR HEAD checkout YASAK
- ❌ `gh pr checkout` YASAK
- ❌ Secrets kullanma
- ❌ Label/body mutate etme
- ❌ PR title/body içeriğini shell komutuna interpolate etme

## Roadmap

- BG-1 ✓ (this PR — template + script + workflow)
- BG-2: sandbox-blocking pattern playbook + 3 gray-area resolution docs
- Future: label automation (PR class otomatik tespit + label) — BG-1 scope dışı, ayrı iyileştirme

## References

- ADR-0011 §2.3 (Boundary declaration matrix)
- ADR-0010 §2.5 (Operator/agent authority)
- CLAUDE.md HARD RULE #7 (SSH+sudo+kubectl agent yetkisi)
- Codex thread `019dd409` BG-1 PARTIAL/REVISE (credential-read user-approval class added; event payload parsing; hard gate)
- DD-1..DD-4 + AC-1 governance peers (`scripts/drift_detection/`, `docs/RB-adr-0011-ac-1-first-drill.md`)
