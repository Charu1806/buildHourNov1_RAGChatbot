"""One provider adapter. `complete(system, user) -> str`, no fallback."""

from __future__ import annotations

from src.config import Settings


class ChatModel:
    def __init__(self, settings: Settings) -> None:
        self.provider = settings.llm_provider
        self.model = settings.llm_model
        self.api_key = settings.api_key
        self.temperature = settings.llm_temperature
        self.max_tokens = settings.llm_max_tokens

    def complete(self, system: str, user: str) -> str:
        method = getattr(self, f"_{self.provider}", None)
        if method is None:
            raise RuntimeError(f"unsupported llm_provider: {self.provider}")
        return method(system, user)

    def _groq(self, system: str, user: str) -> str:
        from groq import Groq

        client = Groq(api_key=self.api_key)
        response = client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            temperature=self.temperature,
            max_tokens=self.max_tokens,
        )
        return response.choices[0].message.content or ""

    def _openai(self, system: str, user: str) -> str:
        from openai import OpenAI

        client = OpenAI(api_key=self.api_key)
        response = client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            temperature=self.temperature,
            max_tokens=self.max_tokens,
        )
        return response.choices[0].message.content or ""

    def _mistral(self, system: str, user: str) -> str:
        from mistralai import Mistral

        client = Mistral(api_key=self.api_key)
        response = client.chat.complete(
            model=self.model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            temperature=self.temperature,
            max_tokens=self.max_tokens,
        )
        return response.choices[0].message.content or ""

    def _anthropic(self, system: str, user: str) -> str:
        from anthropic import Anthropic

        client = Anthropic(api_key=self.api_key)
        response = client.messages.create(
            model=self.model,
            max_tokens=self.max_tokens,
            temperature=self.temperature,
            system=system,
            messages=[{"role": "user", "content": user}],
        )
        return "".join(
            block.text for block in response.content if getattr(block, "type", "") == "text"
        )

    def _gemini(self, system: str, user: str) -> str:
        from google import genai

        client = genai.Client(api_key=self.api_key)
        response = client.models.generate_content(
            model=self.model,
            contents=user,
            config={
                "system_instruction": system,
                "temperature": self.temperature,
                "max_output_tokens": self.max_tokens,
            },
        )
        return response.text or ""
