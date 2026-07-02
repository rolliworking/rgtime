"""Staff display names and initials-based staff_code suggestion."""

from __future__ import annotations

import re

_NON_ALPHA = re.compile(r"[^A-Za-z]")


def _name_initial(name: str) -> str:
    cleaned = _NON_ALPHA.sub("", (name or "").strip())
    return cleaned[0].upper() if cleaned else ""


def initials_staff_code(
    first_name: str,
    last_name: str,
    *,
    middle_name: str | None = None,
) -> tuple[str, str | None]:
    """
    Return (base_code, middle_disambiguation_code).
    base: first + last initial (MH). middle form: first + middle + last (MJH).
    """
    fi = _name_initial(first_name)
    li = _name_initial(last_name)
    if not fi or not li:
        return "STAFF", None
    base = f"{fi}{li}"
    middle = (middle_name or "").strip()
    mid_code = None
    if middle:
        mi = _name_initial(middle)
        if mi:
            mid_code = f"{fi}{mi}{li}"
    return base, mid_code


def staff_code_with_suffix(root: str, suffix: int) -> str:
    suffix_str = str(suffix)
    max_root = 16 - len(suffix_str)
    return f"{root[:max_root]}{suffix_str}"


def suggest_staff_code_sync(
    first_name: str,
    last_name: str,
    *,
    middle_name: str | None = None,
    code_exists: set[str] | None = None,
) -> str:
    """
    Pure suggestion logic for unit tests.
    code_exists: uppercase set of taken codes (active + terminated).
    """
    taken = code_exists or set()
    base, mid_code = initials_staff_code(first_name, last_name, middle_name=middle_name)

    if base not in taken:
        return base

    if mid_code and mid_code not in taken:
        return mid_code

    root = mid_code if mid_code else base
    suffix = 2
    while True:
        candidate = staff_code_with_suffix(root, suffix)
        if candidate not in taken:
            return candidate
        suffix += 1


def format_display_name(
    first_name: str,
    last_name: str,
    *,
    middle_name: str | None = None,
    short_middle: bool = False,
) -> str:
    first = (first_name or "").strip()
    last = (last_name or "").strip()
    middle = (middle_name or "").strip()
    if middle:
        if short_middle:
            return f"{first} {middle[0]}. {last}"
        return f"{first} {middle} {last}"
    return f"{first} {last}".strip()
