"""LLM 深度解读生成"""

import json
import logging
from typing import Optional

from sources.base import Paper, Digest
from llm.client import LLMClient

logger = logging.getLogger(__name__)

# 深度解读 System Prompt（学术论文）
ACADEMIC_DIGEST_SYSTEM_PROMPT = """你是个能把复杂技术讲明白的搜广推工程师。你的任务是把论文解读写成**小白也能看懂、看完能复述给别人听**的水平。

## 核心原则：深入浅出

1. **像在给组里新人讲论文一样**。假设读者是入行 1-2 年的搜广推工程师，懂 ML 基础（梯度下降、embedding、attention），但不一定了解论文涉及的专业方向（如 ANNS、多任务学习、双塔模型）。
2. **先讲"为什么这个很重要"**。不要一上来就抛技术细节。先让读者理解问题背景——如果没解决这个问题，业务会有什么实际影响？
3. **用类比和比喻**。遇到复杂概念（如用户态 I/O、乘积量化、对比学习），用生活中或读者已知的类比来解释。比如："所谓用户态 I/O，就像绕开层层审批直接找负责人"。
4. **每提到一个专业术语，用一句话解释一下**。不能默认读者知道"SPDK""IVF""PQ""HNSW"是什么。每次提新术语时跟在括号里简单说明。
5. **和已有知识挂钩**。主动联系读者可能知道的基础概念：常见的推荐系统双塔、CTR 模型、Faiss 向量检索等。"这相当于给 Faiss IVF 加了一个智能调度器"。
6. **具体而非空泛**。不要只说"效果好"——要说"在 YouTube 8 天线上 A/B 测试中，XX 指标提升 X%"。但指标解释要通俗，不要只丢数字。
7. **每个字段写 3-8 句**，但句子要短，语气像在聊天。

## 关键要求：中文精读
你必须在 JSON 中输出一个 `chinese_overview` 字段：用 400-600 字的中文，像讲故事一样把论文讲一遍。
结构建议：**读者为什么要关心** → **以前怎么做的、有什么问题** → **这篇做了什么、为什么聪明** → **实验结果说明什么** → **对读者的实际价值**。
用一个具体的类比开场更好，比如："想象你有一个超大的仓库...以前是派人满仓库跑着找东西..."

## 输出格式
你必须输出纯 JSON，不要添加其他内容：
{
    "one_liner": "一句话说明这篇论文的核心贡献（像新闻标题一样抓人）",
    "chinese_overview": "400-600字中文精读：用讲故事的方式，类比+联系基础+连贯叙述",
    "problem": "详细说明：业务/学术问题是什么？用日常语言解释为什么这个问题难、为什么重要",
    "method": "核心方法是什么？用类比+通俗语言说明，关键公式用文字描述含义而不是列公式",
    "diff_from_prior": "和已有的常见方法（如双塔、HNSW、FM/DeepFM）相比，核心区别是什么？",
    "metrics": "实验怎么做的？用了什么数据？提升多少？这些数字在实际业务中意味着什么？",
    "engineering_insight": "对搜广推工程有什么实际启发？我能在自己的推荐/广告/搜索系统里怎么用？预期解决什么痛点？",
    "deployment": "如果要落地，需要什么条件？改造点在哪里？难不难？要花多少资源？",
    "limitations": "论文没说的坑有哪些？业务落地可能遇到什么问题？什么场景不适合用？",
    "target_audience": "适合谁读：推荐工程师/广告算法工程师/搜索工程师/研究员/架构师"
}
"""

# 工程博客的深度解读 Prompt
BLOG_DIGEST_SYSTEM_PROMPT = """你是个能把工程文章讲明白的技术布道师。任务是写**新手也能看懂**的深度解读。

## 核心原则：深入浅出
1. 先讲背景：这篇文章解决什么实际业务问题？为什么这个问题值得关注？
2. 用类比解释系统设计：把复杂的架构讲得像搭积木一样清楚
3. 每提一个技术名词就用一句话解释。不默认读者知道"SPDK""HNSW""IVF"等
4. 联系读者已知的知识：Faiss、HNSW、Embedding、双塔等
5. 每个字段写 3-8 句，但用短句、口语化表达

## 关键要求：中文精读
你必须在 JSON 中输出一个 `chinese_overview` 字段：用 400-600 字讲故事。
结构：**业务背景** → **过去怎么做、哪里不够好** → **本文怎么做的** → **上线效果** → **你能学到什么**。

## 输出格式
你必须输出纯 JSON，不要添加其他内容：
{
    "one_liner": "一句话概括这篇文章的核心价值",
    "chinese_overview": "400-600字中文精读：讲故事+类比+联系基础",
    "problem": "解决了什么实际业务/工程问题？背景和挑战是什么？用大白话说",
    "system_architecture": "系统架构是怎样的？模块怎么分工？数据怎么流转？用通俗语言描述",
    "tech_choices": "关键技术选型：为什么选这个？放弃了什么替代方案？为什么那样不行？",
    "metrics": "核心指标：上线前后对比、性能数据、资源消耗变化。这些数字在实际中意味着什么？",
    "lessons_learned": "踩坑经验：实施中遇到过什么问题？怎么解决的？有什么可以复用的经验？",
    "engineering_insight": "对搜广推工程的启发：哪些设计思路可以直接拿过来用？能解决什么痛点？",
    "deployment_advice": "想复用这套方案需要什么条件？改造点在哪里？难不难？"
}
"""


class LLMSummarizer:
    """LLM 深度解读生成器"""

    def __init__(self, llm_client: LLMClient):
        self.client = llm_client
        self.max_input_length = 15000  # 输入截断长度

    def generate_digest(self, paper: Paper) -> Optional[Digest]:
        """生成单篇论文的深度解读"""
        logger.info("Generating digest for: %s", paper.title[:60])

        try:
            if paper.is_engineering:
                return self._generate_blog_digest(paper)
            else:
                return self._generate_academic_digest(paper)
        except Exception as e:
            logger.error("Digest generation failed for '%s': %s", paper.title[:40], e)
            return None

    def _generate_academic_digest(self, paper: Paper) -> Optional[Digest]:
        """学术论文深度解读"""
        user_prompt = self._build_academic_prompt(paper)
        system_prompt = ACADEMIC_DIGEST_SYSTEM_PROMPT

        result = self.client.chat_structured(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            output_schema={"type": "json_object"},
        )

        if not result:
            return None

        return Digest(
            paper=paper,
            one_liner=result.get("one_liner", ""),
            chinese_overview=result.get("chinese_overview", ""),
            problem=result.get("problem", ""),
            method=result.get("method", ""),
            diff_from_prior=result.get("diff_from_prior", ""),
            metrics=result.get("metrics", ""),
            engineering_insight=result.get("engineering_insight", ""),
            deployment=result.get("deployment", ""),
            limitations=result.get("limitations", ""),
            target_audience=result.get("target_audience", ""),
            raw_digest=json.dumps(result, ensure_ascii=False),
        )

    def _generate_blog_digest(self, paper: Paper) -> Optional[Digest]:
        """工程博客深度解读"""
        user_prompt = self._build_blog_prompt(paper)
        system_prompt = BLOG_DIGEST_SYSTEM_PROMPT

        result = self.client.chat_structured(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            output_schema={"type": "json_object"},
        )

        if not result:
            return None

        return Digest(
            paper=paper,
            one_liner=result.get("one_liner", ""),
            chinese_overview=result.get("chinese_overview", ""),
            problem=result.get("problem", ""),
            method=result.get("system_architecture", "") + "\n\n" + result.get("tech_choices", ""),
            diff_from_prior="",
            metrics=result.get("metrics", ""),
            engineering_insight=result.get("engineering_insight", ""),
            deployment=result.get("deployment_advice", ""),
            limitations=result.get("lessons_learned", ""),
            target_audience="推荐/广告/搜索工程师",
            raw_digest=json.dumps(result, ensure_ascii=False),
        )

    def _build_academic_prompt(self, paper: Paper) -> str:
        """构建学术论文的 prompt"""
        content = f"""论文标题：{paper.title}
作者：{', '.join(paper.authors[:8])}
发表日期：{paper.published_date or 'N/A'}
来源：{paper.source}
原文链接：{paper.url}

摘要：
{paper.abstract[:self.max_input_length]}

请对这篇论文进行深度解读，输出 JSON 格式的详细分析。"""
        return content

    def _build_blog_prompt(self, paper: Paper) -> str:
        """构建工程博客的 prompt"""
        extra = paper.extra
        full_summary = extra.get("summary_full", paper.abstract)
        blog_name = extra.get("blog_name", "Engineering Blog")

        content = f"""文章标题：{paper.title}
作者：{', '.join(paper.authors)}
发表日期：{paper.published_date or 'N/A'}
博客来源：{blog_name}
原文链接：{paper.url}

文章内容：
{full_summary[:self.max_input_length]}

请对这篇工程文章进行深度技术解读，输出 JSON 格式的详细分析。"""
        return content
