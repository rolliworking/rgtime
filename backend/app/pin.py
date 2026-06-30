"""PIN hashing and verification (4–6 digit staff-chosen PIN)."""

from __future__ import annotations

import re

import bcrypt

PIN_PATTERN = re.compile(r"^\d{4,6}$")


def validate_pin_format(pin: str) -> None:
    if not PIN_PATTERN.match(pin):
        raise ValueError("PIN must be 4–6 digits")


def hash_pin(pin: str) -> str:
    validate_pin_format(pin)
    return bcrypt.hashpw(pin.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_pin(pin: str, pin_hash: str) -> bool:
    try:
        return bcrypt.checkpw(pin.encode("utf-8"), pin_hash.encode("utf-8"))
    except ValueError:
        return False
