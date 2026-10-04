from __future__ import annotations

import hashlib
import json
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class TokenCount:
    token_count: int
    text_sha256: str
    latency_ms: float
    model_id: str


class TokenCounter(Protocol):
    def count(self, text: str) -> TokenCount:
        ...


class CachedTokenCounter:
    """Memoize exact counts by content hash for one fixed-model counter.

    Budget packers repeatedly probe identical prefixes while testing candidate
    events.  The target tokenizer is still authoritative, but an identical text
    should never require a second model-server request within the same run.
    """

    def __init__(self, counter: TokenCounter) -> None:
        self.counter = counter
        self._cache: dict[str, TokenCount] = {}
        self.requests = 0
        self.hits = 0
        self.misses = 0

    def count(self, text: str) -> TokenCount:
        if not text:
            raise ValueError("raw token counting requires non-empty text")
        self.requests += 1
        digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
        cached = self._cache.get(digest)
        if cached is not None:
            self.hits += 1
            return cached
        result = self.counter.count(text)
        if result.text_sha256 != digest:
            raise RuntimeError("token counter returned a mismatched content hash")
        self._cache[digest] = result
        self.misses += 1
        return result

    @property
    def hit_rate(self) -> float:
        return self.hits / self.requests if self.requests else 0.0


class OllamaRawTokenCounter:
    """Count raw prompt tokens with the target Ollama model's own tokenizer.

    Ollama does not expose a standalone tokenizer route.  A raw generate request
    with one predicted token returns ``prompt_eval_count`` without adding the chat
    template.  The generated probe token is discarded and reported separately by
    experiment manifests.
    """

    def __init__(
        self,
        *,
        model: str,
        base_url: str = "http://127.0.0.1:11434",
        timeout_seconds: float = 180.0,
        seed: int = 5203,
    ) -> None:
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds
        self.seed = seed

    def count(self, text: str) -> TokenCount:
        if not text:
            raise ValueError("raw token counting requires non-empty text")
        payload = {
            "model": self.model,
            "prompt": text,
            "raw": True,
            "stream": False,
            "think": False,
            "options": {
                "num_predict": 1,
                "temperature": 0,
                "seed": self.seed,
            },
        }
        request = urllib.request.Request(
            f"{self.base_url}/api/generate",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        started = time.perf_counter()
        try:
            with urllib.request.urlopen(
                request, timeout=self.timeout_seconds
            ) as handle:
                response = json.loads(handle.read().decode("utf-8"))
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            raise RuntimeError(f"Local Ollama token count failed: {exc}") from exc
        elapsed_ms = (time.perf_counter() - started) * 1000.0
        count = response.get("prompt_eval_count")
        if not isinstance(count, int) or count <= 0:
            raise RuntimeError("Ollama response is missing positive prompt_eval_count")
        return TokenCount(
            token_count=count,
            text_sha256=hashlib.sha256(text.encode("utf-8")).hexdigest(),
            latency_ms=elapsed_ms,
            model_id=str(response.get("model", self.model)),
        )
