"""
LLM 调用抽象层。支持多模型配置。

通过 OpenAI 兼容协议统一调用，覆盖 OpenAI / Anthropic / Kimi 等。
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Optional

from ..config import LLMConfig


@dataclass
class LLMResponse:
    content: str
    model: str
    usage: dict[str, int]  # prompt_tokens, completion_tokens


class LLMClient:
    """统一 LLM 调用接口。"""

    def __init__(self, config: LLMConfig):
        self.config = config
        self._client = None

    def _get_client(self):
        if self._client is None:
            from openai import OpenAI

            api_key = os.environ.get(self.config.api_key_env, "")
            kwargs = {"api_key": api_key}
            if self.config.api_base:
                kwargs["base_url"] = self.config.api_base

            self._client = OpenAI(**kwargs)
        return self._client

    def generate(
        self,
        system_prompt: str,
        user_prompt: str,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
    ) -> LLMResponse:
        """调用 LLM 生成响应。"""
        client = self._get_client()
        temp = temperature if temperature is not None else self.config.temperature
        tokens = max_tokens if max_tokens is not None else self.config.max_tokens

        response = client.chat.completions.create(
            model=self.config.model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=temp,
            max_tokens=tokens,
        )

        choice = response.choices[0]
        usage = response.usage

        return LLMResponse(
            content=choice.message.content or "",
            model=response.model,
            usage={
                "prompt_tokens": usage.prompt_tokens if usage else 0,
                "completion_tokens": usage.completion_tokens if usage else 0,
            },
        )
