#!/usr/bin/env bash

set -euo pipefail

SUMMARY="${1:-}"
[[ -n "${SUMMARY}" && -s "${SUMMARY}" ]] || {
  echo "ERROR: viewer audience summary is missing or empty" >&2
  exit 1
}

for command_name in grep jq sha256sum; do
  command -v "${command_name}" >/dev/null 2>&1 || {
    echo "ERROR: required command missing: ${command_name}" >&2
    exit 1
  }
done

jq -e '
  .schemaVersion == "faz22.6.viewerFrontendAudience.v1"
  and (.action == "check" or .action == "apply" or .action == "rollback")
  and (.result | type == "string" and length > 0)
  and .target.environment == "test"
  and .target.realm == "platform-test"
  and .target.frontendClient == "frontend"
  and .target.resourceClient == "remote-bridge-operator-api"
  and .target.mapperName == "remote-bridge-operator-api-audience"
  and (.before.controlledMapperCount | type == "number")
  and (.before.exact | type == "boolean")
  and (.before.rows | type == "array")
  and (.after.controlledMapperCount | type == "number")
  and (.after.exact | type == "boolean")
  and (.after.rows | type == "array")
  and ([.before.rows[], .after.rows[]] | all(
    .name == "remote-bridge-operator-api-audience"
    and (.config.includedClientAudience == null or (.config.includedClientAudience | type == "string"))
    and (.config.includedCustomAudiencePresent | type == "boolean")
    and (.config.accessTokenClaim == null or .config.accessTokenClaim == "true" or .config.accessTokenClaim == "false")
    and (.config.idTokenClaim == null or .config.idTokenClaim == "true" or .config.idTokenClaim == "false")
    and (.config.introspectionTokenClaim == null or .config.introspectionTokenClaim == "true" or .config.introspectionTokenClaim == "false")
    and (.config.userinfoTokenClaim == null or .config.userinfoTokenClaim == "true" or .config.userinfoTokenClaim == "false")
  ))
  and (.securityBoundary.accessTokenOnly | type == "boolean")
  and .securityBoundary.productionMutation == false
  and .secretHygiene.adminPasswordIncluded == false
  and .secretHygiene.adminTokenIncluded == false
  and .secretHygiene.userTokenIncluded == false
' "${SUMMARY}" >/dev/null || {
  echo "ERROR: viewer audience summary contract mismatch" >&2
  exit 1
}

# These exact fields are typed Keycloak claim assertions, not credentials.
# Every path component is inspected so nested values under a secret-like key
# cannot bypass the evidence guard.
jq -e '
  def secret_name:
    test("(password|secret|private[_-]?key|access[_-]?token|refresh[_-]?token)"; "i");
  def allowed_claim_field:
    . == "accessTokenClaim"
    or . == "idTokenClaim"
    or . == "introspectionTokenClaim"
    or . == "userinfoTokenClaim";
  [paths(scalars) as $path
    | select(
        ((getpath($path) | type) == "string")
        and ((getpath($path) | length) > 0)
        and any(
          $path[];
          ((tostring | secret_name) and ((tostring | allowed_claim_field) | not))
        )
      )
  ] | length == 0
' "${SUMMARY}" >/dev/null || {
  echo "ERROR: secret-named string value found in evidence" >&2
  exit 1
}

if grep -Eqi 'bearer[[:space:]]+[A-Za-z0-9._-]+|eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+' "${SUMMARY}"; then
  echo "ERROR: bearer/JWT-like material found in evidence" >&2
  exit 1
fi

summary_dir="$(cd "$(dirname "${SUMMARY}")" && pwd)"
summary_name="$(basename "${SUMMARY}")"
checksum_tmp="${summary_dir}/.SHA256SUMS.$$.tmp"
trap 'rm -f "${checksum_tmp}"' EXIT
(
  cd "${summary_dir}"
  sha256sum "${summary_name}" > "${checksum_tmp}"
  sha256sum -c "${checksum_tmp}"
  mv "${checksum_tmp}" SHA256SUMS
)

echo "viewer-frontend-audience-evidence=verified"
