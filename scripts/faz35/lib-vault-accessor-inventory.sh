#!/usr/bin/env bash

# Classify one captured `vault list -format=json .../secret-id` result.
# stdout is reserved for a validated accessor JSON array. Callers must stop
# before secret-id generation when this function returns non-zero.
vault_json_document_classify() {
  local status_code=$1 output_file=$2 error_file=$3 document_filter=$4

  [ "$status_code" -eq 0 ] && [ ! -s "$error_file" ] && jq -e -s \
    "length == 1 and (.[0] | ($document_filter))" "$output_file" >/dev/null || return 45
  cat "$output_file"
}

# A missing KV v2 document has one exact, pinned CLI contract. Do not accept a
# substring match: warnings, extra lines, or another path are operational drift.
vault_kv_document_classify() {
  local status_code=$1 output_file=$2 error_file=$3 expected_missing_line=$4

  if [ "$status_code" -eq 0 ]; then
    vault_json_document_classify "$status_code" "$output_file" "$error_file" \
      '.data.data | type == "object"'
    return
  fi

  if [ "$status_code" -eq 2 ] && [ ! -s "$output_file" ] && \
      [ "$(sed -e 's/\r$//' "$error_file")" = "$expected_missing_line" ]; then
    printf 'null'
    return 44
  fi

  return 45
}

vault_accessor_inventory_classify() {
  local status_code=$1 output_file=$2 error_file=$3 compact_output

  if [ "$status_code" -eq 0 ]; then
    vault_json_document_classify "$status_code" "$output_file" "$error_file" \
      'type == "array" and all(.[]; type == "string" and length > 0)'
    return $?
  fi

  compact_output=$(tr -d '[:space:]' <"$output_file")
  if [ "$status_code" -eq 2 ] && [ "$compact_output" = "{}" ] && [ ! -s "$error_file" ]; then
    printf '[]'
    return 0
  fi

  return 45
}
