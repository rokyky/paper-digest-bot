"""LLM 相关性筛序 + 排序"""

import json
import logging
from typing import Optional

from sources.base import Paper
from llm.client import LLMClient

logger = logging.getLogger(__name__)

# 相关性判断 System Prompt
RELEVANCE_SYSTEM_PROMPT = """你是一个搜广推（搜索、广告、推荐）领域的论文审稿专家。
你的任务是从海量论文中筛选出对搜广推工程有实际价值的论文。

## 判断标准
一篇论文是"相关"的，当它至少满足以下一项：
1. 核心方法可直接应用于推荐系统、广告系统、搜索排序
2. 提出新的召回/粗排/精排/重排/混排算法
3. 研究 CTR/CVR/转化率建模、多任务学习、用户行为建模
4. 涉及广告出价、竞价、拍卖机制设计
5. 涉及向量检索、ANN、稠密检索、语义匹配
6. 将 LLM 用于推荐、广告、搜索的生成/排序/解释
7. 研究个性化、用户序列建模、图推荐、强化学习推荐
8. 在推荐/广告/搜索场景下的工业级系统论文或实践经验

## 输出格式
你必须输出 JSON 格式，不要包含其他内容：
{
    "is_relevant": true/false,
    "relevance_score": 0.0-1.0,
    "reason": "用一句话说明判断理由"
}

评分标准：
- 0.0-0.3: 不相关或轻微相关
- 0.3-0.6: 弱相关，方法可能有启发
- 0.6-0.8: 相关，对搜广推有参考价值
- 0.8-1.0: 高度相关，直接可落地或创新性极强
"""

# 排序 System Prompt
RANKING_SYSTEM_PROMPT = """你是一个搜广推领域的首席工程师。
你的任务是对一批论文按照"对搜广推工程的实用价值"进行排序。

## 排序需要考虑
1. **工程可行性**：方法能否在真实业务场景落地？推理成本、训练成本如何？
2. **业务价值**：能否直接提升 CTR/CVR/GMV/广告收入等关键指标？
3. **创新性**：是不是老问题的新解法？有没有真知灼见？
4. **可迁移性**：方案能否迁移到其他搜广推场景？
5. **时效性**：是不是当前行业正在关注的热点方向？

## 输出格式
你必须输出 JSON 格式的排序结果。不要添加其他内容：
{
    "ranked_indices": [3, 0, 4, 1, 2],
    "reasons": ["论文3: ...", "论文0: ...", ...]
}
其中 ranked_indices 是论文原始列表的索引，按价值从高到低排列。
"""


class LLMFilter:
    """LLM 相关性筛序 + 排序"""

    def __init__(self, llm_client: LLMClient, config: dict):
        self.client = llm_client
        self.topic_keywords = config.get("keywords", [])
        self.relevance_threshold = config.get("relevance_threshold", 0.5)
        self.max_items = config.get("max_items", 5)

    def filter_relevant(self, papers: list[Paper]) -> list[tuple[Paper, float, str]]:
        """用 LLM 筛出相关论文，返回 [(paper, score, reason)]"""
        if not papers:
            return []

        logger.info("Filtering %d papers for relevance...", len(papers))
        relevant = []

        for i, paper in enumerate(papers):
            try:
                result = self._judge_relevance(paper)
                if result and result.get("is_relevant") and result.get("relevance_score", 0) >= self.relevance_threshold:
                    relevant.append((paper, result["relevance_score"], result.get("reason", "")))
                # 避免打印过多日志
                if (i + 1) % 20 == 0:
                    logger.info("Progress: %d/%d papers processed", i + 1, len(papers))
            except Exception as e:
                logger.warning("Failed to judge relevance for paper '%s': %s", paper.title[:40], e)
                continue

        # 按分数降序
        relevant.sort(key=lambda x: x[1], reverse=True)
        logger.info("Relevance filter: %d/%d papers passed (threshold=%.2f)",
                     len(relevant), len(papers), self.relevance_threshold)
        return relevant

    def _judge_relevance(self, paper: Paper) -> Optional[dict]:
        """判断单篇论文的相关性"""
        user_prompt = f"""论文标题：{paper.title}
作者：{', '.join(paper.authors[:5])}
摘要：{paper.abstract[:2000]}
来源：{paper.source}
关键词：{', '.join(self.topic_keywords[:15])}

请判断这篇论文是否与搜索、广告、推荐（搜广推）领域相关？给出评分和理由。"""

        try:
            result = self.client.chat_structured(
                system_prompt=RELEVANCE_SYSTEM_PROMPT,
                user_prompt=user_prompt,
                output_schema={"type": "json_object"},
            )
            return result
        except Exception as e:
            logger.error("LLM relevance call failed: %s", e)
            return None

    def rank_top_n(self, papers_with_scores: list[tuple[Paper, float, str]]) -> list[Paper]:
        """用 LLM 排序，返回 Top N"""
        if not papers_with_scores:
            return []

        if len(papers_with_scores) <= self.max_items:
            # 数量不多，直接用 LLM 分数排序即可
            logger.info("Only %d papers, skipping LLM ranking", len(papers_with_scores))
            return [p for p, _, _ in papers_with_scores]

        logger.info("Ranking %d papers to select top %d...", len(papers_with_scores), self.max_items)

        # 准备排序用的文本（用 title + 简短摘要）
        candidates = []
        for i, (paper, score, reason) in enumerate(papers_with_scores):
            candidates.append(f"[{i}] 标题: {paper.title}\n摘要: {paper.abstract[:300]}\n初筛评分: {score:.2f}\n")

        user_prompt = f"""请从以下 {len(candidates)} 篇论文中，选出对搜广推工程最有价值的 {self.max_items} 篇。

候选论文：
{chr(10).join(candidates)}

输出 JSON 格式的排序结果。"""

        try:
            result = self.client.chat_structured(
                system_prompt=RANKING_SYSTEM_PROMPT,
                user_prompt=user_prompt,
                output_schema={"type": "json_object"},
            )

            ranked = result.get("ranked_indices", [])
            if ranked:
                # 取 Top N
                top_indices = ranked[:self.max_items]
                selected = [papers_with_scores[i][0] for i in top_indices if i < len(papers_with_scores)]
                logger.info("Ranking complete: selected top %d papers", len(selected))
                return selected

        except Exception as e:
            logger.error("LLM ranking failed: %s", e)

        # Fallback：按初筛分数排序
        logger.warning("Falling back to score-based ranking")
        papers_with_scores.sort(key=lambda x: x[1], reverse=True)
        return [p for p, _, _ in papers_with_scores[:self.max_items]]
