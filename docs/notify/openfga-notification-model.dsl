model
  schema 1.1

# Faz 21.3 explicit-scope contract per ADR-0008 (platform-k8s-gitops).
# UI mandate: "Scope atanmadan kullanıcı hiçbir veri göremez."
#   - organization#member = tenant binding, NO data grant
#   - organization#admin  = scope assignment authority
#   - company|project|warehouse|branch#viewer@user = explicit assignment
#     from data_access.scope INSERT via permission-service tuple writer.
#   - parent_org / parent_company / parent_warehouse = ownership/containment
#     metadata; NO auto-grant viewer.
#
# PG ↔ OpenFGA naming bridge: PG `data_access.scope.scope_kind = 'depot'`
# (V19/V20 immutable migrations) maps to OpenFGA object_type `warehouse`
# via tuple writer (Halildeu/platform-k8s-gitops ADR-0008 § Naming).

type user

type organization
  relations
    define admin: [user]
    define member: [user]

type company
  relations
    define org: [organization]
    define viewer: [user]

type project
  relations
    define company: [company]
    define viewer: [user]

type warehouse
  relations
    define company: [company]
    define parent_warehouse: [warehouse]
    define viewer: [user]

type branch
  relations
    define company: [company]
    define viewer: [user]

type module
  relations
    define can_edit: [user] but not blocked
    define can_manage: [user] or can_edit but not blocked
    define can_view: [user] or can_manage but not blocked
    define blocked: [user]

type action
  relations
    define allowed: [user] but not blocked
    define blocked: [user]

type report
  relations
    define can_edit: [user] but not blocked
    define can_view: [user] or can_edit but not blocked
    define blocked: [user]

# R16 PR-B (Codex 019e27f5 Option 3) — report_group authz contract repair.
# Faz 2 Program 1c spec'te yazılı ama model'e eklenmedi; bu PR ile ekleniyor.
# ReportDefinition.access.reportGroup ("FINANCE_REPORTS", "HR_REPORTS",
# "SALES_REPORTS", "ANALYTICS_REPORTS") → bu type üzerinden authz check.
#
# Runtime'da permission-service `TupleSyncService` key-aware mapping
# yapacak (PR-B-2): PermissionType.REPORT + key in REPORT_GROUP_KEYS ise
# object type `report_group`; aksi halde `report`. /authz/me.reports
# map'i `report_group:<KEY>#can_view` listObjects ile dolar.
type report_group
  relations
    define can_edit: [user] but not blocked
    define can_view: [user] or can_edit but not blocked
    define blocked: [user]

# ── Faz 23.7 M3-supplement: Notification authorization (Codex 019e2651 Yol A) ──
# Channel-level notification authz (ADR-0013 Layer 2). The notification-
# orchestrator AuthzClient calls permission-service /api/v1/internal/authz/check
# with {principal_type:subscriber, relation:can_receive, object_type:template}.
# Until this extension the OpenFGA model held only ERP types, so every
# subscriber-recipient delivery resolved to BLOCKED_BY_AUTHZ by construction.
#
# Topic-based inheritance (Codex refinement): a subscriber is granted
# `can_receive` on a notification_topic; templates inherit it via their `topic`
# relation. Per-template direct grant is intentionally NOT modeled — governance:
# topic-scoped grants only, future topic-federation friendly.
#
# `template` is the transition-compat alias of `notification_template`: the
# orchestrator AuthzClient currently sends object_type=template; once the
# backend migrates to object_type=notification_template the `template` type
# can be retired.

type subscriber
  relations
    define member: [user]

type service_account

type notification_topic
  relations
    define can_receive: [subscriber]
    define can_publish: [service_account, user]

type notification_template
  relations
    define topic: [notification_topic]
    define can_receive: can_receive from topic
    define can_publish: can_publish from topic

type template
  relations
    define topic: [notification_topic]
    define can_receive: can_receive from topic
    define can_publish: can_publish from topic
