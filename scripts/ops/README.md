# scripts/ops — Operator + AI Workflow Helpers

> Host-level + cluster-level operator scripts (non-CI). Bunlar staging-sw veya
> developer machine'de kullanılır.

## AI Auto-Merge Cleanup Pattern (Codex Sprint A retrospective + 019df310 absorb)

### Canonical kaynak

`scripts/ops/ai-post-merge-cleanup.sh` — bu repo'da canonical kopya.

Operator deployment: `~/.claude/scripts/ai-post-merge-cleanup.sh` symlink veya kopya:

```bash
# Setup (one-time)
mkdir -p ~/.claude/scripts ~/.claude/logs
ln -sf $(pwd)/scripts/ops/ai-post-merge-cleanup.sh ~/.claude/scripts/ai-post-merge-cleanup.sh
ln -sf $(pwd)/scripts/ops/AI_MONITOR_PATTERN.md ~/.claude/scripts/MONITOR_PATTERN.md
```

Bu pattern her PR auto-merge'den sonra çağrılır:

```bash
gh pr merge $PR --squash --delete-branch --admin && \
  bash ~/.claude/scripts/ai-post-merge-cleanup.sh $PR "$BRANCH"
```

### 5-Layer Hardening (Codex 019df310 absorb)

1. **Per-worktree lock** — atomic `mkdir`, aynı worktree race engelle
2. **Working tree safety** — uncommitted check (porcelain comprehensive + mid-op marker)
3. **Remote tag push HARD GATE** — push fail → no delete
4. **Existing tag SHA collision** — aynı SHA → idempotent OK; farklı → abort
5. **Local-only branch + PR proof** — `gh pr view --json mergedAt` doğrulaması

Plus race protection: `EXPECTED_BRANCH` arg verifier.

### Recovery (1+ yıl sonra)

```bash
# PR numarasıyla
git tag --list 'archive/*pr<N>*'
git checkout -b recovery/X archive/2026/05/<branch>-pr<N>

# Audit
grep "pr=<N>" ~/.claude/logs/git-cleanup.log
```

### Disaster Recovery (laptop disk failure)

Archive tag'leri remote'a push'lu → yeni laptop'ta:
```bash
git clone <repo>
git fetch --tags origin
git tag --list 'archive/*'
```

### Multi-User Concurrent Safety

| Senaryo | Davranış |
|---|---|
| Farklı worktree, farklı PR | ✅ tam izole |
| Aynı worktree, 2 session | ✅ mkdir lock abort |
| Aynı PR, 2 session | ✅ idempotent (tag SHA check) |
| Audit log concurrent append | ✅ POSIX O_APPEND |
| Race (operator switched away) | ✅ EXPECTED_BRANCH guard |

### GitHub Tag Protection (operator manual)

D pattern recovery güvencesi için:
```
Settings → Rules → Tag rulesets:
Pattern: archive/**
- Restrict deletions: ON
- Restrict force-update: ON
- Bypass: NONE
```

Bu setting olmadan archive tag delete'lenebilir → "1+ yıl recovery" iddiası zayıflar.

## Diğer ops scripts

- `platform-ops-vault-patch.sh` — Vault memory online resize (Session 37 Codex absorb)
- `systemd/git-cleanup-audit-logrotate.conf` — AI cleanup audit log rotation policy (1 yıl retention, tamper-detection, forensic note)

## Audit log integrity

`~/.claude/logs/git-cleanup.log` POSIX append-only, ama default mode 0644 yazılabilir (operator-edit risk).

Tamper-detection için rotation sonrası rotated dosyalar read-only (0400). Operator edit ister sudo gerekir, audit trail bozulmaz.

Rotation kurulumu:

```bash
# Operator manual setup
sudo cp scripts/ops/systemd/git-cleanup-audit-logrotate.conf /etc/logrotate.d/git-cleanup-audit
sudo logrotate -d /etc/logrotate.d/git-cleanup-audit  # dry-run validate
sudo logrotate -f /etc/logrotate.d/git-cleanup-audit  # force first rotation
```

Tamper-evident pattern (post-rotation):
```bash
ls -la ~/.claude/logs/git-cleanup.log.*.gz
# -r-------- 1 halil halil ... git-cleanup.log.1.gz   ← read-only post-rotation
```

Editing rotated logs requires `sudo chmod` first → leaves trace.

## Tag protection (GitHub Settings — operator manual)

D pattern recovery güvencesi için **Settings → Rules → Tag rulesets**:
```
Pattern: archive/**
- Restrict deletions: ON
- Restrict force-update: ON
- Bypass: NONE (operator dahil immutable)
```

Bu setting OLMADAN: 1+ yıl recovery iddiası politikaya bağlı kalır (Codex 019df310 absorb).

## Bağlantılar

- `~/.claude/CLAUDE.md` — global Git Workflow HARD RULE
- Codex thread: `019df310-26f4-7b33-8201-f4f4a91e4435`
- `scripts/ops/AI_MONITOR_PATTERN.md` — Monitor wrapper template
- `~/.claude/logs/git-cleanup.log` — host-level audit trail
