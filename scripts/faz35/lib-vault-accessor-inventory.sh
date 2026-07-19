#!/usr/bin/env bash

# Classify one captured `vault list -format=json .../secret-id` result.
# stdout is reserved for a validated accessor JSON array. Callers must stop
# before secret-id generation when this function returns non-zero.
vault_accessor_inventory_classify() {
  local status=$1 output_file=$2 error_file=$3 compact_output

  if [ "$status" -eq 0 ]; then
    [ ! -s "$error_file" ] && jq -e -s '
      length == 1 and
      (.[0] | type == "array" and all(.[]; type == "string" and length > 0))
    ' "$output_file" >/dev/null || return 45
    cat "$output_file"
    return 0
  fi

  compact_output=$(tr -d '[:space:]' <"$output_file")
  if [ "$status" -eq 2 ] && [ "$compact_output" = "{}" ] && [ ! -s "$error_file" ]; then
    printf '[]'
    return 0
  fi

  return 45
}
