#!/usr/bin/env bash

# Validate one complete read-only Keycloak persona snapshot. A missing persona
# is a valid first-run state. An existing persona may be pre-role/pre-org after
# a recoverable partial run, but it may not carry any unrelated profile field,
# group, direct role, composite role, or client role.
faz35_validate_keycloak_persona_snapshot() {
  local snapshot=$1 username=$2 email=$3 first_name=$4 last_name=$5 org_id=$6
  jq -e \
    --arg username "$username" --arg email "$email" \
    --arg first "$first_name" --arg last "$last_name" --arg org "$org_id" '
    (.users | type) == "array" and (.users | length) <= 1 and
    if (.users | length) == 0 then
      (keys | sort) == ["users"]
    else
      (.users[0].id | type) == "string" and (.users[0].id | length) > 0 and
      (.profile | type) == "object" and
      .profile.id == .users[0].id and
      .profile.username == $username and .profile.email == $email and
      .profile.firstName == $first and .profile.lastName == $last and
      .profile.enabled == true and .profile.emailVerified == true and
      (.profile.requiredActions // []) == [] and
      (((.profile.attributes // {}) == {}) or
       ((.profile.attributes // {}) == {org_id:[$org]})) and
      (.roleMappings | type) == "object" and
      (([((.roleMappings.realmMappings // [])[] | .name)] -
        ["default-roles-platform-test", "ethics-manager"]) | length == 0) and
      ([((.roleMappings.clientMappings // {}) | to_entries[]? |
        .value.mappings[]? | .name)] | length == 0) and
      (.groups | type) == "array" and (.groups | length) == 0 and
      (.effectiveRealm | type) == "array" and
      (([.effectiveRealm[].name] -
        ["default-roles-platform-test", "ethics-manager", "offline_access", "uma_authorization"]) |
       length == 0) and
      (.effectiveClients | type) == "array" and
      (.effectiveClients | length) > 0 and
      (([.effectiveClients[].clientId] | unique | length) ==
       (.effectiveClients | length)) and
      all(.effectiveClients[];
        (.clientId | type) == "string" and (.clientId | length) > 0 and
        (.roles | type) == "array" and
        if .clientId == "account" then
          (([.roles[].name] - ["manage-account", "manage-account-links", "view-profile"]) |
           length == 0)
        else
          (.roles | length) == 0
        end
      )
    end
  ' "$snapshot"
}
