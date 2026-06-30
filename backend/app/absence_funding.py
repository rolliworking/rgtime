"""Absence reason funding axis — locked rules §4."""

from __future__ import annotations

from typing import Literal

AbsenceFunding = Literal[
    "paid_outright",
    "paid_from_pto",
    "unpaid_pto_coverable",
    "unpaid",
]

FUNDING_VALUES: frozenset[str] = frozenset(
    {"paid_outright", "paid_from_pto", "unpaid_pto_coverable", "unpaid"}
)
