"""飞书消息卡片模板生成"""

import json
import logging
from typing import Optional
from datetime import datetime

from sources.base import Digest

logger = logging.getLogger(__name__)

# 飞书卡片颜色
HEADER_COLORS = ["blue", "wathet", "turquoise", "green", "yellow", "orange", "red", "purple"]

# 每个字段的图标前缀
FIELD_ICONS = {
    "one_liner": "💡 ",
    "chinese_overview": "📖 ",
    "analogy": "🔥 ",
    "problem": "🎯 ",
    "method_comparison": "⚖️ ",
    "core_method": "🔬 ",
    "results": "📊 ",
    "limitations": "⚠️ ",
    # 旧版字段（保留兼容）
    "method": "🔬 ",
    "diff_from_prior": "⚡ ",
    "metrics": "📊 ",
    "engineering_insight": "🛠️ ",
    "deployment": "🚀 ",
    "lessons_learned": "📝 ",
    "target_audience": "🎯 ",
}

FIELD_LABELS = {
    "one_liner": "一句话结论",
    "chinese_overview": "中文精读",
    "analogy": "30 秒类比",
    "problem": "要解决什么问题",
    "method_comparison": "已有方法对比",
    "core_method": "核心方法拆解",
    "results": "实验结果",
    "limitations": "局限性",
    # 旧版字段（保留兼容）
    "method": "核心方法",
    "diff_from_prior": "和已有方法的区别",
    "metrics": "实验/业务指标",
    "engineering_insight": "对搜广推工程的启发",
    "deployment": "可能的落地方式",
    "target_audience": "适合谁读",
}


def truncate_text(text: str, max_len: int = 800) -> str:
    """截断文本到指定长度，保留完整性"""
    if len(text) <= max_len:
        return text
    return text[:max_len] + "...(已截断)"


def _build_paper_section(digest: Digest, label: str, max_field_len: int = 5000) -> dict:
    """构建单篇论文的卡片 section（div element）"""
    paper = digest.paper
    source_icon = "📄" if not paper.is_engineering else "📝"
    source_tag = "学术论文" if not paper.is_engineering else "工程博客"

    # 构建每篇论文的详细内容
    # 原文链接放在标题下方，最显眼的位置
    url_line = f"🔗 [原文链接]({paper.url})" if paper.url else "🔗 *（无原文链接）*"
    content_parts = [
        f"**{source_icon} {label}. {paper.title}**",
        f"*{source_tag} | {', '.join(paper.authors[:4])} | {paper.published_date or ''}*",
        url_line,
        "",
    ]

    # 字段映射：字段名 -> Digest 属性
    # 新格式：独立模块
    field_map = [
        ("one_liner", digest.one_liner),
        ("analogy", digest.analogy),
        ("problem", digest.problem),
        ("method_comparison", digest.method_comparison),
        ("core_method", digest.core_method),
        ("results", digest.results),
        ("limitations", digest.limitations),
    ]

    # 如果新字段都为空，回退到旧版 chinese_overview（兼容旧队列）
    new_fields_have_content = any(v for _, v in field_map if v and v.strip())
    if not new_fields_have_content and digest.chinese_overview:
        field_map = [
            ("one_liner", digest.one_liner),
            ("chinese_overview", digest.chinese_overview),
            ("problem", digest.problem),
            ("method", digest.method),
            ("diff_from_prior", digest.diff_from_prior),
            ("metrics", digest.metrics),
            ("engineering_insight", digest.engineering_insight),
            ("deployment", digest.deployment),
            ("limitations", digest.limitations),
            ("target_audience", digest.target_audience),
        ]

    for field_name, field_value in field_map:
        if not field_value or field_value.strip() == "":
            continue
        icon = FIELD_ICONS.get(field_name, "• ")
        label = FIELD_LABELS.get(field_name, field_name)
        truncated = truncate_text(field_value.strip(), max_field_len)
        content_parts.append(f"{icon}**{label}:**\n{truncated}")
        content_parts.append("")

    markdown_content = "\n".join(content_parts)

    return {
        "tag": "div",
        "text": {
            "tag": "lark_md",
            "content": markdown_content,
        },
    }


def _build_horizontal_line() -> dict:
    """分割线"""
    return {"tag": "hr"}


def build_digest_card(
    digests: list[Digest],
    topic_name: str = "搜广推前沿日报",
    total_candidates: int = 0,
    max_content_length: int = 4000,
    daily_seq_start: int = 1,        # 当天已推送篇数+1，用于编号
) -> Optional[dict]:
    """
    构建飞书消息卡片

    Args:
        digests: 解读列表
        topic_name: 日报名称
        total_candidates: 当日候选总数
        max_content_length: 卡片内容的最大字符数
        daily_seq_start: 当天序号起点（第几篇），用于 YY-MM-DD(N) 编号

    Returns:
        消息卡片 JSON 字典，如果内容为空则返回 None
    """
    if not digests:
        logger.info("No digests to build card from")
        return None

    now = datetime.now()
    date_str = now.strftime("%Y-%m-%d")
    time_str = now.strftime("%H:%M")
    date_label = now.strftime("%y-%m-%d")  # 用于论文编号：YY-MM-DD(N)

    # 构建 header（精确到分钟）
    header_text = f"【{topic_name}】{date_str} {time_str}  今日第 {daily_seq_start} 篇"
    if total_candidates > 0:
        header_text = f"【{topic_name}】{date_str} {time_str}  今日第 {daily_seq_start} 篇"

    # 构建 elements
    elements = []

    # 摘要行
    summary_line = {
        "tag": "div",
        "text": {
            "tag": "lark_md",
            "content": f"📖 今日第 **{daily_seq_start}** 篇深度解读",
        },
    }
    elements.append(summary_line)
    elements.append(_build_horizontal_line())

    # 每篇论文
    content_length = 0
    for i, digest in enumerate(digests):
        seq = daily_seq_start + i  # 当天序号：如第 5 篇
        section = _build_paper_section(digest, f"{date_label}({seq})")

        # 估算内容长度
        text_content = section.get("text", {}).get("content", "")
        content_length += len(text_content)

        elements.append(section)

        # 如果内容超长，截断
        if content_length > max_content_length:
            logger.warning("Card content exceeds limit (%d > %d), truncating", content_length, max_content_length)
            elements.append({
                "tag": "div",
                "text": {
                    "tag": "lark_md",
                    "content": f"*⚠️ 内容过长，仅展示前 {i+1} 篇。完整内容请查看原文链接。*",
                },
            })
            break

        if i < len(digests) - 1:
            elements.append(_build_horizontal_line())

    # 页脚
    elements.append({
        "tag": "note",
        "elements": [
            {
                "tag": "plain_text",
                "content": f"🤖 搜广推论文速报 | {date_str} {time_str} | arXiv / Semantic Scholar / OpenReview / 工程博客",
            }
        ],
    })

    card = {
        "config": {
            "wide_screen_mode": True,
            "enable_forward": True,
        },
        "header": {
            "title": {
                "tag": "plain_text",
                "content": header_text,
            },
            "template": "blue",
        },
        "elements": elements,
    }

    return card


def build_empty_card(topic_name: str = "搜广推前沿论文速报", reason: str = "今日无匹配论文") -> dict:
    """构建空日报卡片（当天无论文时推送）"""
    now = datetime.now()
    today = now.strftime("%Y-%m-%d")
    time_str = now.strftime("%H:%M")

    return {
        "config": {
            "wide_screen_mode": True,
        },
        "header": {
            "title": {
                "tag": "plain_text",
                "content": f"【{topic_name}】{today} {time_str}",
            },
            "template": "grey",
        },
        "elements": [
            {
                "tag": "div",
                "text": {
                    "tag": "lark_md",
                    "content": f"😴 **{reason}**\n\n下次推送见。",
                },
            }
        ],
    }
