from __future__ import annotations

import math
import os
from dataclasses import dataclass
from numbers import Real

from .ports import WorkbookModelConfigurationError


@dataclass(frozen=True)
class WorkbookModelConfig:
    api_key: str
    model: str
    base_url: str | None = None
    timeout_seconds: float = 20.0

    def __post_init__(self) -> None:
        api_key = self.api_key.strip() if isinstance(self.api_key, str) else ""
        model = self.model.strip() if isinstance(self.model, str) else ""
        if not api_key:
            raise WorkbookModelConfigurationError("api_key must be a non-empty string")
        if not model:
            raise WorkbookModelConfigurationError("model must be a non-empty string")
        if (
            isinstance(self.timeout_seconds, bool)
            or not isinstance(self.timeout_seconds, Real)
            or not math.isfinite(self.timeout_seconds)
            or self.timeout_seconds <= 0
        ):
            raise WorkbookModelConfigurationError("timeout_seconds must be a finite positive real")
        base_url = self.base_url.strip() if isinstance(self.base_url, str) else self.base_url
        object.__setattr__(self, "api_key", api_key)
        object.__setattr__(self, "model", model)
        object.__setattr__(self, "base_url", base_url or None)

    def __repr__(self) -> str:
        return (
            f"WorkbookModelConfig(model={self.model!r}, "
            "api_key='***', "
            f"base_url={self.base_url!r}, "
            f"timeout_seconds={self.timeout_seconds})"
        )


def resolve_workbook_model_config(
    *,
    cli_model: str | None = None,
    cli_api_key: str | None = None,
    cli_base_url: str | None = None,
    cli_timeout_seconds: float | None = None,
    from_env: bool = True,
) -> WorkbookModelConfig:
    """Resolve workbook model configuration with CLI args taking precedence over environment variables."""

    api_key_candidate = (
        cli_api_key
        if cli_api_key is not None
        else (os.environ.get("OPENAI_API_KEY") if from_env else None)
    )
    api_key = api_key_candidate.strip() if isinstance(api_key_candidate, str) else ""
    if not api_key:
        raise WorkbookModelConfigurationError(
            "OPENAI_API_KEY is required for model disambiguation. "
            "Set it via the environment or inject WorkbookModelConfig programmatically."
        )

    model_candidate = cli_model.strip() if cli_model is not None else ""
    model = model_candidate or (os.environ.get("OPENAI_MODEL", "").strip() if from_env else "")
    if not model:
        raise WorkbookModelConfigurationError(
            "OPENAI_MODEL is required for model disambiguation. "
            "Set it via environment variable or pass --model <name>."
        )

    base_url = cli_base_url or (os.environ.get("OPENAI_BASE_URL") if from_env else None)
    if base_url:
        base_url = base_url.strip() or None

    timeout_seconds = cli_timeout_seconds if cli_timeout_seconds is not None else 20.0

    return WorkbookModelConfig(
        api_key=api_key,
        model=model,
        base_url=base_url,
        timeout_seconds=timeout_seconds,
    )
