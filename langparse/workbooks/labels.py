"""Explicit row labels shared by region detection and table interpretation."""

import re

_SECTION_LABEL = re.compile(r"^[一二三四五六七八九十百]+[、．.]\s*\S")
_TOTAL_LABEL = re.compile(r"(?:合计|小计|总计)(?:[:：]|[=＝].*|[（(\[].*[）)\]])?$")


def is_section_label(value: str) -> bool:
    return bool(_SECTION_LABEL.match(value.strip()))


def is_total_label(value: str) -> bool:
    return bool(_TOTAL_LABEL.search(re.sub(r"\s+", "", value)))
