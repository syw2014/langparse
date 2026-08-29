from __future__ import annotations

from .config import WorkbookModelConfig, resolve_workbook_model_config
from .ports import WorkbookModelResponseError, WorkbookStructureModelAdapter
from .types import ModelIdentity, ProviderReply, WorkbookModelRequest

_DECISION_COMMON_PROPERTIES = {
    "case_id": {"type": "string"},
    "status": {"type": "string"},
    "confidence": {"type": "number", "minimum": 0, "maximum": 1},
    "reason_codes": {"type": "array", "items": {"type": "string"}},
}

_WORKBOOK_RESPONSE_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["schema_version", "request_checksum", "decisions"],
    "properties": {
        "schema_version": {"type": "integer", "const": 1},
        "request_checksum": {"type": "string"},
        "decisions": {
            "type": "array",
            "minItems": 1,
            "maxItems": 1,
            "items": {
                "anyOf": [
                    {
                        "type": "object",
                        "additionalProperties": False,
                        "required": [
                            "case_id",
                            "status",
                            "choice_id",
                            "confidence",
                            "reason_codes",
                        ],
                        "properties": {
                            **_DECISION_COMMON_PROPERTIES,
                            "status": {"type": "string", "const": "selected"},
                            "choice_id": {"type": "string"},
                        },
                    },
                    {
                        "type": "object",
                        "additionalProperties": False,
                        "required": ["case_id", "status", "confidence", "reason_codes"],
                        "properties": {
                            **_DECISION_COMMON_PROPERTIES,
                            "status": {"type": "string", "const": "abstained"},
                        },
                    },
                ]
            },
        },
    },
}


class OpenAIWorkbookStructureAdapter(WorkbookStructureModelAdapter):
    """Adapter invoking OpenAI Chat Completions API for workbook structure disambiguation."""

    def __init__(self, config: WorkbookModelConfig) -> None:
        self._config = config
        self._identity = ModelIdentity(
            provider="openai",
            model=config.model,
            revision=None,
        )
        self._client = None

    @property
    def identity(self) -> ModelIdentity:
        return self._identity

    @property
    def config(self) -> WorkbookModelConfig:
        return self._config

    @classmethod
    def from_env(
        cls,
        *,
        cli_model: str | None = None,
        cli_api_key: str | None = None,
        cli_base_url: str | None = None,
        cli_timeout_seconds: float | None = None,
    ) -> OpenAIWorkbookStructureAdapter:
        config = resolve_workbook_model_config(
            cli_model=cli_model,
            cli_api_key=cli_api_key,
            cli_base_url=cli_base_url,
            cli_timeout_seconds=cli_timeout_seconds,
            from_env=True,
        )
        return cls(config)

    def _get_client(self, timeout_seconds: float):
        import openai

        if self._client is None:
            self._client = openai.OpenAI(
                api_key=self._config.api_key,
                base_url=self._config.base_url,
                timeout=timeout_seconds,
            )
        return self._client

    def complete(
        self,
        request: WorkbookModelRequest,
        *,
        timeout_seconds: float,
    ) -> ProviderReply:
        try:
            import openai

            if openai is None:
                raise ImportError("openai module is None")
        except (ImportError, TypeError) as exc:
            raise ImportError(
                "The 'openai' package is required for model disambiguation. "
                "Install it with 'pip install \"langparse[model]\"'."
            ) from exc

        effective_timeout = min(timeout_seconds, self._config.timeout_seconds)
        try:
            client = self._get_client(effective_timeout)
            response = client.chat.completions.create(
                model=self._config.model,
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "You are an Excel layout disambiguation adjudicator. "
                            "Analyze the cell cues, structural feature summary, and registered choice reasons, "
                            "then select the registered choice that best explains the region. "
                            "Use 'unclassified' only when no registered typed choice is supported by the facts. "
                            "Return only one JSON object matching the supplied response contract. "
                            "If you choose a registered choice_id, status MUST be exactly 'selected'. "
                            "If you do not choose one, status MUST be exactly 'abstained' and choice_id "
                            "MUST be omitted. Never use 'resolved', 'chosen', or any other status. "
                            "Copy schema_version, request_checksum, and case_id exactly from the request. "
                            "choice_id MUST be copied exactly from that case's registered choices."
                        ),
                    },
                    {
                        "role": "user",
                        "content": request.body.decode("utf-8"),
                    },
                ],
                response_format={
                    "type": "json_schema",
                    "json_schema": {
                        "name": "workbook_region_decision",
                        "strict": True,
                        "schema": _WORKBOOK_RESPONSE_SCHEMA,
                    },
                },
                seed=0,
                temperature=0,
                timeout=effective_timeout,
            )
        except Exception as exc:
            if isinstance(exc, ImportError):
                raise
            raise WorkbookModelResponseError(
                f"OpenAI completion failed ({type(exc).__name__})"
            ) from exc

        if not response.choices:
            raise WorkbookModelResponseError("OpenAI returned an empty choices list")

        message_content = response.choices[0].message.content or ""
        reply_body = message_content.encode("utf-8")

        usage_dict: dict[str, int] = {}
        if getattr(response, "usage", None) is not None:
            usage = response.usage
            if getattr(usage, "prompt_tokens", None) is not None:
                usage_dict["prompt_tokens"] = usage.prompt_tokens
            if getattr(usage, "completion_tokens", None) is not None:
                usage_dict["completion_tokens"] = usage.completion_tokens
            if getattr(usage, "total_tokens", None) is not None:
                usage_dict["total_tokens"] = usage.total_tokens

        provider_request_id = getattr(response, "id", None)

        return ProviderReply(
            body=reply_body,
            provider_request_id=provider_request_id,
            usage=usage_dict,
        )
