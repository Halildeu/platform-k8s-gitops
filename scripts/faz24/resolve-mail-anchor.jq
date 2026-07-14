def validated_internal_senders($expected_subject):
  if (."@odata.nextLink" // "") != "" then
    error("mail-anchor-page-incomplete")
  elif (.value | type) != "array" or (.value | length) == 0 then
    error("mail-anchor-evidence-empty")
  elif any(.value[]?;
    (.subject // "") != $expected_subject
    or ((.from.emailAddress.address // "") | length) == 0
    or (((.from.emailAddress.address // "") | ascii_downcase) | endswith("@acik.com") | not)
  ) then
    error("mail-anchor-evidence-invalid")
  else
    [
      .value[]?
      | (.from.emailAddress.address // "" | ascii_downcase)
    ]
    | unique
  end;

($primary[0] | validated_internal_senders($primary_subject)) as $primary_senders
| ($corroborating[0] | validated_internal_senders($corroborating_subject)) as $corroborating_senders
| if ($primary_senders | length) == 1
    and ($corroborating_senders | length) == 1
    and $primary_senders[0] == $corroborating_senders[0]
  then $primary_senders[0]
  else error("mail-anchor-not-unique-or-consistent")
  end
