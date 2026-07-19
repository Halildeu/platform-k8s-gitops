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
