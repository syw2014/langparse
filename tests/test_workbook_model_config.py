from __future__ import annotations

import os
from unittest import mock

import pytest

from langparse.workbooks.modeling.config import (
    WorkbookModelConfig,
    resolve_workbook_model_config,
)
from langparse.workbooks.modeling.ports import WorkbookModelConfigurationError


def test_resolve_config_from_explicit_cli_args():
    config = resolve_workbook_model_config(
        cli_model="gpt-4o",
        cli_api_key="sk-cli-key",
        cli_base_url="https://custom.api.com/v1",
        cli_timeout_seconds=30.0,
    )
    assert isinstance(config, WorkbookModelConfig)
    assert config.model == "gpt-4o"
    assert config.api_key == "sk-cli-key"
    assert config.base_url == "https://custom.api.com/v1"
    assert config.timeout_seconds == 30.0


def test_resolve_config_from_env_vars():
    env = {
        "OPENAI_API_KEY": "sk-env-key",
        "OPENAI_MODEL": "gpt-4o-mini",
        "OPENAI_BASE_URL": "https://env.api.com/v1",
    }
    with mock.patch.dict(os.environ, env, clear=True):
        config = resolve_workbook_model_config()
        assert config.model == "gpt-4o-mini"
        assert config.api_key == "sk-env-key"
        assert config.base_url == "https://env.api.com/v1"
        assert config.timeout_seconds == 20.0


def test_cli_args_override_env_vars():
    env = {
        "OPENAI_API_KEY": "sk-env-key",
        "OPENAI_MODEL": "gpt-4o-mini",
        "OPENAI_BASE_URL": "https://env.api.com/v1",
    }
    with mock.patch.dict(os.environ, env, clear=True):
        # Override only model and base_url, keep api_key from env
        config = resolve_workbook_model_config(
            cli_model="gpt-4o-override",
            cli_base_url="https://cli.api.com/v1",
        )
        assert config.model == "gpt-4o-override"
        assert config.api_key == "sk-env-key"
        assert config.base_url == "https://cli.api.com/v1"


def test_empty_cli_model_falls_back_to_env():
    env = {
        "OPENAI_API_KEY": "sk-env-key",
        "OPENAI_MODEL": "gpt-4o-env-default",
    }
    with mock.patch.dict(os.environ, env, clear=True):
        # Passing cli_model="" (e.g. from nargs="?" const="")
        config = resolve_workbook_model_config(cli_model="")
        assert config.model == "gpt-4o-env-default"
        assert config.api_key == "sk-env-key"


def test_missing_api_key_raises_configuration_error():
    with mock.patch.dict(os.environ, {}, clear=True):
        with pytest.raises(WorkbookModelConfigurationError) as exc_info:
            resolve_workbook_model_config(cli_model="gpt-4o")
        assert "OPENAI_API_KEY" in str(exc_info.value)


def test_whitespace_api_key_is_rejected():
    with mock.patch.dict(os.environ, {}, clear=True):
        with pytest.raises(WorkbookModelConfigurationError, match="OPENAI_API_KEY"):
            resolve_workbook_model_config(
                cli_model="gpt-4o",
                cli_api_key="   ",
            )


def test_direct_model_config_rejects_blank_credentials():
    with pytest.raises(WorkbookModelConfigurationError, match="api_key"):
        WorkbookModelConfig(api_key="   ", model="gpt-4o")
    with pytest.raises(WorkbookModelConfigurationError, match="model"):
        WorkbookModelConfig(api_key="sk-test", model="   ")


def test_missing_model_raises_configuration_error():
    env = {"OPENAI_API_KEY": "sk-test"}
    with mock.patch.dict(os.environ, env, clear=True):
        with pytest.raises(WorkbookModelConfigurationError) as exc_info:
            resolve_workbook_model_config()
        assert "OPENAI_MODEL" in str(exc_info.value)


def test_api_key_masked_in_repr_and_str():
    config = WorkbookModelConfig(
        api_key="sk-1234567890abcdef",
        model="gpt-4o",
        base_url=None,
    )
    repr_str = repr(config)
    assert "sk-1234567890abcdef" not in repr_str
    assert "sk-" not in repr_str
    assert "def" not in repr_str
    assert "***" in repr_str
