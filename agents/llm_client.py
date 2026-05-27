
import os
import requests
from typing import Any, Dict, List, Optional
from dotenv import load_dotenv
load_dotenv()

class VLLMClient:
    def __init__(
        self,
        base_url: Optional[str] = None,
        model: Optional[str] = None,
        api_key: Optional[str] = None,
        timeout: int = 45,
    ):
        self.base_url = (base_url or os.getenv("EXACT_LLM_BASE_URL") or "https://openrouter.ai/api/v1").rstrip("/")
        self.model = (
          model
          or os.getenv("EXACT_LLM_MODEL")
          or "qwen/qwen-2.5-7b-instruct"
      )
        self.api_key = api_key or os.getenv("EXACT_LLM_API_KEY")
        self.timeout = timeout

    @property
    def enabled(self) -> bool:
        return bool(
            self.base_url
            and self.model
            and self.api_key
        )

    def chat(
        self,
        messages: List[Dict[str, str]],
        temperature: float = 0.0,
        max_tokens: int = 1024,
        response_format: Optional[Dict[str, Any]] = None,
    ) -> str:

        print("=" * 60)
        print("LLM CALLED")
        print("BASE_URL =", self.base_url)
        print("MODEL    =", self.model)
        print("MESSAGES =", len(messages))
        print("=" * 60)

        if not self.enabled:
            raise RuntimeError("No endpoint configured.")

        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }

        if response_format is not None:
            payload["response_format"] = response_format

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        r = requests.post(
            f"{self.base_url}/chat/completions",
            json=payload,
            headers=headers,
            timeout=self.timeout,
        )

        r.raise_for_status()
        data = r.json()

        return data["choices"][0]["message"]["content"]
