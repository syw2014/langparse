import copy
import json
import os
from pathlib import Path
from typing import Any, Dict


class Config:
    """
    Global configuration manager for LangParse.
    Priorities:
    1. Runtime kwargs (passed to functions)
    2. Environment variables (LANGPARSE_*)
    3. Config file (~/.langparse/config.json)
    4. Defaults
    """

    ENV_MAP = {
        "LANGPARSE_DEFAULT_PDF_ENGINE": "default_pdf_engine",
        "LANGPARSE_MINERU_DEVICE": "engines.mineru.device",
        "LANGPARSE_MINERU_MODEL_DIR": "engines.mineru.model_dir",
        "LANGPARSE_MINERU_DOWNLOAD_DIR": "engines.mineru.download_dir",
        "LANGPARSE_MINERU_ENABLE_OCR": "engines.mineru.enable_ocr",
    }

    DEFAULT_CONFIG = {
        "default_pdf_engine": "simple",
        "engines": {
            "mineru": {
                "device": "auto",
                "model_dir": None,
                "download_dir": None,
                "enable_ocr": True,
                "extra_options": {},
            },
            "vision_llm": {
                "provider": "openai",
                "model": "gpt-4o",
                "api_key": None,
            },
        },
    }

    def __init__(self):
        self._config = copy.deepcopy(self.DEFAULT_CONFIG)
        self._load_from_file()
        self._load_from_env()

    def _load_from_file(self):
        config_path = Path.home() / ".langparse" / "config.json"
        if config_path.exists():
            try:
                with open(config_path, "r", encoding="utf-8") as f:
                    user_config = json.load(f)
                    self._merge_dict(self._config, user_config)
            except Exception as e:
                print(f"Warning: Failed to load config file: {e}")

    def _load_from_env(self):
        for env_key, config_key in self.ENV_MAP.items():
            if env_key not in os.environ:
                continue
            current_value = self.get(config_key)
            parsed_value = self._parse_env_value(os.environ[env_key], current_value)
            self._set_nested_value(config_key, parsed_value)

    def _parse_env_value(self, value: str, current_value: Any = None) -> Any:
        normalized = value.strip()
        lowered = normalized.lower()

        if isinstance(current_value, bool):
            if lowered in {"true", "1", "yes", "on"}:
                return True
            if lowered in {"false", "0", "no", "off"}:
                return False

        if current_value is None and lowered in {"null", "none", ""}:
            return None

        try:
            return json.loads(normalized)
        except json.JSONDecodeError:
            return normalized

    def _set_nested_value(self, key: str, value: Any) -> None:
        keys = key.split(".")
        target = self._config
        for part in keys[:-1]:
            if part not in target or not isinstance(target[part], dict):
                target[part] = {}
            target = target[part]
        target[keys[-1]] = value

    def _merge_dict(self, base: Dict, update: Dict):
        for k, v in update.items():
            if k in base and isinstance(base[k], dict) and isinstance(v, dict):
                self._merge_dict(base[k], v)
            else:
                base[k] = v

    def resolve_engine_config(self, engine_name: str, runtime_kwargs: Dict[str, Any]) -> Dict[str, Any]:
        config_key = f"engines.{engine_name}"
        engine_config = self.get(config_key, {})
        resolved_config = {**engine_config, **runtime_kwargs}

        config_extra_options = engine_config.get("extra_options")
        runtime_extra_options = runtime_kwargs.get("extra_options")
        if isinstance(config_extra_options, dict) and isinstance(runtime_extra_options, dict):
            resolved_config["extra_options"] = {
                **config_extra_options,
                **runtime_extra_options,
            }

        return resolved_config

    def get(self, key: str, default: Any = None) -> Any:
        """Get a config value using dot notation, e.g. 'engines.mineru.model_dir'"""
        keys = key.split(".")
        val = self._config
        for k in keys:
            if isinstance(val, dict) and k in val:
                val = val[k]
            else:
                return default
        return val


# Singleton instance
settings = Config()
