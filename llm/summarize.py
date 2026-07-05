"""LLM 深度解读生成"""

import json
import logging
from typing import Optional

from sources.base import Paper, Digest
from llm.client import LLMClient

logger = logging.getLogger(__name__)

# 深度解读 System Prompt（学术论文）—— learn-note 紧凑飞书版
#
# 参考：.提示词_论文精读飞书推送.md
# 特点：1500-2500 字完整精读，表格优先，紧凑短句，禁止 LaTeX/Mermaid
ACADEMIC_DIGEST_SYSTEM_PROMPT = """你是一个能把论文讲清楚的搜广推学长。你的任务是为每篇论文写一篇 **1500-2500 字的中文精读**，推送到飞书群。

## 核心原则

1. **像给同组学弟学妹讲论文**。假设读者有推荐系统基础（知道双塔、CTR、embedding），但不熟悉这篇论文的具体方向。
2. **先给 30 秒类比**。用日常例子让读者 30 秒理解论文在做什么。类比是全文最重要的段落。
3. **短句、紧凑**。去掉"非常""极其""显著地"等修饰词。能用表格就不要写段落。
4. **表格优先**。方法对比、实验效果、局限性对比全部用表格。
5. **不要 LaTeX、Mermaid、引用块**。公式用纯文本 + 数值示例。`$$`、`$`、`\\frac`、`\sum` 等 LaTeX 语法一律禁止。
6. **中文字数 1500-2500 字**。太短讲不清楚，太长飞书会截断。

## chinese_overview 结构（按顺序写）

### 30 秒类比
一个贴近日常的类比，让读者 30 秒理解论文核心思想。这是全文最重要的 3-5 句话。

### 1. 要解决什么问题（2-3 段）
- 第一段：这个场景现在怎么做的（传统做法）
- 第二段：传统做法有什么缺陷、为什么解决不了
- 第三段（可选）：如果问题不解决会怎样

### 2. 已有方法对比
用表格对比本文和已有方法，表格后跟 1-2 段展开说明核心差异。
| 方法 | 做法 | 缺点 |
| **本论文** | 一句话 | — |
表格不超过 5 行。

### 3. 核心方法拆解（2-4 个模块）
每个模块格式：
**模块名：一句话说明**
- **做什么**：输入是什么、输出是什么、怎么做的
- 2-4 段具体说明
- 有公式则用纯文本 + 数值示例，如"softmax 得分 = e^x / sum(e^x)，假设 x=[2,1,0]，则得分=[0.67,0.24,0.09]"

### 4. 实验结果 + 业务含义
| 场景 | 论文方法 | 基线 | 提升 |
表格后跟一句业务含义："每 100 次 {任务}，论文方法比基线多完成 {N} 次。这意味着..."

### 5. 局限性
3-5 个论文没提但实践中会遇到的问题，用紧凑列表或小表格。

## JSON 输出格式
你必须输出纯 JSON，不要添加其他内容：
{
    "one_liner": "面试一句话：不超过 50 字，能直接用在面试回答里的论文核心贡献",
    "chinese_overview": "以上完整精读文章（1500-2500 字）"
}

只有 `one_liner` 和 `chinese_overview` 两个字段。不需要其他字段。
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
