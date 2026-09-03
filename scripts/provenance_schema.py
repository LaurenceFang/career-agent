#!/usr/bin/env python3
"""Canonical provenance validation shared by the gate and the tests.

Mirrors schemas/provenance.schema.json without a third-party validator so the
core pipeline stays stdlib-only. If that schema file changes, update this to
match (tests/test_provenance_schema.py checks the required-key lists agree).
"""

from __future__ import annotations

from pathlib import Path

BULLET_REQUIRED = {
    "bullet_id": str,
    "text": str,
    "fact_ids": list,
    "evidence_paths": list,
}

MANIFEST_REQUIRED = {"job_id": str, "bullets": list}


def validate_manifest(data: dict) -> list[str]:
    errors: list[str] = []
    for field, typ in MANIFEST_REQUIRED.items():
        value = data.get(field)
        if not isinstance(value, typ):
            errors.append(f"Provenance manifest: {field} missing or not a {typ.__name__}.")
    if not isinstance(data.get("bullets"), list) or not data.get("bullets"):
        errors.append("Provenance manifest: bullets must be a non-empty list.")
        return errors
    for position, item in enumerate(data.get("bullets", [])):
        where = f"bullet #{position + 1}"
        if isinstance(item, dict) and item.get("bullet_id"):
            where = str(item["bullet_id"])
        if not isinstance(item, dict):
            errors.append(f"Schema violation: {where} is not an object.")
            continue
        for field, typ in BULLET_REQUIRED.items():
            value = item.get(field)
            if value is None:
                errors.append(f"Schema violation: {field} missing on {where}.")
            elif not isinstance(value, typ):
                errors.append(f"Schema violation: {field} has wrong type on {where}.")
            elif isinstance(value, list):
                if not value:
                    errors.append(f"Schema violation: {field} is empty on {where}.")
                elif not all(isinstance(x, str) and x for x in value):
                    errors.append(f"Schema violation: {field} must be a list of non-empty strings on {where}.")
    return errors
