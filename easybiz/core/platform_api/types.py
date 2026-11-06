from ninja import Schema


class PlatformLoginIn(Schema):
    email: str
    password: str


class PlatformTokenOut(Schema):
    access_token: str
    token_type: str = "bearer"
    expires_in: int


class PlatformMeOut(Schema):
    id: str
    email: str


class DomainOut(Schema):
    domain: str
    is_primary: bool


class TenantModuleOut(Schema):
    module: str
    status: str
    installed_version: str = ""


class TenantOut(Schema):
    slug: str
    name: str
    schema_name: str
    is_active: bool
    created_at: str
    domains: list[DomainOut]
    modules: list[TenantModuleOut]
    member_count: int


class TenantListOut(Schema):
    count: int
    items: list[TenantOut]


class OverviewOut(Schema):
    tenants_total: int
    tenants_active: int
    tenants_suspended: int
    platform_admins: int
    modules_installed: int


class TenantCreateIn(Schema):
    name: str
    slug: str
    domain: str
    owner_email: str
    owner_password: str | None = None
    modules: list[str] = []


class TenantRenameIn(Schema):
    name: str


class DomainIn(Schema):
    domain: str
    is_primary: bool = False
