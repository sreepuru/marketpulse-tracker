"""Minimal Ollama embedding client using the standard library."""
from __future__ import annotations

import json
import os
from urllib.request import Request, urlopen

class OllamaEmbeddingClient:
    def __init__(self, base_url: str | None = None, model: str | None = None, timeout: int = 30):
        self.base_url = (base_url or os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")).rstrip("/")
        self.model = model or os.getenv("MARKETPULSE_EMBEDDING_MODEL", "nomic-embed-text")
        self.timeout = timeout

    def embed(self, text: str) -> list[float]:
        payload = json.dumps({"model": self.model, "input": text}).encode("utf-8")
        req = Request(
            f"{self.base_url}/api/embed",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urlopen(req, timeout=self.timeout) as response:
            body = json.loads(response.read().decode("utf-8"))
        embeddings = body.get("embeddings") or []
        if not embeddings or not isinstance(embeddings[0], list):
            raise RuntimeError("Ollama returned no embedding")
        return [float(x) for x in embeddings[0]]
