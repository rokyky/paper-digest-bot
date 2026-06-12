"""LLM 深度解读生成"""

import json
import logging
from typing import Optional

from sources.base import Paper, Digest
from llm.client import LLMClient

logger = logging.getLogger(__name__)

# 深度解读 System Prompt（学术论文）
ACADEMIC_DIGEST_SYSTEM_PROMPT = """你是一个搜广推（搜索、广告、推荐）领域的资深研究员兼工程架构师。
你的任务是对一篇论文进行**深度解读**，输出详细、有洞见的分析。

## 要求
1. **不只是翻译摘要**。你要用自己的话把论文的核心贡献讲清楚、讲透彻。
2. **每个字段写 3-8 句**，而不是一两句话带过。要给出具体的分析、推理和判断。
3. **工程视角优先**：重点分析这篇论文对搜广推工程的实际价值——哪些思路可以搬到你自己的推荐/广告/搜索系统里？
4. **诚实评价局限性**：论文的实验设计有没有漏洞？方法在真实业务中可能遇到什么问题？
5. **具体而非空泛**：不要只说"效果好"——要说"在 YouTube 8 天线上 A/B 测试中，XX 指标提升 X%"

## 关键要求：中文精读
你必须在 JSON 中输出一个 `chinese_overview` 字段：用 300-500 字的中文，以连贯叙述的方式把论文的核心故事讲一遍。
这**不是**翻译摘要，而是像一个资深工程师给同行讲论文一样——先交代背景动机，再说核心思路，
然后点出关键实验结果，最后给出你的判断。要让人读完就能在脑子里构建出这篇论文的全貌。

## 输出格式
你必须输出纯 JSON，不要添加其他内容：
{
    "one_liner": "一句话说明这篇论文的核心贡献（1-2句）",
    "chinese_overview": "300-500字中文精读：用连贯叙述讲清论文背景、核心思路、关键结果、判断",
    "problem": "详细说明：解决了什么业务/学术问题？现有方法为什么不够？难点在哪里？",
    "method": "详细说明：核心方法是什么？模型结构、损失函数、训练流程、关键公式或算法步骤",
    "diff_from_prior": "详细说明：和已有的 SoTA/经典方法相比，核心区别是什么？创新点具体体现在哪？",
    "metrics": "详细说明：用了什么数据集？离线指标如何？有没有线上 A/B 实验？消融实验发现了什么？",
    "engineering_insight": "详细说明：对搜广推工程有什么启发？这个思路能迁移到我的业务中吗？预期能解决什么问题？",
    "deployment": "详细说明：如果要落地到生产环境，接入哪个场景？需要哪些改造？推理成本、延迟、工程复杂度预估",
    "limitations": "详细说明：论文没提到的问题？实验设计的局限性？复现难点？在真实业务中可能踩什么坑？",
    "target_audience": "这篇适合谁读：推荐工程师/广告算法工程师/搜索工程师/研究员/架构师？"
}
"""

# 工程博客的深度解读 Prompt
BLOG_DIGEST_SYSTEM_PROMPT = """你是一个搜广推领域的工程架构师。
你的任务是对一篇工程博客文章进行**深度技术解读**，提取可以复用的工程经验。

## 要求
1. 关注实际工程决策：为什么这样选型？放弃什么替代方案？
2. 关注指标数据：上线前后的具体业务指标变化
3. 关注踩坑经验：实施过程中遇到什么问题，怎么解决的
4. 每个字段写 3-8 句，讲深讲透

## 关键要求：中文精读
你必须在 JSON 中输出一个 `chinese_overview` 字段：用 300-500 字的中文连贯叙述，讲清这篇文章的背景、核心方案、关键结果和工程启示。
这不是翻译，而是像一个资深工程师给团队分享一样讲清楚。

## 输出格式
你必须输出纯 JSON，不要添加其他内容：
{
    "one_liner": "一句话概括这篇文章的核心价值",
    "chinese_overview": "300-500字中文精读：连贯叙述文章背景、核心方案、关键结果、工程启示",
    "problem": "解决了什么实际业务/工程问题？背景和挑战是什么？",
    "system_architecture": "系统架构是怎样的？模块如何划分？数据流如何设计？",
    "tech_choices": "关键技术选型：为什么选这个框架/模型/存储？放弃了什么替代方案？",
    "metrics": "核心指标：上线前后的业务指标对比、性能数据、资源消耗",
    "lessons_learned": "踩坑经验：实施中遇到的问题、解决方案、可复用的经验",
    "engineering_insight": "对搜广推工程的启发：哪些设计思路可以直接借鉴？",
    "deployment_advice": "如果要复用这套方案，需要什么条件？改造点在哪里？"
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
