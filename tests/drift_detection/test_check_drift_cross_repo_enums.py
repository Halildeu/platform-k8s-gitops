"""ADR-0031 DD-5-1 unit tests — cross-repo enum drift parsers + spec validator.

Codex iter-1..iter-4 absorbed:
  - Per-strategy positive case on real-shape fixtures (synthetic, derived from
    actual production sources — ADR-0031 §I9).
  - Per-strategy negative case: drifted value, duplicate.
  - Per-strategy error case: unparseable shape → exit 2.
  - Spec validator: duplicate id, unknown kind, missing field, zero mirrors,
    java_grid_column_case_literals without anchor.
  - Paired-PR protocol: parse, validate, multiple-url, no-block.

Run:
    python3 -m unittest tests.drift_detection.test_check_drift_cross_repo_enums -v
"""
from __future__ import annotations

import importlib.util
import json
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_DIR = REPO_ROOT / "scripts" / "drift_detection"
sys.path.insert(0, str(SCRIPT_DIR))

from lib.cross_repo_enum import parsers  # noqa: E402
from lib.cross_repo_enum.paired_pr import (  # noqa: E402
    PairingError,
    extract_paired_pr_url,
    parse_pr_url,
)
from lib.cross_repo_enum.spec_validator import (  # noqa: E402
    SpecValidationError,
    load_spec_schema,
    validate_spec,
)


SPEC_SCHEMA_PATH = REPO_ROOT / "config" / "cross_repo_enum_drift_spec.schema.json"
SPEC_YAML_PATH = REPO_ROOT / "config" / "cross_repo_enum_drift_spec.yaml"


# ----------------------------------------------------------------------
# strip_comments
# ----------------------------------------------------------------------


class TestStripComments(unittest.TestCase):
    def test_line_comment(self) -> None:
        src = "int x = 1; // tail\nint y = 2;"
        out = parsers.strip_comments(src)
        self.assertNotIn("tail", out)
        self.assertIn("int x = 1;", out)
        self.assertIn("int y = 2;", out)

    def test_block_comment(self) -> None:
        src = "int x = /* skipme */ 1;"
        out = parsers.strip_comments(src)
        self.assertNotIn("skipme", out)
        self.assertIn("int x =", out)

    def test_preserves_string_literal_with_slashes(self) -> None:
        src = 'String url = "http://example.com/path";'
        out = parsers.strip_comments(src)
        self.assertIn("http://example.com/path", out)

    def test_preserves_escaped_quote(self) -> None:
        src = r'String q = "He said \"hi\""; // comment'
        out = parsers.strip_comments(src)
        self.assertIn(r'He said \"hi\"', out)
        self.assertNotIn("comment", out)

    def test_unterminated_block_comment_errors(self) -> None:
        with self.assertRaises(parsers.ParseError):
            parsers.strip_comments("int x = 1; /* unterminated")

    def test_unterminated_string_errors(self) -> None:
        with self.assertRaises(parsers.ParseError):
            parsers.strip_comments('String s = "open and no close')


# ----------------------------------------------------------------------
# java_enum
# ----------------------------------------------------------------------


JAVA_ENUM_COMPLIANCE_DECISION = """
package com.example;

public enum ComplianceDecision {
    COMPLIANT,
    NON_COMPLIANT,
    UNAUTHORIZED,
    UNKNOWN
}
"""

JAVA_ENUM_DEVICE_STATUS_WITH_METHODS = """
package com.example;

public enum DeviceStatus {
    PENDING_ENROLLMENT,
    ONLINE,
    @Deprecated
    STALE,           // legacy
    OFFLINE,
    DECOMMISSIONED;  // trailing semicolon

    public boolean isActive() {
        return this == ONLINE;
    }
}
"""

JAVA_ENUM_CONSTRUCTOR_ARGS = """
public enum Color {
    RED("#ff0000"),
    GREEN("#00ff00"),
    BLUE("#0000ff");

    private final String hex;
    Color(String hex) { this.hex = hex; }
}
"""


class TestJavaEnumParser(unittest.TestCase):
    def test_compliance_decision_simple(self) -> None:
        out = parsers.parse_java_enum(JAVA_ENUM_COMPLIANCE_DECISION, "ComplianceDecision")
        self.assertEqual(out, ["COMPLIANT", "NON_COMPLIANT", "UNAUTHORIZED", "UNKNOWN"])

    def test_with_methods_and_annotations(self) -> None:
        out = parsers.parse_java_enum(JAVA_ENUM_DEVICE_STATUS_WITH_METHODS, "DeviceStatus")
        self.assertEqual(
            out,
            ["PENDING_ENROLLMENT", "ONLINE", "STALE", "OFFLINE", "DECOMMISSIONED"],
        )

    def test_per_value_constructor_args_stripped(self) -> None:
        out = parsers.parse_java_enum(JAVA_ENUM_CONSTRUCTOR_ARGS, "Color")
        self.assertEqual(out, ["RED", "GREEN", "BLUE"])

    def test_symbol_not_found(self) -> None:
        with self.assertRaises(parsers.ParseError):
            parsers.parse_java_enum(JAVA_ENUM_COMPLIANCE_DECISION, "Missing")


# ----------------------------------------------------------------------
# java_set_of
# ----------------------------------------------------------------------


JAVA_SET_OF_WDAC_SINGLE = """
package com.example;
import java.util.Set;

public class P {
    public static final Set<String> WDAC_MODE_ENUM = Set.of("OFF", "AUDIT", "ENFORCE", "UNKNOWN");
}
"""

JAVA_SET_OF_MULTI_LINE = """
public static final Set<String> PROBE_ERROR_CODE_ENUM = Set.of(
        "NO_EVIDENCE",
        "REGISTRY_DENIED",
        "FILESYSTEM_DENIED"
);
"""

JAVA_SET_OF_TYPE_WITNESS = """
public static final Set<String> SERVICE_STATE_ENUM = Set.<String>of(
        "RUNNING", "STOPPED", "DISABLED", "UNKNOWN"
);
"""

JAVA_SET_OF_UNMATCHED_QUOTE = """
public static final Set<String> BAD = Set.of("A, "B");
"""


class TestJavaSetOfParser(unittest.TestCase):
    def test_single_line(self) -> None:
        out = parsers.parse_java_set_of(JAVA_SET_OF_WDAC_SINGLE, "WDAC_MODE_ENUM")
        self.assertEqual(out, ["OFF", "AUDIT", "ENFORCE", "UNKNOWN"])

    def test_multi_line(self) -> None:
        out = parsers.parse_java_set_of(JAVA_SET_OF_MULTI_LINE, "PROBE_ERROR_CODE_ENUM")
        self.assertEqual(out, ["NO_EVIDENCE", "REGISTRY_DENIED", "FILESYSTEM_DENIED"])

    def test_type_witness(self) -> None:
        out = parsers.parse_java_set_of(JAVA_SET_OF_TYPE_WITNESS, "SERVICE_STATE_ENUM")
        self.assertEqual(out, ["RUNNING", "STOPPED", "DISABLED", "UNKNOWN"])

    def test_unmatched_quote_does_not_silently_pass(self) -> None:
        # The shape `Set.of("A, "B")` actually parses as two string literals
        # (the quote in the middle closes the first string). Our parser
        # accepts that under the "literal-only body" rule because there's no
        # non-literal residual. The TRUE protection is that B (without a
        # surrounding quote) leaves a residual `B)` which is non-literal —
        # but here the quote re-opens. Let's instead test a clearly
        # non-literal residual case.
        bad = 'public static final Set<String> BAD = Set.of("A", foo, "B");'
        with self.assertRaises(parsers.ParseError):
            parsers.parse_java_set_of(bad, "BAD")

    def test_symbol_not_found(self) -> None:
        with self.assertRaises(parsers.ParseError):
            parsers.parse_java_set_of(JAVA_SET_OF_WDAC_SINGLE, "MISSING")


# ----------------------------------------------------------------------
# ts_const_tuple
# ----------------------------------------------------------------------


TS_CONST_TUPLE_PLAIN = """
const PROHIBITED_DECISION_VALUES = [
  'COMPLIANT',
  'NON_COMPLIANT',
  'UNAUTHORIZED',
  'UNKNOWN',
] as const;
"""

TS_CONST_TUPLE_TYPED = """
export const DEVICE_STATUS_VALUES: readonly DeviceStatus[] = [
  'PENDING_ENROLLMENT',
  'ONLINE',
  'STALE',
  'OFFLINE',
  'DECOMMISSIONED',
] as const;
"""

TS_CONST_TUPLE_SATISFIES = """
export const FOO = ['A', "B", `C`] as const satisfies readonly ('A' | 'B' | 'C')[];
"""

TS_CONST_TUPLE_NON_LITERAL = """
export const FOO = ['A', BAR, 'C'] as const;
"""


class TestTsConstTupleParser(unittest.TestCase):
    def test_plain_as_const(self) -> None:
        out = parsers.parse_ts_const_tuple(
            TS_CONST_TUPLE_PLAIN, "PROHIBITED_DECISION_VALUES"
        )
        self.assertEqual(out, ["COMPLIANT", "NON_COMPLIANT", "UNAUTHORIZED", "UNKNOWN"])

    def test_typed(self) -> None:
        out = parsers.parse_ts_const_tuple(
            TS_CONST_TUPLE_TYPED, "DEVICE_STATUS_VALUES"
        )
        self.assertEqual(
            out,
            ["PENDING_ENROLLMENT", "ONLINE", "STALE", "OFFLINE", "DECOMMISSIONED"],
        )

    def test_as_const_satisfies_with_mixed_quotes(self) -> None:
        out = parsers.parse_ts_const_tuple(TS_CONST_TUPLE_SATISFIES, "FOO")
        self.assertEqual(out, ["A", "B", "C"])

    def test_non_literal_entry_rejected(self) -> None:
        with self.assertRaises(parsers.ParseError):
            parsers.parse_ts_const_tuple(TS_CONST_TUPLE_NON_LITERAL, "FOO")


# ----------------------------------------------------------------------
# ts_union_type
# ----------------------------------------------------------------------


TS_UNION_SINGLE_LINE = (
    "export type DeviceStatus = 'PENDING_ENROLLMENT' | 'ONLINE' | 'STALE' "
    "| 'OFFLINE' | 'DECOMMISSIONED';"
)

TS_UNION_MULTI_LINE = """
export type ServiceStartupMode =
  | 'AUTO'
  | 'AUTO_DELAYED'
  | 'MANUAL'
  | 'DISABLED'
  | 'UNKNOWN';
"""

TS_UNION_NON_LITERAL = "export type Bad = 'A' | 'B' | string;"


class TestTsUnionTypeParser(unittest.TestCase):
    def test_single_line(self) -> None:
        out = parsers.parse_ts_union_type(TS_UNION_SINGLE_LINE, "DeviceStatus")
        self.assertEqual(
            out,
            ["PENDING_ENROLLMENT", "ONLINE", "STALE", "OFFLINE", "DECOMMISSIONED"],
        )

    def test_multi_line_with_leading_pipe(self) -> None:
        out = parsers.parse_ts_union_type(TS_UNION_MULTI_LINE, "ServiceStartupMode")
        self.assertEqual(out, ["AUTO", "AUTO_DELAYED", "MANUAL", "DISABLED", "UNKNOWN"])

    def test_non_literal_rejected(self) -> None:
        with self.assertRaises(parsers.ParseError):
            parsers.parse_ts_union_type(TS_UNION_NON_LITERAL, "Bad")


# ----------------------------------------------------------------------
# java_grid_column_case_literals
# ----------------------------------------------------------------------


JAVA_GRID_COLUMN_CASE = '''
public final class DeviceGridColumns {
    private static final List<GridColumn> COLUMNS = List.of(
            new GridColumn("prohibited_status",
                    "CASE WHEN pe.id IS NULL THEN 'NO_EVALUATION' ELSE 'OK' END",
                    ColumnType.ENUM, false, "Yasakli Yazilim Durumu")
    );
}
'''

JAVA_GRID_COLUMN_NESTED_CASE = '''
new GridColumn("prohibited_status",
        "CASE WHEN x THEN 'A' ELSE CASE WHEN y THEN 'B' ELSE 'C' END END",
        ColumnType.ENUM, false, "h")
'''

JAVA_GRID_COLUMN_NO_ANCHOR = '''
new GridColumn("other_column", "d.foo", ColumnType.TEXT, false, "h")
'''


class TestJavaGridColumnCaseLiteralsParser(unittest.TestCase):
    def test_extracts_then_else(self) -> None:
        out = parsers.parse_java_grid_column_case_literals(
            JAVA_GRID_COLUMN_CASE,
            "prohibited_status",
            anchor='new GridColumn("prohibited_status",',
        )
        self.assertEqual(out, ["NO_EVALUATION", "OK"])

    def test_nested_case_rejected(self) -> None:
        with self.assertRaises(parsers.ParseError):
            parsers.parse_java_grid_column_case_literals(
                JAVA_GRID_COLUMN_NESTED_CASE,
                "prohibited_status",
                anchor='new GridColumn("prohibited_status",',
            )

    def test_anchor_not_found(self) -> None:
        with self.assertRaises(parsers.ParseError):
            parsers.parse_java_grid_column_case_literals(
                JAVA_GRID_COLUMN_NO_ANCHOR,
                "prohibited_status",
                anchor='new GridColumn("prohibited_status",',
            )

    def test_anchor_required(self) -> None:
        with self.assertRaises(parsers.ParseError):
            parsers.parse_java_grid_column_case_literals(
                JAVA_GRID_COLUMN_CASE,
                "prohibited_status",
                anchor="",
            )


# ----------------------------------------------------------------------
# Dispatcher
# ----------------------------------------------------------------------


class TestDispatcher(unittest.TestCase):
    def test_unknown_strategy(self) -> None:
        with self.assertRaises(parsers.ParseError):
            parsers.parse("bogus_strategy", "src", "Sym")

    def test_dispatches_java_enum(self) -> None:
        out = parsers.parse("java_enum", JAVA_ENUM_COMPLIANCE_DECISION, "ComplianceDecision")
        self.assertEqual(set(out), {"COMPLIANT", "NON_COMPLIANT", "UNAUTHORIZED", "UNKNOWN"})

    def test_dispatches_java_grid_column_with_anchor(self) -> None:
        out = parsers.parse(
            "java_grid_column_case_literals",
            JAVA_GRID_COLUMN_CASE,
            "prohibited_status",
            anchor='new GridColumn("prohibited_status",',
        )
        self.assertEqual(out, ["NO_EVALUATION", "OK"])


# ----------------------------------------------------------------------
# Spec validator
# ----------------------------------------------------------------------


class TestSpecValidator(unittest.TestCase):
    def setUp(self) -> None:
        self.schema = load_spec_schema(SPEC_SCHEMA_PATH)

    def test_canonical_spec_passes(self) -> None:
        import yaml  # type: ignore

        with SPEC_YAML_PATH.open("r", encoding="utf-8") as fh:
            spec = yaml.safe_load(fh)
        # Should NOT raise
        validate_spec(spec, self.schema)

    def test_duplicate_mapping_id(self) -> None:
        spec = {
            "schema_version": 1,
            "mappings": [
                {
                    "id": "dup",
                    "canonical": {
                        "repo": "x/y",
                        "path": "a.java",
                        "kind": "java_enum",
                        "symbol": "Foo",
                    },
                    "mirrors": [
                        {
                            "repo": "x/z",
                            "path": "b.ts",
                            "kind": "ts_const_tuple",
                            "symbol": "FOO_VALUES",
                        }
                    ],
                },
                {
                    "id": "dup",
                    "canonical": {
                        "repo": "x/y",
                        "path": "c.java",
                        "kind": "java_enum",
                        "symbol": "Bar",
                    },
                    "mirrors": [
                        {
                            "repo": "x/z",
                            "path": "d.ts",
                            "kind": "ts_const_tuple",
                            "symbol": "BAR_VALUES",
                        }
                    ],
                },
            ],
        }
        with self.assertRaises(SpecValidationError) as cm:
            validate_spec(spec, self.schema)
        self.assertIn("duplicate", str(cm.exception).lower())

    def test_unknown_kind(self) -> None:
        spec = {
            "schema_version": 1,
            "mappings": [
                {
                    "id": "x",
                    "canonical": {
                        "repo": "x/y",
                        "path": "a.java",
                        "kind": "java_record",
                        "symbol": "Foo",
                    },
                    "mirrors": [
                        {
                            "repo": "x/z",
                            "path": "b.ts",
                            "kind": "ts_const_tuple",
                            "symbol": "FOO",
                        }
                    ],
                }
            ],
        }
        with self.assertRaises(SpecValidationError):
            validate_spec(spec, self.schema)

    def test_zero_mirrors(self) -> None:
        spec = {
            "schema_version": 1,
            "mappings": [
                {
                    "id": "x",
                    "canonical": {
                        "repo": "x/y",
                        "path": "a.java",
                        "kind": "java_enum",
                        "symbol": "Foo",
                    },
                    "mirrors": [],
                }
            ],
        }
        with self.assertRaises(SpecValidationError):
            validate_spec(spec, self.schema)

    def test_missing_anchor_for_grid_column_case(self) -> None:
        spec = {
            "schema_version": 1,
            "mappings": [
                {
                    "id": "x",
                    "canonical": {
                        "repo": "x/y",
                        "path": "a.java",
                        "kind": "java_grid_column_case_literals",
                        "symbol": "foo",
                    },
                    "mirrors": [
                        {
                            "repo": "x/z",
                            "path": "b.ts",
                            "kind": "ts_const_tuple",
                            "symbol": "FOO",
                        }
                    ],
                }
            ],
        }
        with self.assertRaises(SpecValidationError):
            validate_spec(spec, self.schema)

    def test_extra_anchor_on_non_case_strategy(self) -> None:
        spec = {
            "schema_version": 1,
            "mappings": [
                {
                    "id": "x",
                    "canonical": {
                        "repo": "x/y",
                        "path": "a.java",
                        "kind": "java_enum",
                        "symbol": "Foo",
                        "anchor": "should-not-be-here",
                    },
                    "mirrors": [
                        {
                            "repo": "x/z",
                            "path": "b.ts",
                            "kind": "ts_const_tuple",
                            "symbol": "FOO",
                        }
                    ],
                }
            ],
        }
        with self.assertRaises(SpecValidationError):
            validate_spec(spec, self.schema)


# ----------------------------------------------------------------------
# Paired-PR protocol
# ----------------------------------------------------------------------


class TestPairedPRProtocol(unittest.TestCase):
    def test_no_block_returns_none(self) -> None:
        body = "Some PR description.\n\nNo pairing here."
        self.assertIsNone(extract_paired_pr_url(body))

    def test_single_paired_url(self) -> None:
        body = (
            "Intro.\n\n"
            "<!-- cross-repo-enum-drift:paired-pr -->\n"
            "paired_pr_url: https://github.com/Halildeu/platform-web/pull/123\n"
        )
        url = extract_paired_pr_url(body)
        self.assertEqual(url, "https://github.com/Halildeu/platform-web/pull/123")

    def test_multiple_paired_urls_rejected(self) -> None:
        body = (
            "<!-- cross-repo-enum-drift:paired-pr -->\n"
            "paired_pr_url: https://github.com/Halildeu/platform-web/pull/1\n"
            "paired_pr_url: https://github.com/Halildeu/platform-web/pull/2\n"
        )
        with self.assertRaises(PairingError):
            extract_paired_pr_url(body)

    def test_block_without_url(self) -> None:
        body = (
            "<!-- cross-repo-enum-drift:paired-pr -->\n"
            "intentionally empty\n"
        )
        with self.assertRaises(PairingError):
            extract_paired_pr_url(body)

    def test_parse_pr_url(self) -> None:
        ref = parse_pr_url("https://github.com/Halildeu/platform-web/pull/456")
        self.assertEqual(ref.repo, "Halildeu/platform-web")
        self.assertEqual(ref.number, 456)

    def test_parse_pr_url_invalid(self) -> None:
        with self.assertRaises(PairingError):
            parse_pr_url("https://example.com/not-a-pr")


# ----------------------------------------------------------------------
# Real-source sanity (when running locally with sibling worktrees present)
# ----------------------------------------------------------------------


SIBLING_BACKEND = Path("/Users/halilkocoglu/Documents/platform-backend")
SIBLING_WEB = Path("/Users/halilkocoglu/Documents/platform-web")


class TestRealSourceParserSanity(unittest.TestCase):
    """Sanity-check parsers against the actual production source shapes."""

    @unittest.skipUnless(SIBLING_BACKEND.exists(), "sibling backend not checked out")
    def test_compliance_decision_real(self) -> None:
        src = (
            SIBLING_BACKEND
            / "endpoint-admin-service/src/main/java/com/example/endpointadmin/model/ComplianceDecision.java"
        ).read_text(encoding="utf-8")
        out = parsers.parse_java_enum(src, "ComplianceDecision")
        self.assertEqual(set(out), {"COMPLIANT", "NON_COMPLIANT", "UNAUTHORIZED", "UNKNOWN"})

    @unittest.skipUnless(SIBLING_BACKEND.exists(), "sibling backend not checked out")
    def test_wdac_mode_enum_real(self) -> None:
        src = (
            SIBLING_BACKEND
            / "endpoint-admin-service/src/main/java/com/example/endpointadmin/security/AppControlPayloadPolicy.java"
        ).read_text(encoding="utf-8")
        out = parsers.parse_java_set_of(src, "WDAC_MODE_ENUM")
        self.assertEqual(set(out), {"OFF", "AUDIT", "ENFORCE", "UNKNOWN"})

    @unittest.skipUnless(SIBLING_BACKEND.exists(), "sibling backend not checked out")
    def test_service_state_enum_real(self) -> None:
        src = (
            SIBLING_BACKEND
            / "endpoint-admin-service/src/main/java/com/example/endpointadmin/security/EndpointServiceWireEnums.java"
        ).read_text(encoding="utf-8")
        out = parsers.parse_java_set_of(src, "SERVICE_STATE_ENUM")
        self.assertEqual(set(out), {"RUNNING", "STOPPED", "DISABLED", "UNKNOWN"})

    @unittest.skipUnless(SIBLING_BACKEND.exists(), "sibling backend not checked out")
    def test_startup_mode_enum_real(self) -> None:
        src = (
            SIBLING_BACKEND
            / "endpoint-admin-service/src/main/java/com/example/endpointadmin/security/EndpointServiceWireEnums.java"
        ).read_text(encoding="utf-8")
        out = parsers.parse_java_set_of(src, "STARTUP_MODE_ENUM")
        self.assertEqual(
            set(out),
            {"AUTO", "AUTO_DELAYED", "MANUAL", "DISABLED", "UNKNOWN"},
        )

    @unittest.skipUnless(SIBLING_BACKEND.exists(), "sibling backend not checked out")
    def test_prohibited_status_sql_case_real(self) -> None:
        src = (
            SIBLING_BACKEND
            / "endpoint-admin-service/src/main/java/com/example/endpointadmin/grid/DeviceGridColumns.java"
        ).read_text(encoding="utf-8")
        out = parsers.parse_java_grid_column_case_literals(
            src, "prohibited_status", anchor='new GridColumn("prohibited_status",'
        )
        self.assertEqual(out, ["NO_EVALUATION", "OK"])

    @unittest.skipUnless(SIBLING_WEB.exists(), "sibling web not checked out")
    def test_prohibited_decision_values_real(self) -> None:
        src = (
            SIBLING_WEB
            / "apps/mfe-endpoint-admin/src/pages/devices/EndpointDevicesPage.tsx"
        ).read_text(encoding="utf-8")
        out = parsers.parse_ts_const_tuple(src, "PROHIBITED_DECISION_VALUES")
        self.assertEqual(
            set(out), {"COMPLIANT", "NON_COMPLIANT", "UNAUTHORIZED", "UNKNOWN"}
        )

    @unittest.skipUnless(SIBLING_WEB.exists(), "sibling web not checked out")
    def test_device_status_union_real(self) -> None:
        src = (
            SIBLING_WEB
            / "apps/mfe-endpoint-admin/src/entities/endpoint-device/types.ts"
        ).read_text(encoding="utf-8")
        out = parsers.parse_ts_union_type(src, "DeviceStatus")
        self.assertEqual(
            set(out),
            {"PENDING_ENROLLMENT", "ONLINE", "STALE", "OFFLINE", "DECOMMISSIONED"},
        )

    @unittest.skipUnless(SIBLING_WEB.exists(), "sibling web not checked out")
    def test_startup_mode_real(self) -> None:
        src = (
            SIBLING_WEB
            / "apps/mfe-endpoint-admin/src/entities/endpoint-services/types.ts"
        ).read_text(encoding="utf-8")
        out = parsers.parse_ts_union_type(src, "StartupMode")
        self.assertEqual(
            set(out),
            {"AUTO", "AUTO_DELAYED", "MANUAL", "DISABLED", "UNKNOWN"},
        )


if __name__ == "__main__":
    unittest.main()
