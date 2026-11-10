from ninja import Schema


class LoginIn(Schema):
    email: str
    password: str


class TokenOut(Schema):
    access_token: str
    token_type: str = "bearer"
    expires_in: int


class MenuItemOut(Schema):
    module: str
    label: str
    route: str


class MeOut(Schema):
    id: str
    email: str
    permissions: list[str]
    menu: list[MenuItemOut]


class TenantSummary(Schema):
    slug: str
    name: str


class ContextOut(Schema):
    tenant: TenantSummary
    enabled_modules: list[str]


class ModuleOut(Schema):
    id: str
    name: str
    version: str
    status: str
    requires: list[str]
    optional: list[str]
    blocked_by: list[str]


class RoleIn(Schema):
    name: str
    description: str = ""
    permissions: list[str]


class RoleOut(Schema):
    id: str
    name: str
    description: str
    is_system: bool
    permissions: list[str]


class RoleUpdateIn(Schema):
    name: str | None = None
    description: str | None = None
    permissions: list[str] | None = None
    parent: str | None = None


class RoleCloneIn(Schema):
    name: str


class RoleDetailOut(Schema):
    id: str
    name: str
    description: str
    is_system: bool
    parent: str | None = None
    permissions: list[str]
    effective_permissions: list[str]


class PermissionItemOut(Schema):
    code: str
    description: str = ""


class PermissionGroupOut(Schema):
    module: str
    permissions: list[PermissionItemOut]


class UserIn(Schema):
    email: str
    password: str | None = None
    name: str = ""
    roles: list[str] = []


class UserOut(Schema):
    id: str
    email: str
    roles: list[str]


class UserRolesIn(Schema):
    roles: list[str]


class AuditOut(Schema):
    at: str
    actor_id: str | None
    action: str
    entity: str
    entity_id: str


class PolicyIn(Schema):
    permission: str
    effect: str
    condition: dict
    priority: int = 0
    description: str = ""
    is_active: bool = True


class PolicyPatch(Schema):
    permission: str | None = None
    effect: str | None = None
    condition: dict | None = None
    priority: int | None = None
    description: str | None = None
    is_active: bool | None = None


class PolicyOut(Schema):
    id: str
    permission: str
    effect: str
    condition: dict
    priority: int
    description: str
    is_active: bool


class EvaluateIn(Schema):
    permission: str
    subject: dict = {}
    resource: dict = {}
    context: dict = {}


class EvaluateOut(Schema):
    allowed: bool
    decided_by: str | None
    reason: str


class AttributesIn(Schema):
    attributes: dict


class AttributesOut(Schema):
    attributes: dict
