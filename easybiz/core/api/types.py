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
