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
    one_liner: str = ""           # 面试一句话（≤50字）
    chinese_overview: str = ""    # (旧)中文精读完整文章，新格式不再使用
    analogy: str = ""             # 30秒类比
    problem: str = ""             # 解决了什么问题
    method_comparison: str = ""   # 已有方法对比
    core_method: str = ""         # 核心方法拆解
    results: str = ""             # 实验结果 + 业务含义
    limitations: str = ""         # 局限性/坑
    # 以下为旧版字段保留（与老队列兼容）
    method: str = ""              # (旧)核心方法
    diff_from_prior: str = ""     # (旧)和已有方法的区别
    metrics: str = ""             # (旧)实验/业务指标
    engineering_insight: str = "" # (旧)对搜广推工程的启发
    deployment: str = ""          # (旧)可能的落地方式
    target_audience: str = ""     # (旧)适合谁读
    raw_digest: str = ""          # LLM 返回的原始解读文本
    relevance_score: float = 0.0  # 相关性分数
