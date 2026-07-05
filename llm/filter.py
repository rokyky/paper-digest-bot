"""LLM 相关性筛序 + 排序"""

import json
import logging
from typing import Optional

from sources.base import Paper
from llm.client import LLMClient

logger = logging.getLogger(__name__)

# 相关性判断 System Prompt（严格版）
# 目标：只筛出与 搜广推(搜索/广告/推荐)、LLM4Rec、生成式推荐 紧密相关的论文
RELEVANCE_SYSTEM_PROMPT = """你是一个搜广推（搜索、广告、推荐）领域的论文审稿专家。
你的任务是从海量论文中**严格筛选**出对搜广推有研究价值的论文。

## 核心判断原则
一篇论文"相关"的充要条件是：**这篇论文的主要贡献直接针对搜索、广告或推荐系统中的核心问题**。
仅提及"可用于推荐系统"作为潜在应用是不够的——论文必须把 搜广推 作为主要研究对象或主要应用场景。

## 通过标准
论文满足以下**任意一条**且为主要贡献（不是顺带一提）：
1. 提出新的**召回/粗排/精排/重排**算法或模型结构
2. 研究**CTR/CVR/转化率/出价/竞价**建模
3. 研究**用户/物品序列建模、多任务学习、特征交互**且面向推荐场景
4. 研究**广告拍卖、竞价策略、预算分配、市场设计**
5. 将 **LLM/大模型** 用于推荐、广告、搜索的任一环节（召回、排序、重排、解释等）
6. **生成式推荐**（直接生成候选、语义ID、端到端生成）
7. 研究**向量检索、稠密检索、ANN**且明确以推荐/搜索为应用场景
8. 研究**个性化/用户画像/冷启/多目标优化**且面向推荐系统
9. 提出推荐/广告/搜索系统的**端到端或全链路**方案

## 严格排除标准（即使标题包含 "recommendation"）
- ❌ 论文的主要贡献是**非搜广推领域**的推荐（如医疗诊断推荐、药物推荐、论文推荐、电影/音乐推荐给用户等——如果方法是通用的且核心创新适用于搜广推，可以通过，否则排除）
- ❌ 论文仅把 recommendation 作为**一个实验数据集或一个示例场景**
- ❌ 纯 ML 理论论文（如优化理论、学习理论）仅在推荐上做实验验证
- ❌ NLP/CV/语音等非搜广推领域的论文，即使其在其他领域使用了 "retrieval" 或 "ranking"
- ❌ 纯工程架构/基础设施/分布式训练框架优化
- ❌ 纯系统性能优化（GPU 利用率、编译优化、I/O 优化）
- ❌ 数据分析/调研报告（survey）除非有实质性方法论贡献
- ❌ 只涉及知识图谱、图神经网络但**没有明确面向推荐/搜索系统**设计

## 评分标准
- 0.0-0.3: ❌ 不相关或仅轻微相关，应排除
- 0.3-0.5: ⚠️ 弱相关，可能有启发但非核心贡献，倾向于排除
- 0.5-0.7: ✅ 相关，对搜广推有参考价值
- 0.7-1.0: ✅ 高度相关，核心贡献直接面向搜广推关键问题

## 特别注意：LLM4Rec 判断
- ✅ 通过：LLM 作为推荐系统核心组件（生成候选、排序、解释、交互等）
- ❌ 排除：LLM 论文中把 recommendation 作为众多评估任务之一，无专门推荐设计
- ✅ 通过：研究推荐系统的 prompt 设计、推荐数据增强、推荐知识蒸馏等
- ❌ 排除：通用 RLHF/RL 方法，仅在推荐数据上做实验

## 输出格式
你必须输出 JSON 格式，不要包含其他内容：
{
    "is_relevant": true/false,
    "relevance_score": 0.0-1.0,
    "reason": "用一句话说明判断理由"
}
"""

# 排序 System Prompt（严格版）
RANKING_SYSTEM_PROMPT = """你是一个搜广推领域的首席工程师。
你的任务是对一批论文按照"对搜广推工程的实用价值"进行排序。

## 第一原则：先过一遍相关性
如果某篇论文**不是主要针对搜广推**（搜索、广告、推荐系统），直接排除。
例如：以医疗推荐、电影推荐、通用ML理论为主但用推荐做实验的论文，直接排除。

## 排序需要考虑
1. **直接相关性**：论文是否直接解决搜广推的核心问题？（召回、排序、CTR、竞价等）—— 这是最重要的因素
2. **工程可行性**：方法能否在真实业务场景落地？推理成本、训练成本如何？
3. **业务价值**：能否直接提升 CTR/CVR/GMV/广告收入等关键指标？
4. **创新性**：是不是老问题的新解法？有没有真知灼见？
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
关键词：{', '.join(self.topic_keywords)}  # 全部关键词

请判断这篇论文是否与搜索、广告、推荐（搜广推）领域相关？特别关注是否涉及 LLM4Rec、生成式推荐等前沿方向。给出评分和理由。"""

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
