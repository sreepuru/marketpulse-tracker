from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


@dataclass(frozen=True)
class OllamaConfig:
    base_url: str = "http://localhost:11434"
    gemma_model: str = "gemma3:4b"
    verifier_model: str = "qwen3:8b"
    embedding_model: str = "nomic-embed-text:latest"
    timeout_seconds: int = 120


class OllamaError(RuntimeError):
    pass


class OllamaClient:
    """Small dependency-free Ollama client. No database writes."""

    def __init__(self, config: OllamaConfig | None = None):
        self.config = config or OllamaConfig()

    def _post(
        self,
        path: str,
        payload: dict[str, Any],
        timeout: int | None = None,
    ) -> dict[str, Any]:
        body = json.dumps(payload).encode("utf-8")

        req = Request(
            self.config.base_url.rstrip("/") + path,
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )

        try:
            with urlopen(
                req,
                timeout=timeout or self.config.timeout_seconds,
            ) as response:
                return json.loads(
                    response.read().decode("utf-8")
                )

        except (
            HTTPError,
            URLError,
            TimeoutError,
            json.JSONDecodeError,
        ) as exc:
            raise OllamaError(
                f"Ollama request failed: {exc}"
            ) from exc

    def generate_json(
        self,
        model: str,
        system: str,
        prompt: str,
        timeout: int | None = None,
        think: bool | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": model,
            "system": system,
            "prompt": prompt,
            "stream": False,
            "format": "json",
            "options": {
                "temperature": 0,
            },
        }

        if think is not None:
            payload["think"] = think

        result = self._post(
            "/api/generate",
            payload,
            timeout=timeout,
        )

        text = result.get("response", "")

        try:
            value = json.loads(text)
        except json.JSONDecodeError as exc:
            raise OllamaError(
                f"Model returned non-JSON output: {text[:500]}"
            ) from exc

        if not isinstance(value, dict):
            raise OllamaError(
                "Model JSON response was not an object"
            )

        return value

    def embed(self, text: str) -> list[float]:
        result = self._post(
            "/api/embed",
            {
                "model": self.config.embedding_model,
                "input": text,
            },
        )

        embeddings = result.get("embeddings") or []

        if not embeddings or not isinstance(
            embeddings[0],
            list,
        ):
            raise OllamaError(
                "Ollama embedding response did not contain "
                "an embedding"
            )

        return [float(x) for x in embeddings[0]]