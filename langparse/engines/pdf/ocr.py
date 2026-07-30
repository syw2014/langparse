"""
OCR fallback for PDF pages whose content is an image rather than text.

The dangerous case is not an empty page -- it is a scanned page carrying a
watermark, which leaves just enough extracted text that the parse reports
success while the actual content is never read. Detection therefore looks for
"almost no text next to an image", not "no text".
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Protocol

#: A full page of body text runs well over a thousand characters. This is the
#: ceiling below which a page covered by an image is treated as a scan rather
#: than as text -- data/domain/scan.pdf carries 145 characters of watermark.
DEFAULT_MIN_CHARS = 500
#: Fraction of the page an image must cover before the page counts as scanned.
DEFAULT_MIN_IMAGE_COVERAGE = 0.5
DEFAULT_RESOLUTION = 150


class Recogniser(Protocol):
    """Matches rapidocr_onnxruntime's RapidOCR call signature."""

    def __call__(self, image: Any) -> tuple[Any, Any]: ...


def image_coverage(page) -> float:
    """Largest single image's area as a fraction of the page."""
    images = getattr(page, "images", None)
    if not images:
        return 0.0

    page_area = (getattr(page, "width", 0) or 0) * (getattr(page, "height", 0) or 0)
    if page_area <= 0:
        return 0.0

    largest = 0.0
    for image in images:
        width = abs(float(image.get("x1", 0)) - float(image.get("x0", 0)))
        height = abs(float(image.get("bottom", 0)) - float(image.get("top", 0)))
        largest = max(largest, width * height)
    return min(1.0, largest / page_area)


def needs_ocr(
    page,
    min_chars: int = DEFAULT_MIN_CHARS,
    min_image_coverage: float = DEFAULT_MIN_IMAGE_COVERAGE,
) -> bool:
    """
    Whether a page's text layer is too thin to trust.

    Text length alone is not enough: data/domain/scan.pdf carries 145 characters
    of rotated watermark per page, which clears any threshold low enough to
    avoid firing on genuinely sparse text pages. The page-covering image is the
    signal that distinguishes them, so both conditions must hold.
    """
    if image_coverage(page) < min_image_coverage:
        return False

    text = page.extract_text() or ""
    return len(text.strip()) < min_chars


def ocr_page_text(
    page,
    recogniser: Recogniser,
    resolution: int = DEFAULT_RESOLUTION,
) -> str:
    """Rasterise a page and return the recognised text, one line per detection."""
    image = page.to_image(resolution=resolution).original
    result, _elapsed = recogniser(image)
    if not result:
        return ""

    lines = []
    for detection in result:
        # rapidocr yields [box, text, score]; be tolerant of shape changes.
        if isinstance(detection, (list, tuple)) and len(detection) >= 2:
            text = detection[1]
        else:
            text = detection
        if isinstance(text, str) and text.strip():
            lines.append(text.strip())
    return "\n".join(lines)


def load_recogniser() -> Callable[[Any], tuple[Any, Any]]:
    """Build the default rapidocr recogniser, with an actionable error if absent."""
    try:
        from rapidocr_onnxruntime import RapidOCR
    except ImportError as exc:
        raise ImportError(
            "OCR fallback needs rapidocr_onnxruntime. Install it with "
            '`pip install "langparse[ocr]"`, or pass enable_ocr=False to skip it.'
        ) from exc

    return RapidOCR()
