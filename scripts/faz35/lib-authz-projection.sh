#!/usr/bin/env bash

# Classify only the non-secret /authz/me fields needed by the Faz 35
# entitlement reconciler. Any partial or broader ETHIC state is rejected.
faz35_authz_projection_state() {
  local document=$1
  jq -er '
    if ((.userId | tostring | test("^[0-9]+$")) | not) then
      error("numeric userId is missing")
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
