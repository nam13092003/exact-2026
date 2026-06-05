import os
import requests
from typing import Any, Dict, List, Optional

class VLLMClient:
    """Tiny OpenAI-compatible client that uses OpenRouter as backend.

    Environment variables (defaults):
      OPENROUTER_API_BASE=https://api.openrouter.ai/v1
      OPENROUTER_API_KEY=<your-key>

    Keeps the original `VLLMClient` name for compatibility but routes requests
    to OpenRouter. If no API key is configured, `enabled` will be False.
    """

    def __init__(self, base_url: Optional[str] = None, model: Optional[str] = None, api_key: Optional[str] = None, timeout: int = 45):
        default_base = (
            os.getenv("OPENROUTER_API_BASE")
            or os.getenv("EXACT_LLM_BASE_URL")
            or "https://openrouter.ai/api/v1"
        ).rstrip("/")
        self.base_url = (base_url or default_base).rstrip("/")
        self.model = model or os.getenv("EXACT_LLM_MODEL") or os.getenv("OPENROUTER_MODEL") or ""
        self.api_key = (
            api_key
            or os.getenv("OPENROUTER_API_KEY")
            or os.getenv("EXACT_LLM_API_KEY")
            or os.getenv("OR_TOKEN")
            or ""
        )
        self.timeout = timeout

    @property
    def enabled(self) -> bool:
        return bool(self.base_url and self.model and self.api_key)

    def chat(self, messages: List[Dict[str, str]], temperature: float = 0.0, max_tokens: int = 1024, response_format: Optional[Dict[str, Any]] = None) -> str:
        if not self.enabled:
            raise RuntimeError("OpenRouter client not configured (missing base URL, model, or API key).")

        payload: Dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if response_format is not None:
            payload["response_format"] = response_format

        headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}
        url = f"{self.base_url}/chat/completions"
        r = requests.post(url, json=payload, headers=headers, timeout=self.timeout)
        r.raise_for_status()
        data = r.json()

        # OpenRouter follows an OpenAI-compatible response shape.
        if "choices" in data and data["choices"]:
            choice = data["choices"][0]
            # new shape: choice.message.content
            if isinstance(choice.get("message"), dict) and "content" in choice["message"]:
                return choice["message"]["content"]
            # fallback to older / alternative shapes
            if "text" in choice:
                return choice["text"]

        raise RuntimeError("Unexpected response format from OpenRouter")
