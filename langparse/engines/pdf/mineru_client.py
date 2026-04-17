from __future__ import annotations

import json
import mimetypes
import uuid
from pathlib import Path
from typing import Any
from urllib import request
from urllib.error import HTTPError, URLError


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
            fields["method"] = "txt"
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
                    f"--{boundary}".encode("utf-8"),
                    f'Content-Disposition: form-data; name="{name}"'.encode("utf-8"),
                    b"",
                    str(value).encode("utf-8"),
                ]
            )

        content_type = mimetypes.guess_type(file_path.name)[0] or "application/octet-stream"
        file_bytes = file_path.read_bytes()
        lines.extend(
            [
                f"--{boundary}".encode("utf-8"),
                f'Content-Disposition: form-data; name="files"; filename="{file_path.name}"'.encode(
                    "utf-8"
                ),
                f"Content-Type: {content_type}".encode("utf-8"),
                b"",
                file_bytes,
                f"--{boundary}--".encode("utf-8"),
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
            text_lines = [item.get("text", "") for item in items if item.get("text")]
            pages.append(
                {
                    "page_number": page_idx + 1,
                    "markdown": "\n".join(text_lines) or markdown,
                    "plain_text": "\n".join(text_lines),
                    "elements": [
                        {
                            "kind": item.get("type", "text"),
                            "text": item.get("text", ""),
                            "bbox": item.get("bbox"),
                            "metadata": {"page_idx": page_idx},
                        }
                        for item in items
                    ],
                    "engine_specific": {"content_list": items},
                }
            )
        return pages

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
        for candidate in candidates:
            if isinstance(candidate, str) and candidate:
                return candidate
        return ""

    def _extract_content_list(self, response: dict[str, Any]) -> list[dict[str, Any]]:
        for key in ("content_list", "content_list_v2"):
            value = response.get(key)
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
        return []
