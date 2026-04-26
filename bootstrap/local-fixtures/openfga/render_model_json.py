#!/usr/bin/env python3
from __future__ import annotations

import json
import re
import sys
from pathlib import Path


TYPE_LINE_RE = re.compile(r"^type\s+([a-zA-Z_][a-zA-Z0-9_]*)$")
DEFINE_LINE_RE = re.compile(r"^define\s+([a-zA-Z_][a-zA-Z0-9_]*):\s+(.+)$")
DIRECT_TYPE_RE = re.compile(r"\[([a-zA-Z_][a-zA-Z0-9_]*)\]")


def parse_term(term: str) -> dict:
  term = term.strip()
  if term.startswith("[") and term.endswith("]"):
    return {"this": {}}

  if " from " in term:
    relation, tupleset = [part.strip() for part in term.split(" from ", 1)]
    return {
      "tupleToUserset": {
        "tupleset": {"object": "", "relation": tupleset},
        "computedUserset": {"object": "", "relation": relation},
      }
    }

  return {"computedUserset": {"object": "", "relation": term}}


def parse_union(expr: str) -> dict:
  parts = [part.strip() for part in expr.split(" or ") if part.strip()]
  if len(parts) == 1:
    return parse_term(parts[0])
  return {"union": {"child": [parse_term(part) for part in parts]}}


def parse_expr(expr: str) -> dict:
  expr = expr.strip()
  if " but not " in expr:
    base, subtract = [part.strip() for part in expr.split(" but not ", 1)]
    return {
      "difference": {
        "base": parse_union(base),
        "subtract": parse_term(subtract),
      }
    }
  return parse_union(expr)


def build_type_definition(type_name: str, relations: dict[str, str]) -> dict:
  if not relations:
    return {"type": type_name, "relations": {}, "metadata": None}

  relation_defs: dict[str, dict] = {}
  relation_meta: dict[str, dict] = {}

  for relation_name, expr in relations.items():
    relation_defs[relation_name] = parse_expr(expr)

    direct_types = []
    seen = set()
    for match in DIRECT_TYPE_RE.findall(expr):
      if match in seen:
        continue
      seen.add(match)
      direct_types.append({"type": match, "condition": ""})

    relation_meta[relation_name] = {
      "directly_related_user_types": direct_types,
      "module": "",
      "source_info": None,
    }

  return {
    "type": type_name,
    "relations": relation_defs,
    "metadata": {
      "relations": relation_meta,
      "module": "",
      "source_info": None,
    },
  }


def parse_model(text: str) -> dict:
  type_definitions: list[dict] = []
  current_type: str | None = None
  current_relations: dict[str, str] = {}

  for raw_line in text.splitlines():
    stripped = raw_line.strip()
    if (
      not stripped
      or stripped.startswith("#")
      or stripped == "model"
      or stripped == "relations"
      or stripped.startswith("schema ")
    ):
      continue

    type_match = TYPE_LINE_RE.match(stripped)
    if type_match:
      if current_type is not None:
        type_definitions.append(build_type_definition(current_type, current_relations))
      current_type = type_match.group(1)
      current_relations = {}
      continue

    define_match = DEFINE_LINE_RE.match(stripped)
    if define_match:
      current_relations[define_match.group(1)] = define_match.group(2).strip()
      continue

    raise ValueError(f"Unsupported OpenFGA DSL line: {raw_line}")

  if current_type is not None:
    type_definitions.append(build_type_definition(current_type, current_relations))

  return {
    "schema_version": "1.1",
    "type_definitions": type_definitions,
  }


def main() -> int:
  if len(sys.argv) > 2:
    print("usage: render_model_json.py [model.fga]", file=sys.stderr)
    return 2

  source = Path(sys.argv[1]) if len(sys.argv) == 2 else Path(__file__).with_name("model.fga")
  payload = parse_model(source.read_text())
  json.dump(payload, sys.stdout, indent=2)
  sys.stdout.write("\n")
  return 0


if __name__ == "__main__":
  raise SystemExit(main())
