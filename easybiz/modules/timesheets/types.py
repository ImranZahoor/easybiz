from ninja import Schema


class ProjectIn(Schema):
    code: str
    name: str


class ProjectOut(Schema):
    id: str
    code: str
    name: str
    is_active: bool
