from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


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


@dataclass
class ClassifiedError:
    error_type: ErrorType
    message: str


def classify_exception(exc: BaseException) -> ClassifiedError:
    message = str(exc)
    lowered = message.lower()

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
    if "timed out" in lowered or "timeout" in lowered:
        return ClassifiedError(ErrorType.ENGINE_TIMEOUT, message)
    if "ocr" in lowered and "unavailable" in lowered:
        return ClassifiedError(ErrorType.OCR_UNAVAILABLE, message)
    if "table" in lowered and "failed" in lowered:
        return ClassifiedError(ErrorType.TABLE_EXTRACTION_FAILED, message)

    return ClassifiedError(ErrorType.PARSE_FAILED, message)
