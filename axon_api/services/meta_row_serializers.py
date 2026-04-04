"""Simple row serializers for prompt and memory records extracted from server.py."""
from __future__ import annotations


def serialize_prompt(row, *, loads_json_object_fn) -> dict:
    item = dict(row)
    item["meta"] = loads_json_object_fn(item.get("meta_json"))
    return item


def serialize_memory_item(row, *, loads_json_object_fn) -> dict:
    item = dict(row)
    item["meta"] = loads_json_object_fn(item.get("meta_json"))
    item["pinned"] = bool(item.get("pinned"))
    return item
