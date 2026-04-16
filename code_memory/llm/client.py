"""
LLM 调用抽象层。支持多模型配置。

通过 OpenAI 兼容协议或 Anthropic 协议统一调用。
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Optional

from ..config import LLMConfig

logger = logging.getLogger(__name__)


@dataclass
class LLMResponse:
    content: str
    model: str
    usage: dict[str, int]  # prompt_tokens, completion_tokens


class LLMClient:
    """统一 LLM 调用接口。"""

    REQUEST_TIMEOUT = 90  # 单请求超时（秒）
    MAX_RETRIES = 2       # 超时/网络错误时重试次数

    def __init__(self, config: LLMConfig):
        self.config = config
        self._client = None

    def _get_client(self):
        if self._client is None:
            api_key = os.environ.get(self.config.api_key_env, "")

            if self.config.api_format == "anthropic":
                from anthropic import Anthropic

                kwargs = {
                    "api_key": api_key,
                    "timeout": float(self.REQUEST_TIMEOUT),
                    "max_retries": self.MAX_RETRIES,
                }
                if self.config.api_base:
                    kwargs["base_url"] = self.config.api_base
                self._client = Anthropic(**kwargs)
            else:
                from openai import OpenAI

                kwargs = {
                    "api_key": api_key,
                    "timeout": float(self.REQUEST_TIMEOUT),
                    "max_retries": self.MAX_RETRIES,
                }
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

        if self.config.api_format == "anthropic":
            return self._generate_anthropic(client, system_prompt, user_prompt, temp, tokens)
        else:
            return self._generate_openai(client, system_prompt, user_prompt, temp, tokens)

    def _generate_openai(self, client, system_prompt, user_prompt, temp, tokens) -> LLMResponse:
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

    def _generate_anthropic(self, client, system_prompt, user_prompt, temp, tokens) -> LLMResponse:
        response = client.messages.create(
            model=self.config.model,
            system=system_prompt,
            messages=[
                {"role": "user", "content": user_prompt},
            ],
            temperature=temp,
            max_tokens=tokens,
        )
        content = ""
        for block in response.content:
            if hasattr(block, "text"):
                content += block.text
        return LLMResponse(
            content=content,
            model=response.model,
            usage={
                "prompt_tokens": response.usage.input_tokens if response.usage else 0,
                "completion_tokens": response.usage.output_tokens if response.usage else 0,
            },
        )
