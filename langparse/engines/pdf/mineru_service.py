from __future__ import annotations

import shlex
import socket
import subprocess
import time
from contextlib import contextmanager

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
    ):
        self.api_url = api_url.rstrip("/") if api_url else None
        self.host = host
        self.port = port
        self.command = command
        self.start_timeout = start_timeout
        self.request_timeout = request_timeout

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

        process = self._start_local_service()
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

    def _start_local_service(self) -> subprocess.Popen:
        args = shlex.split(self.command) + ["--host", self.host, "--port", str(self.port)]
        try:
            return subprocess.Popen(
                args,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
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
