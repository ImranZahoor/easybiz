"""Ninja request/response schemas for the tenant API."""

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
    enabled_modules: list[str]
    menu: list[MenuItemOut]


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


class UserIn(Schema):
    email: str
    password: str | None = None
    name: str = ""
    roles: list[str] = []


class UserOut(Schema):
    id: str
    email: str
    roles: list[str]
