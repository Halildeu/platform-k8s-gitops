#!/usr/bin/env bash
# tests/promotion/test_scan_promotion_candidates.sh
#
# Behavioral integration test for scripts/promotion/scan-promotion-candidates.sh.
#
# Neden (Codex 019f6af2): #2295 aktivasyonunda scanner'ın label precondition'ı ve
# orphan-branch idempotency'si canlıda kırıldı. Eklenen fix'lerin kritik yolları
# (label ensure, PR-lifecycle guard, expected-SHA lease) `PROMOTION_DRY_RUN=1`
# smoke'unda ÇALIŞMAZ (dry-run candidate döngüsünde push'tan önce çıkar; label
# ensure yalnız non-dry-run dalında). Bu test o yolları gerçekten yürütür.
#
# Yaklaşım (hibrit — Codex önerisi):
#   · GERÇEK git: tempdir'de working repo + bare `origin` → lease semantiği
#     (empty lease / exact-SHA lease / divergent replacement / push reddi)
#     gerçekten test edilir.
#   · FAKE gh: PATH'te stub. Label state DOSYADA tutulur ($FAKE_GH_LABELS_FILE) —
#     `export` subprocess'ler arasında taşınmaz (Codex REVISE-3 must-fix 1).
#
# Yanlış-pozitif guard'ları (Codex REVISE-3):
#   · run_scan exit code'u YUTMAZ → SCAN_RC her pozitif testte assert edilir.
#   · Lifecycle testleri remote candidate branch SEED EDER → "değişmedi" iddiası
#     gerçek bir SHA'yı korur (ABSENT tautolojisi değil).
#   · Orphan testi local candidate branch BIRAKMAZ → gerçek divergent
#     (non-fast-forward) replacement test edilir; ancestor kontrolüyle kanıtlanır.
#
# Run:  bash tests/promotion/test_scan_promotion_candidates.sh
# Exit: 0 all pass, 1 any fail.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
SCRIPT="$REPO_ROOT/scripts/promotion/scan-promotion-candidates.sh"

PASS=0
FAIL=0

pass() { echo "  ✓ $1"; PASS=$((PASS + 1)); }
fail() { echo "  ✗ $1"; shift; [[ $# -gt 0 ]] && printf '    %s\n' "$@"; FAIL=$((FAIL + 1)); }

assert_contains() {
  local label="$1" haystack="$2" needle="$3"
  if printf '%s' "$haystack" | grep -F -q -- "$needle"; then pass "$label"
  else fail "$label" "expected to contain: $needle" "actual tail: $(printf '%s' "$haystack" | tail -4)"; fi
}
assert_not_contains() {
  local label="$1" haystack="$2" needle="$3"
  if printf '%s' "$haystack" | grep -F -q -- "$needle"; then fail "$label" "should NOT contain: $needle"
  else pass "$label"; fi
}
assert_eq() {
  local label="$1" actual="$2" expected="$3"
  if [[ "$actual" == "$expected" ]]; then pass "$label"
  else fail "$label" "expected: $expected" "actual:   $actual"; fi
}

SHA="1111111111111111111111111111111111111111"
SHORT="1111111"
OLD_DIGEST="sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
NEW_DIGEST="sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
BRANCH="auto-promotion/prod-testrepo-${SHORT}"

setup_fixture() {
  TMP="$(mktemp -d)"; export TMP
  BARE="$TMP/origin.git"; WORK="$TMP/work"; BIN="$TMP/bin"
  mkdir -p "$BIN"

  git init --bare -q "$BARE"
  mkdir -p "$WORK"
  git init -q -b main "$WORK"
  git -C "$WORK" config user.email "test@example.com"
  git -C "$WORK" config user.name "test"

  mkdir -p "$WORK/release-candidates/testrepo" "$WORK/kustomize/overlays/prod"
  cat > "$WORK/release-candidates/testrepo/${SHA}.json" <<JSON
{
  "service": "svc-test",
  "git_sha": "${SHA}",
  "git_short_sha": "${SHORT}",
  "image": { "digest": "${NEW_DIGEST}" },
  "promotion": { "test": { "verified_at": "2026-07-01T00:00:00Z" }, "prod": {} }
}
JSON
  # Format scanner'ın sed heuristic'iyle birebir:
  #   s|halildeu/${repo}-${service}@sha256:[a-f0-9]{64}|...@${digest}|
  cat > "$WORK/kustomize/overlays/prod/kustomization.yaml" <<YAML
images:
  - name: svc-test
    newName: ghcr.io/halildeu/testrepo-svc-test@${OLD_DIGEST}
YAML
  git -C "$WORK" add -A
  git -C "$WORK" commit -q -m "fixture"
  git -C "$WORK" remote add origin "$BARE"
  git -C "$WORK" push -q origin main

  # Label state DOSYADA (subprocess'ler arası kalıcı) — Codex must-fix 1.
  FAKE_GH_LABELS_FILE="$TMP/fake-gh-labels"
  printf '%s\n' auto-promotion env:prod user-approval-required > "$FAKE_GH_LABELS_FILE"
  FAKE_CALLS="$TMP/gh-calls.log"; : > "$FAKE_CALLS"

  cat > "$BIN/gh" <<'GHEOF'
#!/usr/bin/env bash
printf '%s\n' "$*" >> "$FAKE_GH_CALLS"
case "$*" in
  "auth status"*) exit 0 ;;
  *"labels?per_page"*)
    [[ "${FAKE_GH_LABEL_ENUM:-ok}" == "fail" ]] && exit 1
    cat "$FAKE_GH_LABELS_FILE"; exit 0 ;;
  "label create"*)
    [[ "${FAKE_GH_LABEL_CREATE:-ok}" == "fail" ]] && exit 1
    # $3 = label adı (gh label create <name> --repo ...)
    if [[ "${FAKE_GH_LABEL_VISIBLE:-yes}" == "yes" ]]; then
      printf '%s\n' "$3" >> "$FAKE_GH_LABELS_FILE"
    fi
    exit 0 ;;
  "pr list"*)
    case "${FAKE_GH_PR_LIST:-none}" in
      ERR)       exit 1 ;;
      MALFORMED) printf 'not-json{{{'; exit 0 ;;
      none)      printf '[]'; exit 0 ;;
      OPEN)      printf '[{"number":11,"state":"OPEN"}]'; exit 0 ;;
      CLOSED)    printf '[{"number":12,"state":"CLOSED"}]'; exit 0 ;;
      MERGED)    printf '[{"number":13,"state":"MERGED"}]'; exit 0 ;;
    esac ;;
  "pr view"*) printf 'UNKNOWN'; exit 0 ;;
  "pr create"*)
    [[ "${FAKE_GH_PR_CREATE:-ok}" == "fail" ]] && { printf 'boom'; exit 1; }
    printf 'https://github.com/x/y/pull/99\n'; exit 0 ;;
esac
exit 0
GHEOF
  chmod +x "$BIN/gh"

  export FAKE_GH_CALLS="$FAKE_CALLS" FAKE_GH_LABELS_FILE
  export PATH="$BIN:$PATH"
  export PLATFORM_GITOPS_REPO="$WORK" GITHUB_REPO="Halildeu/platform-k8s-gitops"
  export PROMOTION_DRY_RUN=0
  export FAKE_GH_LABEL_ENUM=ok FAKE_GH_LABEL_CREATE=ok FAKE_GH_LABEL_VISIBLE=yes
  export FAKE_GH_PR_LIST=none FAKE_GH_PR_CREATE=ok
}

teardown_fixture() { [[ -n "${TMP:-}" && -d "$TMP" ]] && rm -rf "$TMP"; }

# Exit code YUTULMAZ (Codex must-fix 1): SCAN_RC + SCAN_OUT global.
run_scan() {
  local out="$TMP/scan.out"
  set +e
  ( cd "$WORK" && bash "$SCRIPT" testrepo ) > "$out" 2>&1
  SCAN_RC=$?
  set -e
  SCAN_OUT="$(cat "$out")"
}

remote_sha_of() { git -C "$BARE" rev-parse --verify --quiet "refs/heads/$1" 2>/dev/null || echo "ABSENT"; }
calls() { cat "$FAKE_CALLS"; }

# Remote'ta gerçek candidate branch seed et; LOCAL branch BIRAKMA (must-fix 2/3).
seed_remote_branch() {
  local msg="$1" file="$2"
  git -C "$WORK" checkout -q -b seed-tmp main
  printf '%s\n' "$msg" > "$WORK/$file"
  git -C "$WORK" add "$file"
  git -C "$WORK" commit -q -m "$msg"
  git -C "$WORK" push -q origin "HEAD:refs/heads/$BRANCH"
  git -C "$WORK" checkout -q main
  git -C "$WORK" branch -D seed-tmp > /dev/null
}

# ═════════════════════════════════════════════════════════════════════════════
echo "── Label preflight ──"

setup_fixture
run_scan
assert_eq "1. tüm label mevcut → scanner rc=0" "$SCAN_RC" "0"
assert_not_contains "1b. tüm label mevcut → create çağrısı yok" "$(calls)" "label create"
teardown_fixture

setup_fixture
printf '%s\n' env:prod user-approval-required > "$FAKE_GH_LABELS_FILE"   # auto-promotion eksik
run_scan
assert_eq "2. eksik label + visible → scanner rc=0 (success yolu)" "$SCAN_RC" "0"
assert_contains "2b. eksik label → create edildi" "$(calls)" "label create auto-promotion"
assert_not_contains "2c. görünürlük hatası YOK" "$SCAN_OUT" "create sonrası doğrulanamadı"
assert_contains "2d. success yolu → pr create çağrıldı" "$(calls)" "pr create"
teardown_fixture

setup_fixture
export FAKE_GH_LABEL_ENUM=fail
run_scan
assert_eq "3. label enumeration hata → exit 2 (fail-closed)" "$SCAN_RC" "2"
assert_eq "3b. enumeration hata → ref mutasyonu yok" "$(remote_sha_of "$BRANCH")" "ABSENT"
assert_not_contains "3c. enumeration hata → pr create yok" "$(calls)" "pr create"
teardown_fixture

setup_fixture
printf '%s\n' env:prod user-approval-required > "$FAKE_GH_LABELS_FILE"
export FAKE_GH_LABEL_CREATE=fail
run_scan
assert_eq "4. label create hata → exit 2" "$SCAN_RC" "2"
assert_eq "4b. create hata → branch mutasyonu yok" "$(remote_sha_of "$BRANCH")" "ABSENT"
teardown_fixture

setup_fixture
printf '%s\n' env:prod user-approval-required > "$FAKE_GH_LABELS_FILE"
export FAKE_GH_LABEL_VISIBLE=no    # create "başarılı" ama görünmüyor
run_scan
assert_eq "5. create OK ama görünürlük fail → exit 2" "$SCAN_RC" "2"
assert_contains "5b. görünürlük hatası açık" "$SCAN_OUT" "create sonrası doğrulanamadı"
assert_eq "5c. görünürlük fail → branch mutasyonu yok" "$(remote_sha_of "$BRANCH")" "ABSENT"
teardown_fixture

setup_fixture
{ for i in $(seq 1 210); do printf 'filler-%s\n' "$i"; done
  printf '%s\n' auto-promotion env:prod user-approval-required; } > "$FAKE_GH_LABELS_FILE"
run_scan
assert_eq "6. 210+ label içinde required var → rc=0" "$SCAN_RC" "0"
assert_not_contains "6b. 210+ label → yanlış create yok" "$(calls)" "label create"
teardown_fixture

echo "── PR lifecycle (GERÇEK remote branch korunmalı) ──"

# Tablo: <pr_state>:<test_no>:<beklenen_mesaj>:<beklenen_rc>
# rc kontratı (Codex 019f6af2 non-blocking öneri): API/parse hatası failed++ →
# final exit 1; terminal lifecycle (OPEN/CLOSED/MERGED) temiz skip → exit 0.
for scenario in \
  "ERR:7:fail-closed:1" \
  "MALFORMED:8:fail-closed:1" \
  "OPEN:9:AÇIK:0" \
  "CLOSED:10:KAPATILMIŞ:0" \
  "MERGED:11:MERGED:0"; do
  IFS=':' read -r state num needle exp_rc <<< "$scenario"
  setup_fixture
  seed_remote_branch "operator content" "operator.txt"
  before="$(remote_sha_of "$BRANCH")"
  export FAKE_GH_PR_LIST="$state"
  run_scan
  after="$(remote_sha_of "$BRANCH")"
  assert_contains "${num}. $state → beklenen mesaj" "$SCAN_OUT" "$needle"
  assert_eq "${num}b. $state → remote ref DEĞİŞMEDİ (gerçek SHA korundu)" "$after" "$before"
  assert_not_contains "${num}c. $state → pr create yok" "$(calls)" "pr create"
  assert_eq "${num}d. $state → scanner rc" "$SCAN_RC" "$exp_rc"
  teardown_fixture
done

echo "── Lease (gerçek git) ──"

setup_fixture
run_scan
assert_eq "12. branch absent → rc=0" "$SCAN_RC" "0"
assert_contains "12b. branch absent → draft PR create çağrıldı" "$(calls)" "pr create"
if [[ "$(remote_sha_of "$BRANCH")" != "ABSENT" ]]; then pass "12c. branch absent → empty lease ile ref oluştu"
else fail "12c. ref oluşmalıydı"; fi
teardown_fixture

setup_fixture
# GERÇEK orphan: remote'ta divergent commit; LOCAL candidate branch YOK →
# scanner main'den branch açar → non-fast-forward replacement (asıl canlı hata).
seed_remote_branch "orphan" "orphan.txt"
orphan_sha="$(remote_sha_of "$BRANCH")"
run_scan
new_sha="$(remote_sha_of "$BRANCH")"
assert_eq "13. gerçek orphan → rc=0" "$SCAN_RC" "0"
assert_contains "13b. orphan → expected-SHA lease mesajı" "$SCAN_OUT" "expected-SHA lease"
if [[ "$new_sha" != "$orphan_sha" && "$new_sha" != "ABSENT" ]]; then pass "13c. orphan ref replace edildi"
else fail "13c. orphan ref güncellenmeliydi" "old=$orphan_sha new=$new_sha"; fi
if git --git-dir="$BARE" merge-base --is-ancestor "$orphan_sha" "$new_sha" 2>/dev/null; then
  fail "13d. replacement fast-forward OLMAMALI (divergent olmalı)"
else pass "13d. divergent (non-fast-forward) replacement kanıtlandı"; fi
if git --git-dir="$BARE" cat-file -e "${new_sha}:orphan.txt" 2>/dev/null; then
  fail "13e. yeni tree'de orphan.txt KALMAMALI"
else pass "13e. yeni tree orphan içeriğini taşımıyor"; fi
if git --git-dir="$BARE" show "${new_sha}:kustomize/overlays/prod/kustomization.yaml" 2>/dev/null | grep -Fq "$NEW_DIGEST"; then
  pass "13f. yeni tree prod overlay'de YENİ digest var"
else fail "13f. yeni digest bekleniyordu"; fi
assert_not_contains "13g. delete endpoint'i KULLANILMADI" "$(calls)" "-X DELETE"
teardown_fixture

setup_fixture
# Generic remote push rejection (stale-lease race DEĞİL — dürüst adlandırma,
# Codex REVISE-3): bare pre-receive tüm push'ları reddeder.
seed_remote_branch "pre" "pre.txt"
before_sha="$(remote_sha_of "$BRANCH")"
cat > "$BARE/hooks/pre-receive" <<'HOOK'
#!/usr/bin/env bash
echo "remote: simulated rejection" >&2
exit 1
HOOK
chmod +x "$BARE/hooks/pre-receive"
run_scan
assert_contains "14. generic remote push rejection → [FAIL]" "$SCAN_OUT" "push failed"
assert_eq "14b. push reddi → remote ref DEĞİŞMEDİ" "$(remote_sha_of "$BRANCH")" "$before_sha"
assert_not_contains "14c. push reddi → pr create yok" "$(calls)" "pr create"
assert_eq "14d. push reddi → scanner exit 1 (failed>0)" "$SCAN_RC" "1"
teardown_fixture

# ═════════════════════════════════════════════════════════════════════════════
echo ""
echo "=== scan-promotion-candidates behavioral tests ==="
echo "PASS: $PASS"
echo "FAIL: $FAIL"
[[ "$FAIL" -eq 0 ]] || exit 1
echo "ALL PASS"
