#!/usr/bin/env bash

# The current permission-service /api/v1/roles contract is deliberately
# unpaged. Reject a partial or newly paged response rather than inferring global
# role-name uniqueness from the visible items only.
faz35_validate_complete_role_catalog() {
  local document=$1
  jq -e '
    (.items | type) == "array" and
    (.total | type) == "number" and
    .total == (.items | length) and
    .page == null and .pageSize == null
  ' "${document}" >/dev/null
}
