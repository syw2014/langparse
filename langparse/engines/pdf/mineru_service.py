from __future__ import annotations

import shlex
import socket
import subprocess
import tempfile
import time
from contextlib import contextmanager
from pathlib import Path
import json
import os

from langparse.engines.pdf.mineru_client import MinerUClient


class MinerUServiceManager:
    def __init__(
        self,
        api_url: str | None = None,
        host: str = "127.0.0.1",
        port: int = 8000,
        command: str = "mineru-api",
        start_timeout: float = 30.0,
        request_timeout: float = 300.0,
        model_dir: str | None = None,
        download_dir: str | None = None,
        model_policy: str = "download_if_missing",
        model_source: str | None = None,
    ):
        self.api_url = api_url.rstrip("/") if api_url else None
        self.host = host
        self.port = port
        self.command = command
        self.start_timeout = start_timeout
        self.request_timeout = request_timeout
        self.model_dir = model_dir
        self.download_dir = download_dir
        self.model_policy = model_policy
        self.model_source = model_source

    @contextmanager
    def running_service(self):
        if self.api_url:
            yield self.api_url
            return

        base_url = f"http://{self.host}:{self.port}"
        client = MinerUClient(base_url, timeout=self.request_timeout)
        if self._is_healthy(client):
            yield base_url
            return

        self._validate_model_policy()
        home_override_cm = self._prepare_local_home()
        with home_override_cm as home_override:
            process = self._start_local_service(home_override=home_override)
            try:
                self._wait_until_ready(client)
                yield base_url
            finally:
                self._stop_process(process)

    def _is_healthy(self, client: MinerUClient) -> bool:
        try:
            client.health()
        except Exception:
            return False
        return True

    def _start_local_service(self, home_override: str | None = None) -> subprocess.Popen:
        args = shlex.split(self.command) + ["--host", self.host, "--port", str(self.port)]
        env = self._build_process_env(home_override=home_override)
        try:
            return subprocess.Popen(
                args,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                env=env,
            )
        except FileNotFoundError as exc:
            raise RuntimeError(
                f"Unable to start local mineru-api service using command: {self.command}"
            ) from exc

    def _wait_until_ready(self, client: MinerUClient) -> None:
        deadline = time.time() + self.start_timeout
        last_error: Exception | None = None
        while time.time() < deadline:
            try:
                client.health()
                return
            except Exception as exc:  # pragma: no cover - exercised in timeout flow
                last_error = exc
                time.sleep(0.25)
        raise RuntimeError("Timed out waiting for local mineru-api service to become ready.") from last_error

    def _stop_process(self, process: subprocess.Popen) -> None:
        if process.poll() is not None:
            return
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)

    @staticmethod
    def find_free_port() -> int:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.bind(("127.0.0.1", 0))
            return int(sock.getsockname()[1])

    def _validate_model_policy(self) -> None:
        if self.model_policy not in {"download_if_missing", "require_existing"}:
            raise ValueError(
                "Unsupported MinerU model_policy: "
                f"{self.model_policy}. Expected 'download_if_missing' or 'require_existing'."
            )

        if self.model_policy != "require_existing":
            return

        if self.model_dir:
            model_path = Path(self.model_dir).expanduser()
            if not model_path.exists() or not any(model_path.iterdir()):
                raise RuntimeError(
                    f"MinerU model_policy=require_existing but model_dir is missing or empty: {model_path}"
                )
            return

        home_root = self._resolve_home_root()
        mineru_config = home_root / "mineru.json"
        mineru_cache = home_root / ".mineru"
        if not mineru_config.exists() and not mineru_cache.exists():
            raise RuntimeError(
                "MinerU model_policy=require_existing requires either model_dir or an existing "
                f"local MinerU home with mineru.json/.mineru under: {home_root}"
            )

    def _resolve_home_root(self) -> Path:
        if self.download_dir:
            return Path(self.download_dir).expanduser()
        return Path.home()

    def _build_process_env(self, home_override: str | None = None) -> dict[str, str]:
        env = os.environ.copy()
        if home_override:
            env["HOME"] = home_override

        effective_model_source = self.model_source
        if effective_model_source is None and self.model_dir:
            effective_model_source = "local"

        if effective_model_source:
            env["MINERU_MODEL_SOURCE"] = effective_model_source

        return env

    @contextmanager
    def _prepare_local_home(self):
        if self.model_dir:
            configured_root = Path(self.download_dir).expanduser() if self.download_dir else None
            if configured_root is not None:
                configured_root.mkdir(parents=True, exist_ok=True)
                self._write_mineru_config(configured_root)
                yield str(configured_root)
                return

            with tempfile.TemporaryDirectory(prefix="langparse-mineru-home-") as temp_home:
                temp_root = Path(temp_home)
                self._write_mineru_config(temp_root)
                yield temp_home
                return

        if self.download_dir:
            configured_root = Path(self.download_dir).expanduser()
            configured_root.mkdir(parents=True, exist_ok=True)
            yield str(configured_root)
            return

        yield None

    def _write_mineru_config(self, home_root: Path) -> None:
        model_path = str(Path(self.model_dir).expanduser())
        config_path = home_root / "mineru.json"
        config = {
            "models-dir": {
                "pipeline": model_path,
                "vlm": model_path,
            }
        }
        config_path.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")
