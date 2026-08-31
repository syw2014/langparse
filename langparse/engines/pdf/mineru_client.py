from __future__ import annotations

import json
import mimetypes
import uuid
from html.parser import HTMLParser
from pathlib import Path
from typing import Any
from urllib import request
from urllib.error import HTTPError, URLError


class _HTMLTableReader(HTMLParser):
    """Collects rows/cells from the HTML fragment MinerU returns as ``table_body``."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.rows: list[list[str]] = []
        self._row: list[str] | None = None
        self._cell: list[str] | None = None

    def handle_starttag(self, tag, attrs):
        if tag == "tr":
            self._row = []
        elif tag in ("td", "th"):
            self._cell = []

    def handle_endtag(self, tag):
        if tag in ("td", "th") and self._cell is not None:
            text = " ".join("".join(self._cell).split())
            if self._row is None:
                self._row = []
            self._row.append(text)
            self._cell = None
        elif tag == "tr" and self._row is not None:
            self.rows.append(self._row)
            self._row = None

    def handle_data(self, data):
        if self._cell is not None:
            self._cell.append(data)


def parse_html_table(markup: str) -> list[list[str]]:
    """Parse an HTML table fragment into rows of cell text. Returns [] if unparseable."""
    if not markup:
        return []
    reader = _HTMLTableReader()
    try:
        reader.feed(markup)
        reader.close()
    except Exception:
        return []
    return [row for row in reader.rows if row]


def rows_to_markdown(rows: list[list[str]]) -> str:
    """Render rows as a Markdown table, padding short rows to the header width."""
    if not rows:
        return ""
    width = max(len(row) for row in rows)
    padded = [row + [""] * (width - len(row)) for row in rows]
    lines = [f"| {' | '.join(padded[0])} |", f"| {' | '.join(['---'] * width)} |"]
    lines.extend(f"| {' | '.join(row)} |" for row in padded[1:])
    return "\n".join(lines)


class MinerUClient:
    def __init__(self, base_url: str, timeout: float = 300.0):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def health(self) -> dict[str, Any]:
        return self._request_json("GET", "/health")

    def parse_file(self, file_path: Path, runtime_config: dict[str, Any]) -> list[dict[str, Any]]:
        response = self._request_json(
            "POST",
            "/file_parse",
            fields=self._build_form_fields(runtime_config),
            file_path=file_path,
        )
        return self._normalize_parse_response(response)

    def _build_form_fields(self, runtime_config: dict[str, Any]) -> dict[str, str]:
        fields = {
            "return_md": "true",
            "response_format_zip": "false",
        }
        extra_options = runtime_config.get("extra_options", {})
        if runtime_config.get("enable_ocr") is False:
            fields["parse_method"] = "txt"
        if runtime_config.get("device"):
            fields["device"] = str(runtime_config["device"])
        if runtime_config.get("model_dir"):
            fields["model_dir"] = str(runtime_config["model_dir"])
        if runtime_config.get("download_dir"):
            fields["download_dir"] = str(runtime_config["download_dir"])
        for key, value in extra_options.items():
            if value is None:
                continue
            fields[str(key)] = str(value)
        return fields

    def _request_json(
        self,
        method: str,
        path: str,
        fields: dict[str, str] | None = None,
        file_path: Path | None = None,
    ) -> dict[str, Any]:
        headers = {"Accept": "application/json"}
        data = None
        if file_path is not None:
            data, content_type = self._encode_multipart_form(fields or {}, file_path)
            headers["Content-Type"] = content_type

        req = request.Request(
            f"{self.base_url}{path}",
            data=data,
            headers=headers,
            method=method,
        )
        try:
            with request.urlopen(req, timeout=self.timeout) as response:
                payload = response.read().decode("utf-8")
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"MinerU API request failed with HTTP {exc.code}: {detail}") from exc
        except URLError as exc:
            raise RuntimeError(f"MinerU API request failed: {exc.reason}") from exc

        try:
            return json.loads(payload)
        except json.JSONDecodeError as exc:
            raise RuntimeError("MinerU API returned a non-JSON response.") from exc

    def _encode_multipart_form(self, fields: dict[str, str], file_path: Path) -> tuple[bytes, str]:
        boundary = f"----langparse-mineru-{uuid.uuid4().hex}"
        lines: list[bytes] = []
        for name, value in fields.items():
            lines.extend(
                [
                    f"--{boundary}".encode(),
                    f'Content-Disposition: form-data; name="{name}"'.encode(),
                    b"",
                    str(value).encode("utf-8"),
                ]
            )

        content_type = mimetypes.guess_type(file_path.name)[0] or "application/octet-stream"
        file_bytes = file_path.read_bytes()
        lines.extend(
            [
                f"--{boundary}".encode(),
                f'Content-Disposition: form-data; name="files"; filename="{file_path.name}"'.encode(),
                f"Content-Type: {content_type}".encode(),
                b"",
                file_bytes,
                f"--{boundary}--".encode(),
                b"",
            ]
        )
        return b"\r\n".join(lines), f"multipart/form-data; boundary={boundary}"

    def _normalize_parse_response(self, response: dict[str, Any]) -> list[dict[str, Any]]:
        markdown = self._extract_markdown(response)
        content_list = self._extract_content_list(response)
        if not content_list:
            return [{"page_number": 1, "markdown": markdown}]

        page_map: dict[int, list[dict[str, Any]]] = {}
        for item in content_list:
            page_idx = int(item.get("page_idx", 0))
            page_map.setdefault(page_idx, []).append(item)

        pages = []
        for page_idx in sorted(page_map):
            items = page_map[page_idx]
            pages.append(self._build_page(page_idx, items, markdown))
        return pages

    def _build_page(
        self, page_idx: int, items: list[dict[str, Any]], document_markdown: str
    ) -> dict[str, Any]:
        markdown_blocks: list[str] = []
        text_lines: list[str] = []
        tables: list[dict[str, Any]] = []
        images: list[dict[str, Any]] = []
        elements: list[dict[str, Any]] = []

        for item in items:
            kind = item.get("type", "text")
            caption = self._join_caption(item.get(f"{kind}_caption"))

            if kind == "table":
                rows = parse_html_table(item.get("table_body", ""))
                table_markdown = rows_to_markdown(rows)
                tables.append(
                    {
                        "rows": rows,
                        "caption": caption,
                        "html": item.get("table_body", ""),
                        "img_path": item.get("img_path"),
                    }
                )
                block = "\n\n".join(part for part in (caption, table_markdown) if part)
                if block:
                    markdown_blocks.append(block)
                element_text = table_markdown
            elif kind == "image":
                images.append(
                    {
                        "path": item.get("img_path"),
                        "caption": caption,
                        "footnote": self._join_caption(item.get("image_footnote")),
                    }
                )
                block = f"![{caption}]({item.get('img_path') or ''})"
                markdown_blocks.append(block)
                element_text = caption
            else:
                text = item.get("text", "")
                if text:
                    markdown_blocks.append(text)
                    text_lines.append(text)
                element_text = text

            elements.append(
                {
                    "kind": kind,
                    "text": element_text,
                    "bbox": item.get("bbox"),
                    "metadata": {"page_idx": page_idx},
                }
            )

        return {
            "page_number": page_idx + 1,
            "markdown": "\n\n".join(markdown_blocks) or document_markdown,
            "plain_text": "\n".join(text_lines),
            "elements": elements,
            "tables": tables,
            "images": images,
            "engine_specific": {"content_list": items},
        }

    def _join_caption(self, caption: Any) -> str:
        if isinstance(caption, str):
            return caption.strip()
        if isinstance(caption, list):
            return " ".join(str(part).strip() for part in caption if str(part).strip())
        return ""

    def _extract_markdown(self, response: dict[str, Any]) -> str:
        candidates = [
            response.get("md_content"),
            response.get("markdown"),
            response.get("md"),
            response.get("full_md"),
        ]
        result = response.get("result")
        if isinstance(result, dict):
            candidates.extend(
                [
                    result.get("md_content"),
                    result.get("markdown"),
                    result.get("md"),
                    result.get("full_md"),
                ]
            )
        results = response.get("results")
        if isinstance(results, dict):
            for file_result in results.values():
                if isinstance(file_result, dict):
                    candidates.extend(
                        [
                            file_result.get("md_content"),
                            file_result.get("markdown"),
                            file_result.get("md"),
                            file_result.get("full_md"),
                        ]
                    )
        for candidate in candidates:
            if isinstance(candidate, str) and candidate:
                return candidate
        return ""

    def _extract_content_list(self, response: dict[str, Any]) -> list[dict[str, Any]]:
        for key in ("content_list", "content_list_v2"):
            value = response.get(key)
            if isinstance(value, str):
                try:
                    value = json.loads(value)
                except json.JSONDecodeError:
                    continue
            if isinstance(value, list):
                if value and isinstance(value[0], dict):
                    return value
                if value and isinstance(value[0], list):
                    flattened = []
                    for page_idx, page_items in enumerate(value):
                        for item in page_items:
                            if isinstance(item, dict):
                                flattened.append({"page_idx": page_idx, **item})
                    return flattened
        result = response.get("result")
        if isinstance(result, dict):
            return self._extract_content_list(result)
        results = response.get("results")
        if isinstance(results, dict):
            for file_result in results.values():
                if isinstance(file_result, dict):
                    content_list = self._extract_content_list(file_result)
                    if content_list:
                        return content_list
        return []
