# F14b — ABAC (Attribute-Based Access Control) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add attribute-based policies on top of F14a's RBAC — tenant-defined `allow_if`/`deny_if` rules evaluated by a safe declarative expression engine, exposed through `authorize(user, perm, resource, context)` and demonstrated by gating timesheet approval on the approver's limit.

**Architecture:** A pure, Django-free evaluator (`iam/policy.py`) validates and evaluates a declarative condition tree — never `eval`. Two tenant-schema tables (`iam_policy`, `iam_userattribute`) hold rules and subject attributes. `service.authorize()` layers **after** the existing `perm()`/`has_permission` RBAC gate: RBAC must grant first, then any matching `deny_if` denies, then if any `allow_if` exists at least one must match. Policies and subject attributes are read through the same version-keyed cache F14a built (`cache.bump_role_version()` now also fires on policy/attribute changes). Org-scope row filtering (spec §17 item 5) is **out of scope** — it depends on F3.

**Tech Stack:** Python 3.13, Django 6.1, django-ninja, django-tenants, PostgreSQL 16 (real DB in tests), `uv`/pytest.

**Spec:** `ERP-CORE-SPEC.md` §17 (F14), item 3 (ABAC), item 4 (policy tooling), item 6 (caching). The plan implements the F14b remainder; F14a (role CRUD, guards, version cache) is already merged.

**Scope decisions (deliberate deviations from §17, recorded here so the executor and reviewer treat them as intentional):**
- **Org scope (item 5)** is out — it depends on F3, which is unbuilt; the spec says F14 can start without it.
- **The endpoint decorator** named in item 3 ("and a decorator for endpoints that load the resource first") is **not built now**. `authorize()` is the primitive; the one demonstration endpoint (timesheet approval) loads its resource inside the command and calls `authorize()` directly, so a decorator would have no consumer (YAGNI). Add it when the first endpoint actually needs the load-resource-then-authorize wrapper. No acceptance criterion tests the decorator.
- **Per-request memoisation (item 6)** is subsumed by the process-local, version-keyed cache (same mechanism as F14a): within one request the first lookup populates the cache and later identical lookups hit it; a version bump invalidates immediately in-process. No separate request-scoped store is introduced.
- **The Payroll demonstration** (acceptance: "demonstrated in Payroll") uses **Timesheets** as the stand-in, per the user — Payroll (F2) is intentionally deferred until the frontend exists.

## Global Constraints

- Core/module boundary: a module may call core services, but core never imports a module (I1). `timesheets/commands.py` calling `easybiz.core.iam.service` is allowed; nothing in `easybiz.core` imports timesheets.
- The condition tree is **never executed as code** — no `eval`/`exec`/`compile`. Expression depth and total node count are capped (spec acceptance: "expression depth and size are capped").
- A **missing attribute evaluates to false** (spec acceptance), never an error.
- Status/effect enums are `enum.StrEnum` in a neutral `enums.py` with a `choices()` classmethod (project convention), not `models.TextChoices`.
- Domain errors subclass `easybiz.core.errors.DomainError(message, status)`; the single `@api.exception_handler(DomainError)` in `easybiz/core/api/__init__.py` maps them. Invalid policies use status **422**.
- Per-tenant tables live in the tenant schema and carry no cross-module FKs; `iam_userattribute.user_id` references `users_user` **by value** (I2), like `UserRole.user_id`.
- `authorize()` must never grant beyond RBAC: an `allow_if` policy cannot authorize a user who lacks the RBAC permission.
- New permission code: `core.policy.manage` (added to `CORE_PERMISSIONS`).

## Review Focus

- **Oversized/deeply-nested condition via the API** — a hostile or accidental 10k-node or deeply-recursive tree must be rejected on save with 422, and the evaluator must never recurse unbounded. (Task 1 caps; Task 5 API 422.)
- **Malformed condition** — missing/unknown `op`, a `var` path not under `subject.`/`resource.`/`context.`, or `in` with a non-collection right operand must be rejected on save, not silently treated as allow. (Task 1 validation; Task 4/5 surface it.)
- **Missing subject attribute at evaluation** — a user with no `approval_limit` must not crash and must not be spuriously denied by a `deny_if` that references it (missing → false → condition false). (Task 1 + Task 3.)
- **Group-pattern policy scoping** — a policy on `timesheets.*` must apply to `timesheets.entry.approve`, and a policy on an unrelated permission must not affect the decision. (Task 3 `_policy_matches_permission`.)
- **Stale decision after a policy/attribute change** — a newly created `deny_if` (or a changed attribute) must take effect on the next request in the same process (version bump), not after a 60s TTL. (Task 4.)

---

### Task 1: Pure condition-tree evaluator

**Files:**
- Create: `easybiz/core/iam/policy.py`
- Test: `tests/test_iam_policy_eval.py`

**Interfaces:**
- Consumes: `easybiz.core.errors.DomainError`.
- Produces:
  - `class PolicyError(DomainError)` — `__init__(self, message: str)` calls `super().__init__(message, 422)`.
  - `MAX_DEPTH = 10`, `MAX_NODES = 100` (module constants).
  - `validate_condition(tree: object) -> None` — raises `PolicyError` on any malformed/over-limit tree; returns `None` on success.
  - `evaluate_condition(tree: dict, env: dict) -> bool` — `env` has keys `"subject"`, `"resource"`, `"context"`, each a dict.

Grammar (document as a module docstring-free comment block or constants):
- Bool node: `{"op": "and"|"or", "args": [node, ...]}` (args non-empty) or `{"op": "not", "args": [node]}` (exactly one).
- Leaf node: `{"op": "eq"|"ne"|"lt"|"lte"|"gt"|"gte"|"in", "left": operand, "right": operand}`.
- Operand: `{"var": "<subject|resource|context>.<dotted.path>"}` **or** any other JSON value (treated as a literal). A dict is a var reference only when it has exactly the key `"var"`.
- Evaluation: resolve a `var` by walking `env` along the dotted path; an absent path yields a `MISSING` sentinel. A leaf with any `MISSING` operand is `False`. Ordering ops on incomparable types are `False` (guard `TypeError`). `in` with a non-collection right operand is `False`.

- [ ] **Step 1: Write the failing tests**

```python
from easybiz.core.iam import policy
from easybiz.core.iam.policy import PolicyError

ENV = {"subject": {"approval_limit": 8}, "resource": {"hours": 10, "status": "submitted"}, "context": {}}

def test_leaf_comparisons():
    assert policy.evaluate_condition({"op": "gt", "left": {"var": "resource.hours"}, "right": {"var": "subject.approval_limit"}}, ENV) is True
    assert policy.evaluate_condition({"op": "lte", "left": {"var": "resource.hours"}, "right": 24}, ENV) is True
    assert policy.evaluate_condition({"op": "eq", "left": {"var": "resource.status"}, "right": "submitted"}, ENV) is True
    assert policy.evaluate_condition({"op": "in", "left": {"var": "resource.status"}, "right": ["draft", "submitted"]}, ENV) is True

def test_bool_ops():
    tree = {"op": "and", "args": [
        {"op": "gt", "left": {"var": "resource.hours"}, "right": 0},
        {"op": "not", "args": [{"op": "eq", "left": {"var": "resource.status"}, "right": "draft"}]},
    ]}
    assert policy.evaluate_condition(tree, ENV) is True

def test_missing_attribute_is_false():
    # subject has no approval_limit -> MISSING -> the gt leaf is False, never raises
    env = {"subject": {}, "resource": {"hours": 10}, "context": {}}
    assert policy.evaluate_condition({"op": "gt", "left": {"var": "resource.hours"}, "right": {"var": "subject.approval_limit"}}, env) is False
    assert policy.evaluate_condition({"op": "in", "left": {"var": "subject.nope"}, "right": [1, 2]}, env) is False

def test_incomparable_is_false():
    env = {"subject": {"approval_limit": "high"}, "resource": {"hours": 10}, "context": {}}
    assert policy.evaluate_condition({"op": "gt", "left": {"var": "resource.hours"}, "right": {"var": "subject.approval_limit"}}, env) is False

def test_validate_rejects_unknown_op():
    import pytest
    with pytest.raises(PolicyError):
        policy.validate_condition({"op": "regex", "left": {"var": "resource.x"}, "right": "a"})

def test_validate_rejects_bad_var_path():
    import pytest
    with pytest.raises(PolicyError):
        policy.validate_condition({"op": "eq", "left": {"var": "evil.x"}, "right": 1})

def test_validate_rejects_too_deep():
    import pytest
    tree = {"op": "eq", "left": {"var": "resource.x"}, "right": 1}
    for _ in range(policy.MAX_DEPTH + 1):
        tree = {"op": "not", "args": [tree]}
    with pytest.raises(PolicyError):
        policy.validate_condition(tree)

def test_validate_rejects_too_many_nodes():
    import pytest
    tree = {"op": "or", "args": [{"op": "eq", "left": {"var": "resource.x"}, "right": i} for i in range(policy.MAX_NODES + 1)]}
    with pytest.raises(PolicyError):
        policy.validate_condition(tree)

def test_validate_accepts_valid_tree():
    policy.validate_condition({"op": "and", "args": [
        {"op": "gt", "left": {"var": "resource.hours"}, "right": {"var": "subject.approval_limit"}},
        {"op": "eq", "left": {"var": "context.region"}, "right": "EU"},
    ]})  # returns None
```

- [ ] **Step 2: Run the tests, verify they fail** — Run: `uv run pytest tests/test_iam_policy_eval.py -p no:django -q` — Expected: FAIL (`No module named ...policy`).
- [ ] **Step 3: Implement `policy.py`** — `validate_condition` walks the tree counting nodes and tracking depth, checking op membership and node shape (`LEAF_OPS = {"eq","ne","lt","lte","gt","gte","in"}`, `BOOL_OPS = {"and","or","not"}`), and that every `var` path's first segment is in `{"subject","resource","context"}`; raise `PolicyError` with a specific message on the first violation. `evaluate_condition` recurses; a `_resolve(operand, env)` helper returns the literal or walks the dotted path returning a module-level `MISSING = object()` sentinel; comparison helpers return `False` on `MISSING` or `TypeError`.
- [ ] **Step 4: Run the tests, verify they pass** — Run: `uv run pytest tests/test_iam_policy_eval.py -p no:django -q` — Expected: PASS.
- [ ] **Step 5: Commit** — `git add easybiz/core/iam/policy.py tests/test_iam_policy_eval.py && git commit -m "Add safe declarative policy condition evaluator"`

---

### Task 2: Policy and UserAttribute models

**Files:**
- Create: `easybiz/core/iam/enums.py`
- Modify: `easybiz/core/iam/models.py`
- Create: `easybiz/core/iam/migrations/0003_policy_userattribute.py`
- Test: `tests/test_iam_policy_models.py`

**Interfaces:**
- Produces:
  - `enums.PolicyEffect(StrEnum)` with `ALLOW_IF = "allow_if"`, `DENY_IF = "deny_if"`, and `choices()` returning `[(value, name.title()), ...]` (mirror `timesheets/enums.py`).
  - `models.Policy`: `id` UUID pk (`default=uuid.uuid4, editable=False`), `permission` CharField(100), `effect` CharField(20, `choices=PolicyEffect.choices()`), `condition` `models.JSONField()`, `priority` IntegerField(default=0), `description` CharField(300, blank=True), `is_active` BooleanField(default=True), `created_at` DateTimeField(auto_now_add=True).
  - `models.UserAttribute`: `user_id` UUIDField(db_index=True), `key` CharField(100), `value` `models.JSONField()`, with `UniqueConstraint(fields=["user_id", "key"], name="uniq_user_attribute")`.

- [ ] **Step 1: Write the failing test**

```python
from django_tenants.utils import tenant_context
from easybiz.core.iam.models import Policy, UserAttribute
from easybiz.core.iam.enums import PolicyEffect

USER = "11111111-1111-1111-1111-111111111111"

def test_policy_and_attribute_rows(synced, db_tenant):
    with tenant_context(db_tenant):
        p = Policy.objects.create(permission="timesheets.entry.approve", effect=PolicyEffect.DENY_IF,
                                  condition={"op": "gt", "left": {"var": "resource.hours"}, "right": {"var": "subject.approval_limit"}})
        assert p.is_active is True and p.priority == 0
        UserAttribute.objects.create(user_id=USER, key="approval_limit", value=8)
        import pytest
        from django.db import IntegrityError
        with pytest.raises(IntegrityError):
            UserAttribute.objects.create(user_id=USER, key="approval_limit", value=9)
```

- [ ] **Step 2: Run it, verify it fails** — Run: `uv run pytest tests/test_iam_policy_models.py -q` — Expected: FAIL (model import error).
- [ ] **Step 3: Add `enums.py`, the two models, and generate the migration** — after writing the models run `uv run manage.py makemigrations iam` and confirm it produces `0003_policy_userattribute.py`.
- [ ] **Step 4: Run it, verify it passes** — Run: `uv run pytest tests/test_iam_policy_models.py -q` — Expected: PASS.
- [ ] **Step 5: Verify no stray migrations** — Run: `uv run manage.py makemigrations --check --dry-run` — Expected: "No changes detected".
- [ ] **Step 6: Commit** — `git add easybiz/core/iam/enums.py easybiz/core/iam/models.py easybiz/core/iam/migrations/0003_policy_userattribute.py tests/test_iam_policy_models.py && git commit -m "Add iam_policy and iam_userattribute models"`

---

### Task 3: `authorize()` and version-keyed caches

**Files:**
- Modify: `easybiz/core/iam/service.py`
- Modify: `easybiz/core/iam/cache.py`
- Test: `tests/test_iam_authorize.py`

**Interfaces:**
- Consumes: `policy.evaluate_condition`, `policy.PolicyError`; `enums.PolicyEffect`; `cache.cached_permissions_for`, `cache.role_version`, `cache.bump_role_version`; existing `has_permission`.
- Produces:
  - `service.authorize(user_id, permission: str, resource: dict | None = None, context: dict | None = None) -> bool`.
  - `service.subject_attrs(user_id) -> dict` — `{attr.key: attr.value}` for the user.
  - `service._policy_matches_permission(policy_permission: str, permission: str) -> bool` — exact match, or `policy_permission` is a `<prefix>.*` group that covers `permission` (reuse the `has_permission` matching shape: `{permission.split('.')[0]}.*` and full-prefix `x.*`).
  - `cache.cached_subject_attrs(user_id) -> dict` — `service.subject_attrs` behind the 60s version-keyed cache (key `iam:attrs:{schema}:{user_id}:{version}`), lazy-importing `service`.
  - `cache.cached_active_policies() -> list[dict]` — active policies as `[{"id","permission","effect","condition","priority"}, ...]`, 60s version-keyed cache (key `iam:policies:{schema}:{version}`), lazy-importing `service`.

Decision order in `authorize` (exact): RBAC first (`has_permission(cached_permissions_for(user_id), permission)` → `False` if not granted); build `env = {"subject": cached_subject_attrs(user_id), "resource": resource or {}, "context": context or {}}`; select `cached_active_policies()` whose permission matches; if any `deny_if` evaluates true → `False`; if any `allow_if` exists and none evaluates true → `False`; else `True`.

- [ ] **Step 1: Write the failing tests**

```python
from django_tenants.utils import tenant_context
from easybiz.core.iam import service as iam, cache
from easybiz.core.iam.models import Role, RolePermission, UserRole, Policy, UserAttribute
from easybiz.core.iam.enums import PolicyEffect

PERM = "timesheets.entry.approve"
GT = {"op": "gt", "left": {"var": "resource.hours"}, "right": {"var": "subject.approval_limit"}}

def _user_with(tenant, perms):
    role = Role.objects.create(name="r")
    RolePermission.objects.bulk_create([RolePermission(role=role, permission=p) for p in perms])
    uid = "22222222-2222-2222-2222-222222222222"
    UserRole.objects.create(user_id=uid, role=role)
    return uid

def test_rbac_must_grant_first(synced, db_tenant):
    with tenant_context(db_tenant):
        uid = _user_with(db_tenant, ["timesheets.entry.read"])  # lacks approve
        Policy.objects.create(permission=PERM, effect=PolicyEffect.ALLOW_IF, condition={"op": "eq", "left": {"var": "resource.x"}, "right": 1})
        assert iam.authorize(uid, PERM, resource={"x": 1}) is False  # allow policy cannot grant past RBAC

def test_deny_if_denies(synced, db_tenant):
    with tenant_context(db_tenant):
        uid = _user_with(db_tenant, [PERM])
        UserAttribute.objects.create(user_id=uid, key="approval_limit", value=8)
        Policy.objects.create(permission=PERM, effect=PolicyEffect.DENY_IF, condition=GT)
        assert iam.authorize(uid, PERM, resource={"hours": 10}) is False
        assert iam.authorize(uid, PERM, resource={"hours": 6}) is True

def test_allow_if_required_when_present(synced, db_tenant):
    with tenant_context(db_tenant):
        uid = _user_with(db_tenant, [PERM])
        Policy.objects.create(permission=PERM, effect=PolicyEffect.ALLOW_IF, condition={"op": "eq", "left": {"var": "context.region"}, "right": "EU"})
        assert iam.authorize(uid, PERM, context={"region": "US"}) is False
        assert iam.authorize(uid, PERM, context={"region": "EU"}) is True

def test_no_policies_falls_back_to_rbac(synced, db_tenant):
    with tenant_context(db_tenant):
        uid = _user_with(db_tenant, [PERM])
        assert iam.authorize(uid, PERM, resource={"hours": 99}) is True

def test_group_pattern_policy_matches(synced, db_tenant):
    with tenant_context(db_tenant):
        uid = _user_with(db_tenant, [PERM])
        UserAttribute.objects.create(user_id=uid, key="approval_limit", value=8)
        Policy.objects.create(permission="timesheets.*", effect=PolicyEffect.DENY_IF, condition=GT)
        assert iam.authorize(uid, PERM, resource={"hours": 10}) is False

def test_unrelated_policy_ignored(synced, db_tenant):
    with tenant_context(db_tenant):
        uid = _user_with(db_tenant, [PERM])
        Policy.objects.create(permission="core.user.manage", effect=PolicyEffect.DENY_IF, condition={"op": "eq", "left": {"var": "resource.hours"}, "right": 10})
        assert iam.authorize(uid, PERM, resource={"hours": 10}) is True
```

- [ ] **Step 2: Run them, verify they fail** — Run: `uv run pytest tests/test_iam_authorize.py -q` — Expected: FAIL (`authorize` not defined).
- [ ] **Step 3: Implement `authorize`, `subject_attrs`, `_policy_matches_permission` in `service.py` and the two cached readers in `cache.py`.**
- [ ] **Step 4: Run them, verify they pass** — Run: `uv run pytest tests/test_iam_authorize.py -q` — Expected: PASS.
- [ ] **Step 5: Commit** — `git add easybiz/core/iam/service.py easybiz/core/iam/cache.py tests/test_iam_authorize.py && git commit -m "Add authorize() layering ABAC after RBAC with version-keyed caches"`

---

### Task 4: Policy and attribute write services + dry-run evaluate

**Files:**
- Modify: `easybiz/core/iam/service.py`
- Test: `tests/test_iam_policy_service.py`

**Interfaces:**
- Consumes: Task 1 `validate_condition`/`PolicyError`; Task 3 caches/`authorize`; `audit.record`; `cache.bump_role_version`; `enums.PolicyEffect`.
- Produces (all writes call `validate_condition` where a condition is supplied, then `audit.record` with a `policy.*`/`user.attribute_*` action, then `cache.bump_role_version()`):
  - `create_policy(tenant, *, permission, effect, condition, priority=0, description="", actor_id) -> Policy` — validates the condition, that `effect` is a valid `PolicyEffect` value, and that `permission` is either an exact code in `assignable_permissions(tenant)` **or** a `<module>.*` group whose module is core/enabled; raises `PolicyError` otherwise.
  - `update_policy(tenant, policy_id, *, actor_id, changes: dict) -> Policy` — applies only provided keys among `permission|effect|condition|priority|description|is_active`; re-validates a supplied condition.
  - `delete_policy(policy_id, *, actor_id) -> None`.
  - `get_policy(policy_id) -> Policy` (raises `DomainError("policy not found", 404)`); `list_policies() -> list[Policy]` ordered by `-priority, permission`.
  - `evaluate_policy(tenant, *, permission, subject: dict, resource: dict, context: dict) -> dict` — ABAC-only dry run over the **supplied** `subject` (not the DB), returning `{"allowed": bool, "decided_by": str | None, "reason": str}`. `decided_by` is the id of the highest-priority `deny_if` that matched; else `None` with reason `"no allow_if matched"` when allows exist and none match; else the highest-priority matching `allow_if` id; else `None` reason `"no policy applies"`.
  - `set_user_attribute(user_id, key, value, *, actor_id) -> None` (upsert); `remove_user_attribute(user_id, key, *, actor_id) -> None`; `user_attributes(user_id) -> dict`.

- [ ] **Step 1: Write the failing tests**

```python
from django_tenants.utils import tenant_context
from easybiz.core.iam import service as iam
from easybiz.core.iam.policy import PolicyError
from easybiz.core.iam.enums import PolicyEffect

PERM = "timesheets.entry.approve"
GT = {"op": "gt", "left": {"var": "resource.hours"}, "right": {"var": "subject.approval_limit"}}

def test_create_rejects_invalid_condition(synced, db_tenant):
    with tenant_context(db_tenant):
        import pytest
        with pytest.raises(PolicyError):
            iam.create_policy(db_tenant, permission=PERM, effect=PolicyEffect.DENY_IF,
                              condition={"op": "regex", "left": {"var": "resource.x"}, "right": "a"}, actor_id=None)

def test_create_rejects_unknown_permission(synced, db_tenant):
    with tenant_context(db_tenant):
        import pytest
        with pytest.raises(PolicyError):
            iam.create_policy(db_tenant, permission="made.up.perm", effect=PolicyEffect.DENY_IF, condition=GT, actor_id=None)

def test_evaluate_dry_run_reports_decider(synced, db_tenant):
    with tenant_context(db_tenant):
        p = iam.create_policy(db_tenant, permission=PERM, effect=PolicyEffect.DENY_IF, condition=GT, priority=5, actor_id=None)
        hit = iam.evaluate_policy(db_tenant, permission=PERM, subject={"approval_limit": 8}, resource={"hours": 10}, context={})
        assert hit["allowed"] is False and hit["decided_by"] == str(p.id)
        miss = iam.evaluate_policy(db_tenant, permission=PERM, subject={"approval_limit": 8}, resource={"hours": 6}, context={})
        assert miss["allowed"] is True

def test_priority_orders_decider(synced, db_tenant):
    with tenant_context(db_tenant):
        iam.create_policy(db_tenant, permission=PERM, effect=PolicyEffect.DENY_IF, condition=GT, priority=1, actor_id=None)
        hi = iam.create_policy(db_tenant, permission=PERM, effect=PolicyEffect.DENY_IF, condition=GT, priority=9, actor_id=None)
        res = iam.evaluate_policy(db_tenant, permission=PERM, subject={"approval_limit": 8}, resource={"hours": 10}, context={})
        assert res["decided_by"] == str(hi.id)  # highest priority among matching denies

def test_policy_change_invalidates_authorize(synced, db_tenant):
    with tenant_context(db_tenant):
        from easybiz.core.iam.models import Role, RolePermission, UserRole, UserAttribute
        role = Role.objects.create(name="r"); RolePermission.objects.create(role=role, permission=PERM)
        uid = "33333333-3333-3333-3333-333333333333"; UserRole.objects.create(user_id=uid, role=role)
        UserAttribute.objects.create(user_id=uid, key="approval_limit", value=8)
        assert iam.authorize(uid, PERM, resource={"hours": 10}) is True   # warms the policy cache (empty)
        iam.create_policy(db_tenant, permission=PERM, effect=PolicyEffect.DENY_IF, condition=GT, actor_id=None)
        assert iam.authorize(uid, PERM, resource={"hours": 10}) is False  # bump took effect same process

def test_user_attribute_crud(synced, db_tenant):
    with tenant_context(db_tenant):
        uid = "44444444-4444-4444-4444-444444444444"
        iam.set_user_attribute(uid, "approval_limit", 8, actor_id=None)
        assert iam.user_attributes(uid) == {"approval_limit": 8}
        iam.set_user_attribute(uid, "approval_limit", 12, actor_id=None)  # upsert
        assert iam.user_attributes(uid) == {"approval_limit": 12}
        iam.remove_user_attribute(uid, "approval_limit", actor_id=None)
        assert iam.user_attributes(uid) == {}

def test_create_policy_writes_audit(synced, db_tenant):
    with tenant_context(db_tenant):
        from easybiz.core.audit.models import AuditLog
        iam.create_policy(db_tenant, permission=PERM, effect=PolicyEffect.DENY_IF, condition=GT, actor_id=None)
        assert AuditLog.objects.filter(action="policy.created").exists()
```

- [ ] **Step 2: Run them, verify they fail** — Run: `uv run pytest tests/test_iam_policy_service.py -q` — Expected: FAIL.
- [ ] **Step 3: Implement the write services and `evaluate_policy` in `service.py`.** `evaluate_policy` reuses the Task 3 decision logic but over the supplied `subject` and over `list_policies()` filtered by `_policy_matches_permission`, sorted by `-priority`.
- [ ] **Step 4: Run them, verify they pass** — Run: `uv run pytest tests/test_iam_policy_service.py -q` — Expected: PASS.
- [ ] **Step 5: Commit** — `git add easybiz/core/iam/service.py tests/test_iam_policy_service.py && git commit -m "Add policy/attribute write services and dry-run evaluate"`

---

### Task 5: Policy and attribute API endpoints

**Files:**
- Modify: `easybiz/core/kernel/core_permissions.py`
- Modify: `easybiz/core/api/types.py`
- Modify: `easybiz/core/api/core_routes.py`
- Test: `tests/test_core_policies_api.py`

**Interfaces:**
- Consumes: Task 4 services; `perm` guard; the central `DomainError`/`PolicyError` → status mapping (no per-handler try/except needed for `PolicyError`, but keep the existing `iam.RoleError` pattern for parity where a 422 should be explicit).
- Produces (types in `api/types.py`):
  - `PolicyIn(Schema)`: `permission: str`, `effect: str`, `condition: dict`, `priority: int = 0`, `description: str = ""`, `is_active: bool = True`.
  - `PolicyPatch(Schema)`: all of the above optional (`| None = None`).
  - `PolicyOut(Schema)`: `id: str`, `permission`, `effect`, `condition: dict`, `priority: int`, `description: str`, `is_active: bool`.
  - `EvaluateIn(Schema)`: `permission: str`, `subject: dict = {}`, `resource: dict = {}`, `context: dict = {}`.
  - `EvaluateOut(Schema)`: `allowed: bool`, `decided_by: str | None`, `reason: str`.
  - `AttributesIn(Schema)`: `attributes: dict`.
  - `AttributesOut(Schema)`: `attributes: dict`.
- Endpoints in `core_routes.py`, all `auth=perm("core.policy.manage")`:
  - `GET /policies` → `list[PolicyOut]`; `POST /policies` → `{201: PolicyOut}`; `GET /policies/{policy_id}` → `PolicyOut`; `PATCH /policies/{policy_id}` → `PolicyOut`; `DELETE /policies/{policy_id}` → `{204: None}`; `POST /policies/evaluate` → `EvaluateOut`.
  - `GET /users/{user_id}/attributes` → `AttributesOut`; `PUT /users/{user_id}/attributes` → `AttributesOut` (replace the full map: delete-then-set via `set_user_attribute`, or diff; a full replace within a `transaction.atomic()` is fine).
- `CORE_PERMISSIONS` gains `("core.policy.manage", "Create and edit access policies and user attributes")`.

- [ ] **Step 1: Write the failing tests** (reuse the `_owner`/`_req`/`_limited_token` helpers pattern from `tests/test_core_roles_write_api.py`)

```python
def test_requires_policy_manage(synced, provision):
    from easybiz.core.tenancy.models import Tenant
    _owner(provision, "pol1")  # provisions tenant + owner(*)
    tenant = Tenant.objects.get(slug="pol1")
    tok = _limited_token(tenant, ["core.user.read"])  # lacks core.policy.manage
    assert _req("get", "/api/core/policies", tok, "pol1").status_code == 403

def test_create_and_evaluate_policy(synced, provision):
    token = _owner(provision, "pol2")
    r = _req("post", "/api/core/policies", token, "pol2", {
        "permission": "timesheets.entry.approve", "effect": "deny_if",
        "condition": {"op": "gt", "left": {"var": "resource.hours"}, "right": {"var": "subject.approval_limit"}},
    })
    assert r.status_code == 201
    ev = _req("post", "/api/core/policies/evaluate", token, "pol2", {
        "permission": "timesheets.entry.approve", "subject": {"approval_limit": 8}, "resource": {"hours": 10},
    })
    assert ev.status_code == 200 and ev.json()["allowed"] is False

def test_invalid_condition_is_422(synced, provision):
    token = _owner(provision, "pol3")
    r = _req("post", "/api/core/policies", token, "pol3", {
        "permission": "timesheets.entry.approve", "effect": "deny_if",
        "condition": {"op": "regex", "left": {"var": "resource.x"}, "right": "a"},
    })
    assert r.status_code == 422

def test_user_attributes_put_get(synced, provision):
    token = _owner(provision, "pol4")
    uid = _req("get", "/api/core/users", token, "pol4").json()[0]["id"]
    put = _req("put", f"/api/core/users/{uid}/attributes", token, "pol4", {"attributes": {"approval_limit": 8}})
    assert put.status_code == 200 and put.json()["attributes"] == {"approval_limit": 8}
    got = _req("get", f"/api/core/users/{uid}/attributes", token, "pol4")
    assert got.json()["attributes"] == {"approval_limit": 8}

def test_policies_are_tenant_isolated(synced, provision):
    a = _owner(provision, "polA")
    _req("post", "/api/core/policies", a, "polA", {
        "permission": "timesheets.entry.approve", "effect": "deny_if",
        "condition": {"op": "gt", "left": {"var": "resource.hours"}, "right": {"var": "subject.approval_limit"}},
    })
    b = _owner(provision, "polB")
    assert _req("get", "/api/core/policies", b, "polB").json() == []  # tenant B sees none of A's policies
```

Note: `timesheets.entry.approve` must be an assignable permission in the tenants under test, so `_owner` must provision with `modules=("timesheets",)`. Provision those tenants with `modules=("timesheets",)` in `_owner` or a dedicated helper so the module's permissions are catalogued; otherwise `create_policy`'s permission check rejects it. Adjust `_owner` call sites to pass `modules=("timesheets",)`.

- [ ] **Step 2: Run them, verify they fail** — Run: `uv run pytest tests/test_core_policies_api.py -q` — Expected: FAIL.
- [ ] **Step 3: Add the permission, types, and thin handlers** (guard→parse→call service→shape, matching the existing role handlers; let `PolicyError`/`DomainError` propagate to the central handler).
- [ ] **Step 4: Run them, verify they pass** — Run: `uv run pytest tests/test_core_policies_api.py -q` — Expected: PASS.
- [ ] **Step 5: Verify the new core permission did not break existing permission tests** — Run: `uv run pytest tests/test_core_permissions.py tests/test_core_permissions_api.py -q` — Expected: PASS (update any exhaustive permission-list assertion to include `core.policy.manage`).
- [ ] **Step 6: Commit** — `git add -A && git commit -m "Add /core/policies and user-attribute endpoints under core.policy.manage"`

---

### Task 6: Demonstrate authorize() in timesheet approval

**Files:**
- Modify: `easybiz/modules/timesheets/commands.py`
- Test: `tests/test_timesheets_approval_limit.py`

**Interfaces:**
- Consumes: `easybiz.core.iam.service.authorize`.
- Behaviour: in `_review`, when `new_status == EntryStatus.APPROVED`, after the self-review and status checks, call `iam.authorize(params.reviewer_id, "timesheets.entry.approve", resource={"hours": float(entry.hours)})`; if it returns `False`, raise `TimesheetError("approval exceeds your approval limit", 403)`. A reviewer with no `approval_limit` attribute is unaffected (missing → the `deny_if` does not fire), so this is an opt-in limit per reviewer. Reject is not limit-gated.

- [ ] **Step 1: Write the failing tests** (service-level over a tenant with timesheets enabled; seed a deny_if policy + the reviewer's attribute, then approve over/under the limit; plus one HTTP smoke test driving `/api/core/policies`, `/api/core/users/{id}/attributes`, and `/api/timesheets/entries/{id}/approve`)

```python
# service-level: build a submitted entry, a reviewer holding timesheets.entry.approve with approval_limit=8,
# and a deny_if policy on hours > approval_limit.
def test_approve_over_limit_is_403(...):
    ...  # commands.approve_entry(...) raises TimesheetError status 403 for a 10h entry
def test_approve_within_limit_succeeds(...):
    ...  # a 6h entry approves (status -> approved)
def test_reviewer_without_limit_unaffected(...):
    ...  # reviewer with no approval_limit approves a 10h entry

def test_http_smoke_approval_limit(synced, provision):
    # owner creates the deny_if policy and sets the approver's approval_limit via /api/core/*,
    # an approver logs in and gets 403 on a 10h entry, 200 on a 6h entry.
    ...
```

(Flesh out the fixtures using the `provision(slug, modules=("timesheets",))` fixture, `encode_tenant_token`, and the timesheets query/command helpers; mirror existing timesheets tests for entry/project creation.)

- [ ] **Step 2: Run them, verify they fail** — Run: `uv run pytest tests/test_timesheets_approval_limit.py -q` — Expected: FAIL (approval not limited yet).
- [ ] **Step 3: Add the `authorize` call in `commands._review`.**
- [ ] **Step 4: Run them, verify they pass** — Run: `uv run pytest tests/test_timesheets_approval_limit.py -q` — Expected: PASS.
- [ ] **Step 5: Run the full suite** — Run: `uv run pytest -q` — Expected: all pass (F14a + Part A regressions green).
- [ ] **Step 6: Commit** — `git add easybiz/modules/timesheets/commands.py tests/test_timesheets_approval_limit.py && git commit -m "Gate timesheet approval on the approver's attribute limit via authorize()"`

---

## Post-implementation

- Update `README.md` Status with a short F14b paragraph (ABAC: policies, attributes, `authorize()`, the approval-limit demo).
- Update `ERP-CORE-SPEC.md` Appendix D if a new event is introduced (none is — policy changes only bump the cache + audit).
- **Security review before the PR** (standing instruction for auth/authz work): run `/security-review` on the branch, fix High/Medium findings, then open the PR with `gh` after `gh auth switch --user ImranZahoor`.
