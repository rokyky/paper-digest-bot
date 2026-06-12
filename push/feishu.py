"""飞书自定义机器人 webhook 推送"""

import json
import logging
from typing import Optional

import requests

from sources.base import Digest
from push.card_template import build_digest_card, build_empty_card

logger = logging.getLogger(__name__)


class FeishuPusher:
    """飞书群机器人消息推送"""

    def __init__(self, config: dict):
        self.webhooks = config.get("webhooks", [])
        self.max_card_length = config.get("max_card_content_length", 4000)
        self.timeout = config.get("timeout", 15)

    def push_digest(
        self,
        digests: list[Digest],
        topic_name: str = "搜广推前沿日报",
        total_candidates: int = 0,
    ) -> int:
        """
        推送日报到飞书

        Args:
            digests: 解读列表
            topic_name: 日报名称
            total_candidates: 当日候选总数

        Returns:
            成功推送的 webhook 数量
        """
        if not digests:
            logger.info("No digests to push, sending empty-card notification")
            card = build_empty_card(topic_name)
            return self._push_card(card)

        card = build_digest_card(
            digests=digests,
            topic_name=topic_name,
            total_candidates=total_candidates,
            max_content_length=self.max_card_length,
        )

        if card is None:
            logger.warning("Failed to build card, skipping push")
            return 0

        return self._push_card(card)

    def push_text(self, text: str) -> int:
        """推送纯文本消息"""
        card = {
            "config": {"wide_screen_mode": True},
            "header": {
                "title": {"tag": "plain_text", "content": "搜广推日报"},
                "template": "blue",
            },
            "elements": [
                {
                    "tag": "div",
                    "text": {"tag": "lark_md", "content": text},
                }
            ],
        }
        return self._push_card(card)

    def _push_card(self, card: dict) -> int:
        """推送卡片到所有配置的 webhook"""
        if not self.webhooks:
            logger.error("No Feishu webhooks configured!")
            return 0

        payload = {
            "msg_type": "interactive",
            "card": card,
        }

        success_count = 0
        for webhook in self.webhooks:
            try:
                resp = requests.post(
                    webhook,
                    json=payload,
                    timeout=self.timeout,
                    headers={"Content-Type": "application/json"},
                )

                if resp.status_code == 200:
                    result = resp.json()
                    if result.get("code") == 0:
                        success_count += 1
                        logger.info("Feishu push successful to %s...", webhook[:40])
                    else:
                        logger.error(
                            "Feishu API error: code=%s, msg=%s",
                            result.get("code"),
                            result.get("msg"),
                        )
                else:
                    logger.error(
                        "Feishu webhook HTTP %s: %s",
                        resp.status_code,
                        resp.text[:200],
                    )

            except requests.exceptions.Timeout:
                logger.error("Feishu webhook timeout: %s...", webhook[:40])
            except requests.exceptions.RequestException as e:
                logger.error("Feishu webhook request failed: %s", e)

        return success_count
