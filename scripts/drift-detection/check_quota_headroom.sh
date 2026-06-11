#!/usr/bin/env bash
# scripts/drift-detection/check_quota_headroom.sh
#
# Codex P0 #4 — ResourceQuota headroom preflight gate.
# Computes whether a strict rollout (maxSurge=1, maxUnavailable=0) can fit
# within ResourceQuota for each Deployment in the overlay. Blocks PR when
# headroom < surge pod requirement (worst case: largest single deployment's
# requests.cpu/memory).
#
# Why: Session 37 yaşandı — prod CPU quota 8 dolu olduğunda strict rollout
# api-gateway için Pending pod düştü. Operator manual scale 2→1→2 cycle ile
# kurtardı. Bu script aynı senaryoyu PR-time'da yakalar — "merge bu rollout
# yer açamaz" diyerek block eder.
#
# Usage: bash check_quota_headroom.sh <env>
#
# Exit:
#   0 — clean (rollout will fit)
#   1 — quota exhausted, biggest pod won't fit during rollout
#   2 — quota tight, < 25% headroom

set -uo pipefail

ENV="${1:-prod}"
REPO_ROOT="${PLATFORM_GITOPS_REPO:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)}"
OVERLAY="$REPO_ROOT/kustomize/overlays/${ENV}"
[[ ! -d "$OVERLAY" ]] && { echo "ERR: overlay not found: $OVERLAY"; exit 1; }

cd "$REPO_ROOT" || exit 1

if ! kubectl kustomize "$OVERLAY" > /tmp/quota-render.yaml 2>/dev/null; then
  echo "[FAIL] kustomize render: $OVERLAY"
  exit 1
fi

# Use python for reliable YAML multi-doc parsing + arithmetic
python3 << 'PYEOF'
import sys
sys.stdin = open('/tmp/quota-render.yaml', 'r')
sys.stdin.reconfigure(encoding='utf-8') if hasattr(sys.stdin, 'reconfigure') else None
import sys, yaml, re

docs = list(yaml.safe_load_all(sys.stdin))

# Parse helper: "750m" -> 750, "2" -> 2000, "1.5" -> 1500
def cpu_to_millicores(v):
    if v is None: return 0
    s = str(v).strip()
    if s.endswith('m'): return int(s[:-1])
    return int(float(s) * 1000)

# Parse helper: "512Mi" -> 512, "2Gi" -> 2048, "1Gi" -> 1024
def mem_to_mi(v):
    if v is None: return 0
    s = str(v).strip()
    if s.endswith('Gi'): return int(float(s[:-2]) * 1024)
    if s.endswith('Mi'): return int(s[:-2])
    if s.endswith('Ki'): return int(s[:-2]) // 1024
    return int(s) // (1024 * 1024)

quota = None
deployments = []  # list of (name, replicas, requests_cpu_m, requests_mem_mi, limits_cpu_m, limits_mem_mi)

for d in docs:
    if not isinstance(d, dict): continue
    kind = d.get('kind')
    if kind == 'ResourceQuota':
        # Only consider platform-quota
        name = d.get('metadata', {}).get('name', '')
        if name == 'platform-quota':
            hard = d.get('spec', {}).get('hard', {})
            quota = {
                'requests_cpu_m': cpu_to_millicores(hard.get('requests.cpu', 0)),
                'requests_mem_mi': mem_to_mi(hard.get('requests.memory', 0)),
                'limits_cpu_m': cpu_to_millicores(hard.get('limits.cpu', 0)),
                'limits_mem_mi': mem_to_mi(hard.get('limits.memory', 0)),
                'pods': int(hard.get('pods', 0)),
            }
    elif kind == 'Deployment':
        name = d.get('metadata', {}).get('name', '')
        spec = d.get('spec', {})
        replicas = spec.get('replicas', 1)
        containers = spec.get('template', {}).get('spec', {}).get('containers', [])
        if not containers: continue
        c = containers[0]  # first container
        res = c.get('resources', {})
        req = res.get('requests', {})
        lim = res.get('limits', {})
        deployments.append({
            'name': name,
            'replicas': replicas,
            'requests_cpu_m': cpu_to_millicores(req.get('cpu')),
            'requests_mem_mi': mem_to_mi(req.get('memory')),
            'limits_cpu_m': cpu_to_millicores(lim.get('cpu')),
            'limits_mem_mi': mem_to_mi(lim.get('memory')),
        })

if not quota:
    print("[INFO] platform-quota not found in overlay — skip preflight")
    sys.exit(0)

# Sum current declared usage
sum_req_cpu = sum(d['requests_cpu_m'] * d['replicas'] for d in deployments)
sum_req_mem = sum(d['requests_mem_mi'] * d['replicas'] for d in deployments)
sum_lim_cpu = sum(d['limits_cpu_m'] * d['replicas'] for d in deployments)
sum_lim_mem = sum(d['limits_mem_mi'] * d['replicas'] for d in deployments)
total_pods = sum(d['replicas'] for d in deployments)

# Worst-case surge pod = the largest deployment's per-pod requests
max_pod_req_cpu = max((d['requests_cpu_m'] for d in deployments if d['replicas'] > 0), default=0)
max_pod_req_mem = max((d['requests_mem_mi'] for d in deployments if d['replicas'] > 0), default=0)
max_pod_lim_cpu = max((d['limits_cpu_m'] for d in deployments if d['replicas'] > 0), default=0)
max_pod_lim_mem = max((d['limits_mem_mi'] for d in deployments if d['replicas'] > 0), default=0)

# Print summary
print(f"=== ResourceQuota Headroom Preflight ===")
print(f"Quota hard:")
print(f"  requests.cpu:    {quota['requests_cpu_m']}m")
print(f"  requests.memory: {quota['requests_mem_mi']}Mi")
print(f"  limits.cpu:      {quota['limits_cpu_m']}m")
print(f"  limits.memory:   {quota['limits_mem_mi']}Mi")
print(f"  pods:            {quota['pods']}")
print()
print(f"Declared usage ({len(deployments)} deployments, {total_pods} pod replicas):")
print(f"  requests.cpu:    {sum_req_cpu}m / {quota['requests_cpu_m']}m  ({100*sum_req_cpu//max(quota['requests_cpu_m'],1)}%)")
print(f"  requests.memory: {sum_req_mem}Mi / {quota['requests_mem_mi']}Mi  ({100*sum_req_mem//max(quota['requests_mem_mi'],1)}%)")
print(f"  limits.cpu:      {sum_lim_cpu}m / {quota['limits_cpu_m']}m  ({100*sum_lim_cpu//max(quota['limits_cpu_m'],1)}%)")
print(f"  limits.memory:   {sum_lim_mem}Mi / {quota['limits_mem_mi']}Mi  ({100*sum_lim_mem//max(quota['limits_mem_mi'],1)}%)")
print()
print(f"Largest pod (worst-case surge during strict rollout):")
print(f"  requests.cpu:    {max_pod_req_cpu}m")
print(f"  requests.memory: {max_pod_req_mem}Mi")
print()

# Check: can largest pod fit during surge?
EXIT_CODE = 0
def check(metric, used, hard, surge, name):
    global EXIT_CODE
    margin = hard - used
    if margin < surge:
        print(f"[FAIL] {metric}: surge pod ({surge}{name}) > headroom ({margin}{name}) — strict rollout would fail")
        EXIT_CODE = max(EXIT_CODE, 1)
    elif margin < surge + (hard // 4):
        print(f"[WARN] {metric}: surge pod fits but < 25% extra headroom (margin {margin}{name})")
        EXIT_CODE = max(EXIT_CODE, 2)
    else:
        print(f"[OK]   {metric}: surge pod fits ({margin}{name} headroom > {surge}{name} required)")

check('requests.cpu', sum_req_cpu, quota['requests_cpu_m'], max_pod_req_cpu, 'm')
check('requests.memory', sum_req_mem, quota['requests_mem_mi'], max_pod_req_mem, 'Mi')
check('limits.cpu', sum_lim_cpu, quota['limits_cpu_m'], max_pod_lim_cpu, 'm')
check('limits.memory', sum_lim_mem, quota['limits_mem_mi'], max_pod_lim_mem, 'Mi')

# --- Object-count headroom (2026-06-11, gitops#1449 follow-up) ---
# Live case: services 20/20 doluyken yeni Service apply'da Forbidden aldı
# (stderr'de sessiz — Endpoints yaratıldı Service yaratılamadı, bridge yarım).
# Render'daki object sayıları quota hard'a karşı: headroom <= 0 → FAIL.
# Not: render sayımı alt sınırdır (ESO'nun yarattığı Secret'lar + ArgoCD/runtime
# objeleri render'da görünmez) — quota'ya yaklaşan her değer erkén sinyaldir;
# bu yüzden headroom <= 0 FAIL + <= 2 WARN eşiği kullanılır.
hard_counts = {}
for d in docs:
    if isinstance(d, dict) and d.get('kind') == 'ResourceQuota' \
            and d.get('metadata', {}).get('name') == 'platform-quota':
        h = d.get('spec', {}).get('hard', {})
        for k in ('services', 'secrets', 'configmaps', 'persistentvolumeclaims', 'pods'):
            if k in h:
                hard_counts[k] = int(h[k])

kind_to_quota_key = {
    'Service': 'services',
    'Secret': 'secrets',
    'ConfigMap': 'configmaps',
    'PersistentVolumeClaim': 'persistentvolumeclaims',
}
rendered_counts = {k: 0 for k in kind_to_quota_key.values()}
for d in docs:
    if not isinstance(d, dict):
        continue
    qk = kind_to_quota_key.get(d.get('kind'))
    if qk:
        rendered_counts[qk] += 1
# pods: Deployment replicas toplamı (+ ESO/job'lar hariç — alt sınır)
rendered_counts['pods'] = total_pods

print()
print("Object-count headroom (render = alt sınır; ESO/runtime objeleri hariç):")
for qk, hard in sorted(hard_counts.items()):
    used = rendered_counts.get(qk, 0)
    margin = hard - used
    if margin <= 0:
        print(f"[FAIL] {qk}: rendered {used} / hard {hard} — headroom {margin} (apply Forbidden üretir)")
        EXIT_CODE = max(EXIT_CODE, 1)
    elif margin <= 2:
        print(f"[WARN] {qk}: rendered {used} / hard {hard} — headroom {margin} (sıkışık; runtime objeleriyle dolabilir)")
        EXIT_CODE = max(EXIT_CODE, 2)
    else:
        print(f"[OK]   {qk}: rendered {used} / hard {hard} — headroom {margin}")

print()
print(f"exit_code={EXIT_CODE}")
sys.exit(EXIT_CODE)
PYEOF
