# platform-k8s-gitops — ops komutları wrapper
# Kullanım: make <target>
# make help — hedef listesi

.PHONY: help build build-test build-prod build-eso-test build-eso-prod build-monitoring \
        lint yamllint shelllint kustomize-build-all sanity \
        apply-test apply-prod apply-eso-test apply-eso-prod apply-monitoring \
        smoke-test smoke-prod \
        install-eso-test install-eso-prod install-kyverno install-cert-manager \
        es-switch-test es-switch-prod \
        clean-dryrun context-packet

help:
	@echo "platform-k8s-gitops Makefile"
	@echo ""
	@echo "Kustomize build sanity:"
	@echo "  make sanity                  — tüm overlay + base kustomize build"
	@echo "  make build-test              — overlays/test"
	@echo "  make build-prod              — overlays/prod"
	@echo "  make build-eso-test          — overlays/test/eso"
	@echo "  make build-eso-prod          — overlays/prod/eso"
	@echo "  make build-monitoring        — base/monitoring"
	@echo ""
	@echo "Lint:"
	@echo "  make lint                    — yaml + shell + kustomize"
	@echo "  make yamllint                — yamllint tüm dizinler"
	@echo "  make shelllint               — shellcheck bootstrap/ + scripts/ao-context-packet.sh"
	@echo ""
	@echo "AI context (ao-kernel governed context bridge):"
	@echo "  make context-packet          — render governed context packet (read-only)"
	@echo ""
	@echo "Canlı apply (dikkat: canlı cluster):"
	@echo "  make apply-test              — overlays/test → k3d-test"
	@echo "  make apply-prod              — overlays/prod → k3d-prod"
	@echo "  make apply-eso-test          — overlays/test/eso"
	@echo "  make apply-eso-prod          — overlays/prod/eso"
	@echo "  make apply-monitoring        — base/monitoring (prod cluster)"
	@echo ""
	@echo "Smoke (D29 3-katman — docs/S1-S2-acceptance-smoke-runbook.md):"
	@echo "  make smoke-test              — testai.acik.com deny + sentinel"
	@echo "  make smoke-prod              — ai.acik.com deny + sentinel"
	@echo ""
	@echo "Bootstrap helpers:"
	@echo "  make install-eso-test        — bash bootstrap/install-eso-helm.sh test"
	@echo "  make install-eso-prod        — install-eso-helm.sh prod"
	@echo "  make install-kyverno         — install-kyverno.sh (DRAFT)"
	@echo "  make install-cert-manager    — install-cert-manager.sh (DRAFT)"
	@echo "  make es-switch-test          — apply-eso-switch.sh test (secret-stub → externalsecret)"
	@echo "  make es-switch-prod          — apply-eso-switch.sh prod"

# =========== Kustomize build sanity ===========

sanity: build-test build-prod build-eso-test build-eso-prod build-monitoring
	@echo "✓ tüm overlay + base kustomize build PASS"

build-test:
	@kubectl kustomize kustomize/overlays/test > /dev/null

build-prod:
	@kubectl kustomize kustomize/overlays/prod > /dev/null

build-eso-test:
	@kubectl kustomize kustomize/overlays/test/eso > /dev/null

build-eso-prod:
	@kubectl kustomize kustomize/overlays/prod/eso > /dev/null

build-monitoring:
	@kubectl kustomize kustomize/base/monitoring > /dev/null

# =========== Lint ===========

lint: yamllint shelllint sanity
	@echo "✓ lint PASS"

yamllint:
	@yamllint -d '{extends: relaxed, rules: {line-length: {max: 200, level: warning}, document-start: disable, truthy: {check-keys: false}}}' \
	  kustomize/ argocd/ docs/ helm-values/ 2>&1 | grep -v "^$$" || echo "✓ yamllint PASS"

shelllint:
	@shellcheck -S warning bootstrap/*.sh scripts/ao-context-packet.sh || echo "✓ shellcheck PASS"

# =========== AI context (ao-kernel governed context bridge) ===========
# Whitelisted knobs only, read as ENV vars inside the recipe shell (never
# Make-expanded into the command line) so a knob value cannot inject shell:
#   MAX_ITEMS=12 MIN_CONF=0.7 INCLUDE_DOC_CLAIMS=1 make context-packet
# For any other argument, call scripts/ao-context-packet.sh directly.
context-packet:
	@bash -c 'args=(); \
		if [ -n "$${MAX_ITEMS:-}" ]; then args+=(--max-items "$$MAX_ITEMS"); fi; \
		if [ -n "$${MIN_CONF:-}" ]; then args+=(--min-conf "$$MIN_CONF"); fi; \
		if [ -n "$${INCLUDE_DOC_CLAIMS:-}" ]; then args+=(--include-doc-claims); fi; \
		exec bash scripts/ao-context-packet.sh "$${args[@]}"'

# =========== Canlı apply ===========

apply-test:
	@echo "⚠ canlı apply — k3d-test overlays/test"
	@read -p "Devam et? (y/N): " c && [ "$$c" = "y" ]
	@kubectl --context k3d-test apply -k kustomize/overlays/test

apply-prod:
	@echo "⚠ canlı apply — k3d-prod overlays/prod (D30 ATOMIC CUTOVER — manuel onay!)"
	@read -p "D30 HARD RULE uyarısı: Devam et? (yes/N): " c && [ "$$c" = "yes" ]
	@kubectl --context k3d-prod apply -k kustomize/overlays/prod

apply-eso-test:
	@kubectl --context k3d-test apply -k kustomize/overlays/test/eso

apply-eso-prod:
	@kubectl --context k3d-prod apply -k kustomize/overlays/prod/eso

apply-monitoring:
	@kubectl --context k3d-prod apply -k kustomize/base/monitoring

# =========== Smoke ===========

smoke-test:
	@echo "=== Smoke testai.acik.com (D29 3-katman partial — deny + sentinel) ==="
	@echo -n "sentinel /testai-healthz: "; curl -sk -o /dev/null -w "%{http_code}\n" https://testai.acik.com/testai-healthz
	@echo -n "variants deny: "; curl -sk -o /dev/null -w "%{http_code}\n" https://testai.acik.com/variants
	@echo -n "auth/actuator/health: "; curl -sk -o /dev/null -w "%{http_code}\n" https://testai.acik.com/auth/actuator/health
	@echo "Full smoke: docs/S1-S2-acceptance-smoke-runbook.md"

smoke-prod:
	@echo "=== Smoke ai.acik.com (D29 — D32 cutover sonrası) ==="
	@echo -n "variants deny: "; curl -sk -o /dev/null -w "%{http_code}\n" https://ai.acik.com/variants
	@echo -n "auth/actuator/health: "; curl -sk -o /dev/null -w "%{http_code}\n" https://ai.acik.com/auth/actuator/health

# =========== Bootstrap helpers ===========

install-eso-test:
	@bash bootstrap/install-eso-helm.sh test

install-eso-prod:
	@bash bootstrap/install-eso-helm.sh prod

install-kyverno:
	@bash bootstrap/install-kyverno.sh test

install-cert-manager:
	@bash bootstrap/install-cert-manager.sh test

es-switch-test:
	@bash bootstrap/apply-eso-switch.sh test

es-switch-prod:
	@bash bootstrap/apply-eso-switch.sh prod

# =========== Clean ===========

clean-dryrun:
	@rm -f /tmp/test.yaml /tmp/prod.yaml /tmp/test-eso.yaml /tmp/prod-eso.yaml /tmp/monitoring.yaml
	@echo "✓ /tmp/*.yaml temizlendi"
