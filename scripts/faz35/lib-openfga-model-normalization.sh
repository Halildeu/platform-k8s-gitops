#!/usr/bin/env bash
# Normalize only the empty protobuf defaults that OpenFGA adds when an
# authorization model is read back. This keeps the reviewed model digest bound
# to the exact source JSON while allowing a semantic write/read postcondition.

readonly FAZ35_OPENFGA_MODEL_NORMALIZE_FILTER='
def faz35_openfga_normalize:
  walk(
    if type == "object" then
      del(.source_info | select(. == null))
      | del(.module | select(. == ""))
      | del(.condition | select(. == ""))
      | del(.object | select(. == ""))
      | del(.conditions | select(. == {}))
      | del(.metadata | select(. == null))
      | del(.relations | select(. == {}))
      | del(.directly_related_user_types | select(. == []))
    else . end
  );
faz35_openfga_normalize
'

faz35_normalize_openfga_model() {
  jq -cS "$FAZ35_OPENFGA_MODEL_NORMALIZE_FILTER"
}

faz35_select_equivalent_openfga_models() {
  local desired=$1
  jq -c --argjson desired "$desired" "
    def faz35_openfga_normalize:
      walk(
        if type == \"object\" then
          del(.source_info | select(. == null))
          | del(.module | select(. == \"\"))
          | del(.condition | select(. == \"\"))
          | del(.object | select(. == \"\"))
          | del(.conditions | select(. == {}))
          | del(.metadata | select(. == null))
          | del(.relations | select(. == {}))
          | del(.directly_related_user_types | select(. == []))
        else . end
      );
    [.[] | select((del(.id) | faz35_openfga_normalize) == \$desired)]
  "
}

faz35_assert_openfga_model_response_id() {
  local expected_model_id=$1
  jq -e --arg expected_model_id "$expected_model_id" '
    type == "object" and
    (.authorization_model | type) == "object" and
    .authorization_model.id == $expected_model_id
  ' >/dev/null
}
