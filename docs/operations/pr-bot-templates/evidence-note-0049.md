Evidence (PASS):
- python3 scripts/check_acceptance_evidence.py
- python3 scripts/check_doc_ids.py
- python3 scripts/check_doc_locations.py

Note:
- python3 scripts/check_story_links.py STORY-0049 is expected to FAIL until STORY-0049 is added to docs/03-delivery/PROJECT-FLOW.tsv (SSOT).
- This PR is intentionally docs-only; PROJECT-FLOW changes will be a separate PR when 0049 is scheduled.
