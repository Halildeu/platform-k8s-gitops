#!/usr/bin/env bash

# Classify only the non-secret /authz/me fields needed by the Faz 35
# entitlement reconciler. Any partial or broader ETHIC state is rejected.
faz35_authz_projection_state() {
  local document=$1
  jq -er '
    if ((.subscriberId | tostring | test("^[0-9]+$")) | not) then
      error("numeric subscriberId is missing")
    elif (.userId | tostring) != (.subscriberId | tostring) then
      error("userId and subscriberId differ")
    elif
      (((.modules // {}) | has("ETHIC")) | not) and
      (((.allowedModules // []) | index("ETHIC")) == null)
    then
      "ABSENT"
    elif
      ((.modules.ETHIC // "") == "MANAGE") and
      (((.allowedModules // []) | index("ETHIC")) != null)
    then
      "EXACT_MANAGE"
    else
      error("ETHIC projection is partial or broader than MANAGE")
    end
  ' "$document"
}

# Return the canonical numeric member id only when permission-service and
# user-service agree before any activation or entitlement mutation.
faz35_authz_member_id() {
  local document=$1 expected=$2
  printf '%s' "$expected" | grep -Eq '^[0-9]+$' || return 1
  jq -er --arg expected "$expected" '
    if ((.subscriberId | type) != "number") then
      error("numeric subscriberId is missing")
    elif (.userId | tostring) != (.subscriberId | tostring) then
      error("userId and subscriberId differ")
    elif (.subscriberId | tostring) != $expected then
      error("authz identity differs from local user")
    else
      .subscriberId | tostring
    end
  ' "$document"
}

# Verify every persona-to-local-user binding before issuing the first
# activation request. http_status is supplied by the calling provisioner and
# is intentionally mockable so the no-mutation-on-mismatch invariant is
# executable in unit tests.
faz35_activate_verified_profiles() {
  local tmp_dir=$1 base_url=$2 writer_auth=$3
  local label local_user_id authz_member_id target_user_id='' user_id code

  for label in target wrong-org denied; do
    local_user_id=$(<"$tmp_dir/$label-user-id")
    authz_member_id=$(faz35_authz_member_id \
      "$tmp_dir/$label-authz-before.json" "$local_user_id") || {
      echo "FATAL: $label authz identity differs from the canonical local profile" >&2
      return 1
    }
    [ "$label" != target ] || target_user_id=$authz_member_id
  done

  for label in target wrong-org denied; do
    user_id=$(<"$tmp_dir/$label-user-id")
    if [ "$(jq -r '.enabled' "$tmp_dir/$label-user.json")" = false ]; then
      printf '{"active":true}' >"$tmp_dir/$label-activation.json"
      code=$(http_status PUT "$base_url/api/v1/users/$user_id/activation" \
        "$tmp_dir/$label-activation-response.json" --config "$writer_auth" \
        -H 'Content-Type: application/json' --data-binary "@$tmp_dir/$label-activation.json")
      [ "$code" = 200 ] || {
        echo "FATAL: $label local user activation failed" >&2
        return 1
      }
    fi
    code=$(http_status GET "$base_url/api/v1/users/me/profile" \
      "$tmp_dir/$label-profile-active.json" --config "$tmp_dir/$label-auth.curl")
    if [ "$code" != 200 ] || ! jq -e --argjson expected "$user_id" \
        '.id == $expected and .enabled == true' "$tmp_dir/$label-profile-active.json" >/dev/null; then
      echo "FATAL: $label active local profile postcondition failed" >&2
      return 1
    fi
  done

  printf '%s' "$target_user_id"
}
