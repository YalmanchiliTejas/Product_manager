# app/mongo_utils.py
from __future__ import annotations

from datetime import datetime
from typing import Any

from bson import ObjectId


def to_jsonable(value: Any) -> Any:
    if isinstance(value, ObjectId):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, dict):
        return {k: to_jsonable(v) for k, v in value.items()}
    if isinstance(value, list):
        return [to_jsonable(v) for v in value]
    return value


def doc_to_json(doc: dict | None) -> dict | None:
    if not doc:
        return doc
    return to_jsonable(dict(doc))
