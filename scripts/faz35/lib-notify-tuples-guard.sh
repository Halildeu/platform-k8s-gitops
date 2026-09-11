#!/usr/bin/env bash
# Faz 35 ES-301b: the invariant guard for a notification-topic tuples JSON, as a function
# so the seeder and the contract test run the same code. Positive validation only: the
# file is accepted when every condition below holds; a jq evaluation error, a missing
# field or a null is a refusal, never a pass (Codex 01a08f67: `if jq -e '… | not'` let
# evaluation errors fall through to the write path).
#
#   validate_notify_tuples <tuples.json>   → 0 valid, 1 refused (reason on stderr)
validate_notify_tuples() {
  local json=$1
  [ -f "$json" ] || { echo "guard: file not found: $json" >&2; return 1; }
  command -v jq >/dev/null 2>&1 || { echo "guard: jq missing" >&2; return 1; }
  if grep -q '__SECOND_TIER__' "$json"; then
    echo "guard: placeholder __SECOND_TIER__ still present" >&2; return 1
  fi
  local verdict
  verdict=$(jq -r '
    def str: type == "string" and length > 0;
    def declared_topic($t): . as $x | ($t | index($x)) != null;
    def declared_template($m): . as $x | ($m | index($x)) != null;
    (.topics // null) as $topics | (.templates // null) as $templates |
    if ($topics | type) != "array" or ($topics | length) == 0 or ($topics | all(str) | not) then "topics must be a non-empty string array"
    elif ($templates | type) != "array" or ($templates | length) == 0 or ($templates | all(str) | not) then "templates must be a non-empty string array"
    elif (.tuples | type) != "array" or (.tuples | length) == 0 then "tuples must be a non-empty array"
    elif (.smoke_checks | type) != "array" or (.smoke_checks | length) == 0 then "smoke_checks must be a non-empty array"
    elif (.tuples | all(type == "object" and (.user | str) and (.relation | str) and (.object | str)) | not) then "every tuple needs string user/relation/object"
    elif (.smoke_checks | all(type == "object" and (.user | str) and (.relation | str) and (.object | str) and (.expect_allowed | type) == "boolean") | not) then "every smoke check needs string user/relation/object and boolean expect_allowed"
    elif ([.tuples[].user, .smoke_checks[].user] | any(endswith(":*") or startswith("user:"))) then "wildcard or user:-typed subject forbidden"
    elif (.tuples | all(
            (.relation == "can_receive"
              and (.user | test("^subscriber:[0-9]+$"))
              and (.object | startswith("notification_topic:"))
              and (.object | ltrimstr("notification_topic:") | declared_topic($topics)))
            or
            (.relation == "topic"
              and (.user | startswith("notification_topic:"))
              and (.user | ltrimstr("notification_topic:") | declared_topic($topics))
              and (.object | startswith("template:"))
              and (.object | ltrimstr("template:") | declared_template($templates)))
          ) | not) then "a tuple is outside the allowed shapes (numeric subscriber can_receive declared topic | declared topic -> declared template)"
    elif (.smoke_checks | all(
            .relation == "can_receive"
            and (.object | startswith("template:"))
            and (.object | ltrimstr("template:") | (declared_template($templates) or . == "ethics.case.activity"))
          ) | not) then "smoke checks must ask can_receive on a declared template (or the activity template as the topic-scope negative)"
    else "OK" end' "$json" 2>&1) || { echo "guard: jq could not evaluate $json: $verdict" >&2; return 1; }
  [ "$verdict" = "OK" ] || { echo "guard: $verdict" >&2; return 1; }
  return 0
}
