"""统一 LLM API 客户端，支持 OpenAI / Claude / DeepSeek / Qwen"""

import json
import logging
from typing import Optional

logger = logging.getLogger(__name__)


class LLMClient:
    """统一的 LLM 调用客户端，封装多 provider 切换"""

    def __init__(self, provider: str, model: str, api_key: str = None,
                 max_tokens: int = 1000, temperature: float = 0.3):
        self.provider = provider
        self.model = model
        self.api_key = api_key
        self.max_tokens = max_tokens
        self.temperature = temperature
        self._client = None
        self._init_client()

    def _init_client(self):
        """初始化对应 provider 的客户端"""
        p = self.provider.lower()

        if p == "openai":
            import openai
            self._client = openai.OpenAI(api_key=self.api_key)

        elif p == "claude":
            import anthropic
            self._client = anthropic.Anthropic(api_key=self.api_key)

        elif p == "deepseek":
            import openai  # DeepSeek 兼容 OpenAI SDK
            self._client = openai.OpenAI(
                api_key=self.api_key,
                base_url="https://api.deepseek.com",
            )

        elif p == "qwen":
            import openai  # Qwen 兼容 OpenAI SDK
            self._client = openai.OpenAI(
                api_key=self.api_key,
                base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
            )

        else:
            raise ValueError(f"Unsupported LLM provider: {self.provider}")

    def chat(self, system_prompt: str, user_prompt: str,
             response_format: Optional[dict] = None) -> str:
        """调用 LLM 聊天接口"""
        p = self.provider.lower()

        if p == "claude":
            return self._chat_claude(system_prompt, user_prompt)
        else:
            return self._chat_openai_like(system_prompt, user_prompt, response_format)

    def _chat_openai_like(self, system_prompt: str, user_prompt: str,
                          response_format: Optional[dict] = None) -> str:
        """调用 OpenAI 兼容接口"""
        kwargs = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "max_tokens": self.max_tokens,
            "temperature": self.temperature,
        }
        if response_format:
            kwargs["response_format"] = response_format

        resp = self._client.chat.completions.create(**kwargs)
        return resp.choices[0].message.content or ""

    def _chat_claude(self, system_prompt: str, user_prompt: str) -> str:
        """调用 Claude API"""
        resp = self._client.messages.create(
            model=self.model,
            system=system_prompt,
            messages=[{"role": "user", "content": user_prompt}],
            max_tokens=self.max_tokens,
            temperature=self.temperature,
        )
        return resp.content[0].text if resp.content else ""

    def chat_structured(self, system_prompt: str, user_prompt: str,
                        output_schema: dict) -> dict:
        """调用 LLM 并返回结构化 JSON（仅 OpenAI 兼容接口支持）"""
        if self.provider.lower() == "claude":
            # Claude 不支持 response_format，退化为文本 + JSON 解析
            text = self._chat_claude(
                system_prompt + "\n\n你必须输出纯粹的 JSON，不要包含任何其他内容。",
                user_prompt,
            )
            return self._parse_json(text)
        else:
            text = self._chat_openai_like(
                system_prompt,
                user_prompt,
                response_format={"type": "json_object"},
            )
            return self._parse_json(text)

    def _parse_json(self, text: str) -> dict:
        """解析 LLM 返回的 JSON 字符串"""
        # 尝试提取 JSON 块
        text = text.strip()
        if text.startswith("```"):
            # 移除 markdown 代码块标记
            lines = text.split("\n")
            text = "\n".join(line for line in lines if not line.startswith("```"))

        try:
            return json.loads(text)
        except json.JSONDecodeError as e:
            logger.error("Failed to parse LLM JSON response: %s", e)
            logger.debug("Raw response: %s", text[:500])
            return {}
