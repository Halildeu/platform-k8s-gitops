def validated_internal_senders($expected_subject):
  if (."@odata.nextLink" // "") != "" then
    error("mail-anchor-page-incomplete")
  elif (.value | type) != "array" or (.value | length) == 0 then
    error("mail-anchor-evidence-empty")
  elif any(.value[]?;
    (.subject // "") != $expected_subject
    or ((.from.emailAddress.address // "") | length) == 0
    or (((.from.emailAddress.address // "") | type) != "string")
    or (((.from.emailAddress.address // "") | test("^[^@[:space:]]+@[^@[:space:]]+$")) | not)
  ) then
    error("mail-anchor-evidence-invalid")
  else
    [
      .value[]?
      | (.from.emailAddress.address // "" | ascii_downcase)
      | select(endswith("@acik.com"))
    ]
    | unique
  end;

($primary[0] | validated_internal_senders($primary_subject)) as $primary_senders
| ($corroborating[0] | validated_internal_senders($corroborating_subject)) as $corroborating_senders
| ([
    $primary_senders[]
    | select(. as $sender | $corroborating_senders | index($sender))
  ] | unique) as $shared_senders
| if ($shared_senders | length) == 1
  then $shared_senders[0]
  else error("mail-anchor-not-unique-or-consistent")
  end
