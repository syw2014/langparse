from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum
from subprocess import TimeoutExpired
from urllib.error import URLError


class ErrorType(str, Enum):
    DEPENDENCY_MISSING = "dependency_missing"
    FILE_NOT_FOUND = "file_not_found"
    UNSUPPORTED_FORMAT = "unsupported_format"
    ENGINE_UNAVAILABLE = "engine_unavailable"
    ENGINE_TIMEOUT = "engine_timeout"
    PARSE_FAILED = "parse_failed"
    QUALITY_CHECK_FAILED = "quality_check_failed"
    OCR_UNAVAILABLE = "ocr_unavailable"
    LAYOUT_QUALITY_WARNING = "layout_quality_warning"
    TABLE_EXTRACTION_FAILED = "table_extraction_failed"
    WORKBOOK_EVALUATION_FAILED = "workbook_evaluation_failed"


@dataclass
class ClassifiedError:
    error_type: ErrorType
    message: str


def classify_exception(exc: BaseException) -> ClassifiedError:
    message = str(exc)
    lowered = message.lower()

    from langparse.workbooks.evaluation.schema import WorkbookEvaluationError

    if isinstance(exc, WorkbookEvaluationError):
        return ClassifiedError(ErrorType.WORKBOOK_EVALUATION_FAILED, message)
    if isinstance(exc, FileNotFoundError):
        return ClassifiedError(ErrorType.FILE_NOT_FOUND, message)
    if isinstance(exc, ImportError):
        return ClassifiedError(ErrorType.DEPENDENCY_MISSING, message)
    if "unsupported file extension" in lowered:
        return ClassifiedError(ErrorType.UNSUPPORTED_FORMAT, message)
    if "cuda" in lowered and "not available" in lowered:
        return ClassifiedError(ErrorType.ENGINE_UNAVAILABLE, message)
    if "unable to start local mineru-api" in lowered:
        return ClassifiedError(ErrorType.ENGINE_UNAVAILABLE, message)
    if _is_timeout(exc) or re.search(r"\btimed out\b", lowered):
        return ClassifiedError(ErrorType.ENGINE_TIMEOUT, message)
    if "ocr" in lowered and "unavailable" in lowered:
        return ClassifiedError(ErrorType.OCR_UNAVAILABLE, message)
    if "table" in lowered and "failed" in lowered:
        return ClassifiedError(ErrorType.TABLE_EXTRACTION_FAILED, message)

    return ClassifiedError(ErrorType.PARSE_FAILED, message)


def _is_timeout(exc: BaseException) -> bool:
    """Recognize standard timeout types through explicit backend wrappers."""
    seen: set[int] = set()
    current: BaseException | None = exc
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        if isinstance(current, (TimeoutError, TimeoutExpired)):
            return True
        if isinstance(current, URLError) and isinstance(current.reason, BaseException):
            current = current.reason
        else:
            current = current.__cause__
    return False
