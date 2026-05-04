# AI Auto-Merge Monitor Pattern (Opsiyon D — AI-Native Forensic + Race Protected)

Her PR auto-merge Monitor'u şu wrapper template ile yazılır:

```bash
PR=<number>
REPO=Halildeu/<repo>
BRANCH="<feat-branch>"   # PR'ın branch ismi — race protection için
prev=""
while true; do
  s=$(gh pr checks $PR --repo $REPO --json name,state 2>/dev/null || echo '[]')
  [[ "$s" == "[]" ]] && { sleep 30; continue; }
  cur=$(jq -r '.[] | "\(.name): \(.state)"' <<<"$s" | sort)
  [[ "$prev" == "$cur" ]] && { sleep 30; continue; }

  pending=$(jq -r '[.[] | select(.state=="PENDING" or .state=="QUEUED" or .state=="IN_PROGRESS")] | length' <<<"$s")
  pass=$(jq -r '[.[] | select(.state=="SUCCESS")] | length' <<<"$s")
  fail=$(jq -r '[.[] | select(.state=="FAILURE" or .state=="CANCELLED" or .state=="TIMED_OUT")] | length' <<<"$s")
  skipped=$(jq -r '[.[] | select(.state=="SKIPPED" or .state=="NEUTRAL")] | length' <<<"$s")
  total=$(jq -r 'length' <<<"$s")
  accounted=$((pass + fail + pending + skipped))
  ts=$(date +%H:%M:%S)
  echo "[$ts PR #$PR] $pass pass, $fail fail, $pending pending, $skipped skipped (total=$total)"

  if [[ "$fail" -gt 0 ]]; then
    echo "[$ts PR #$PR FAILED]"
    jq -r '.[] | select(.state=="FAILURE" or .state=="CANCELLED" or .state=="TIMED_OUT") | "- " + .name' <<<"$s"
    break
  fi

  if [[ "$pending" -eq 0 && "$fail" -eq 0 && "$pass" -gt 0 && "$accounted" -eq "$total" ]]; then
    echo "[$ts PR #$PR ALL DONE — merging + race-protected cleanup]"
    if gh pr merge $PR --repo $REPO --squash --delete-branch --admin 2>&1 | head -5; then
      # === AI-Native Forensic Cleanup (Opsiyon D + race protection) ===
      # Pass expected branch — if operator switched away, cleanup aborts safely
      bash ~/.claude/scripts/ai-post-merge-cleanup.sh $PR "$BRANCH"
    fi
    break
  fi
  prev=$cur
  sleep 30
done
echo "[monitor] PR #$PR watch ended"
```

## Anahtar Noktalar

1. **`gh pr merge` başarılı olursa** cleanup tetiklenir
2. **`ai-post-merge-cleanup.sh`** otomatik:
   - Working tree safety check
   - Fetch + prune
   - Archive tag yarat + GitHub'a push
   - Detached HEAD on origin/main
   - Eski branch sil
   - Audit log entry

## Recovery (1+ yıl sonra)

```bash
# PR numarasıyla
git tag --list 'archive/*pr<N>*'
git checkout -b recovery/X archive/2026/05/<branch>-pr<N>

# Tarih aralığıyla
git tag --list 'archive/2026/05/*'

# Audit log'tan
grep "pr=<N>" ~/.claude/logs/git-cleanup.log
```

## Disaster Recovery (laptop kaybı)

Archive tag'leri GitHub'da push'lu olduğu için yeni laptop'ta:
```bash
git clone <repo>
git fetch --tags origin
git tag --list 'archive/*'  # tüm geçmiş PR'lar erişilebilir
```
