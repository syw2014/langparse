import os
from pathlib import Path

import pytest

from langparse.services.parse_service import ParseService


def _live_mineru_config() -> tuple[str, str, Path] | None:
    api_url = os.environ.get("LANGPARSE_MINERU_API_URL")
    server_url = os.environ.get("LANGPARSE_MINERU_SERVER_URL")
    test_pdf = os.environ.get("LANGPARSE_MINERU_TEST_PDF")
    if not api_url or not server_url or not test_pdf:
        return None
    return api_url, server_url, Path(test_pdf)


@pytest.mark.skipif(
    _live_mineru_config() is None,
    reason="Live MinerU integration environment is not configured",
)
def test_live_mineru_parses_markdown_and_structured_content():
    config = _live_mineru_config()
    assert config is not None
    api_url, server_url, test_pdf = config
    assert test_pdf.is_file()

    result = ParseService().parse_result(
        test_pdf,
        engine_name="mineru",
        api_url=api_url,
        request_timeout=1200,
        extra_options={
            "backend": "vlm-http-client",
            "server_url": server_url,
            "return_content_list": True,
        },
    )

    assert result.engine == "mineru"
    assert result.markdown_content.strip()
    assert result.pages
    assert any(page.elements for page in result.pages)
