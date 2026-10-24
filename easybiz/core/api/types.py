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
