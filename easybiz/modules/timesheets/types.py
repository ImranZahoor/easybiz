from datetime import date
from decimal import Decimal

from ninja import Schema


class ProjectIn(Schema):
    code: str
    name: str


class ProjectOut(Schema):
    id: str
    code: str
    name: str
    is_active: bool


class EntryIn(Schema):
    project_id: str
    work_date: date
    hours: Decimal
    note: str = ""


class EntryOut(Schema):
    id: str
    user_id: str
    project_id: str
    work_date: str
    hours: str
    note: str
    status: str


class RejectIn(Schema):
    reason: str = ""
