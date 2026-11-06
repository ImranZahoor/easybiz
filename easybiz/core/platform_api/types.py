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
