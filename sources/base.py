"""论文/文章数据模型"""

from dataclasses import dataclass, field
from typing import Optional
from datetime import datetime


@dataclass
class Paper:
    """统一的论文/文章数据模型，所有源均转换为该格式"""
    external_id: str           # 唯一 ID：arxiv_id / doi / URL hash
    title: str
    authors: list[str] = field(default_factory=list)
    abstract: str = ""
    source: str = ""           # 'arxiv' / 'semantic_scholar' / 'openreview' / 'engineering_blog'
    url: str = ""
    published_date: Optional[str] = None  # ISO 格式日期字符串
    is_engineering: bool = False          # 是否为工程博客文章
    extra: dict = field(default_factory=dict)  # 源特有信息

    def __hash__(self):
        return hash(self.external_id)

    def __eq__(self, other):
        if not isinstance(other, Paper):
            return False
        return self.external_id == other.external_id


@dataclass
class Digest:
    """论文解读结果"""
    paper: Paper
    one_liner: str = ""           # 一句话结论
    chinese_overview: str = ""    # 中文精读（300-500字，连贯叙述论文核心故事）
    problem: str = ""             # 解决了什么问题
    method: str = ""              # 核心方法
    diff_from_prior: str = ""     # 和已有方法的区别
    metrics: str = ""             # 实验/业务指标
    engineering_insight: str = "" # 对搜广推工程的启发
    deployment: str = ""          # 可能的落地方式
    limitations: str = ""         # 局限性/坑
    target_audience: str = ""     # 适合谁读
    raw_digest: str = ""          # LLM 返回的原始解读文本
    relevance_score: float = 0.0  # 相关性分数
