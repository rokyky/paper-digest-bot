# 搜广推论文日报机器人 (PaperDigestBot)

每天 8:00 从学术源和工程博客抓取搜索、广告、推荐（搜广推）领域的最新论文/文章，生成当日 8 篇深度解读队列并立即推送第 1 篇；10:00~22:00 每 2 小时继续从队列取 1 篇，通过飞书群机器人推送结构化速报。

## 功能

- **多源抓取**：arXiv、Semantic Scholar、OpenReview、工程博客 RSS
- **LLM 筛选**：按搜广推主题关键词 + LLM 相关性判断，精选当前窗口 Top 1
- **深度解读**：每篇论文按 `paper-digest-bot/.提示词_论文精读飞书推送.md` 格式生成结构化解读（30秒类比、问题、方法对比、核心方法拆解、实验结果、局限性），而非简单翻译
- **飞书推送**：通过飞书自定义机器人发送结构化消息卡片
- **去重存储**：SQLite 记录已推送论文，避免重复推送
- **定时运行**：GitHub Actions 每天 8 个时间窗口（8:00 collect + push；10:00 / 12:00 / 14:00 / 16:00 / 18:00 / 20:00 / 22:00 push）
- **配置驱动**：所有参数通过 `config.yaml` 控制

## 快速开始

### 1. 克隆并安装

```bash
cd d:/my-projects/paper-digest-bot
python -m venv .venv

# Windows
.venv\Scripts\activate

# 安装依赖
pip install -r requirements.txt
```

或双击 `scripts/install_venv.bat` 一键安装。

### 2. 配置 API 密钥

编辑 `.env` 文件，填入必要的 API Key：

```env
# 飞书群机器人 webhook
FEISHU_WEBHOOK=https://open.feishu.cn/open-apis/bot/v2/hook/你的webhook

# LLM API（至少填一个）
OPENAI_API_KEY=sk-xxx
ANTHROPIC_API_KEY=sk-ant-xxx
```

### 3. 创建飞书机器人

1. 在飞书群中打开 **群设置 → 群机器人 → 添加机器人**
2. 选择 **自定义机器人**
3. 设置机器人名称（如"搜广推日报"）
4. 复制 webhook URL 到 `.env` 文件的 `FEISHU_WEBHOOK`
5. （可选）在安全设置中勾选 **IP 白名单** 或 **自定义关键词**

### 4. 测试运行

```bash
# dry-run 模式：只打印结果，不推送
python main.py --dry-run

# 完整运行
python main.py

# 指定只用 3 篇论文
python main.py --max-papers 3
```

### 5. 设置 GitHub Actions 定时任务（无需开电脑）

```bash
# 把代码推送到 GitHub
git push

# 在 GitHub 仓库设置 Secrets（Settings → Secrets and variables → Actions）：
# 添加 FEISHU_WEBHOOK 和 DEEPSEEK_API_KEY
```

之后每天自动按以下时间运行：**8:00 collect + push**，**10:00 / 12:00 / 14:00 / 16:00 / 18:00 / 20:00 / 22:00 push**

也可在 Actions 页面手动触发：**https://github.com/你的用户名/paper-digest-bot/actions**

## 项目结构

```
paper-digest-bot/
├── config.yaml              # 主配置文件
├── main.py                  # Pipeline 编排入口
├── .env                     # API 密钥（不提交 git）
├── requirements.txt         # Python 依赖
├── sources/                 # 论文/文章来源
│   ├── base.py                  # Paper / Digest 数据模型
│   ├── arxiv_source.py          # arXiv API
│   ├── semantic_scholar_source.py  # Semantic Scholar
│   ├── openreview_source.py     # OpenReview
│   ├── engineering_blog_source.py  # 工程博客 RSS
│   └── aggregator.py            # 多源聚合
├── llm/                     # LLM 处理
│   ├── client.py               # 统一 LLM 客户端（OpenAI / Claude / DeepSeek / Qwen）
│   ├── filter.py               # 相关性筛选 + 排序
│   └── summarize.py            # 深度解读生成
├── push/                    # 飞书推送
│   ├── feishu.py               # 飞书 webhook
│   └── card_template.py        # 卡片模板
├── storage/                 # 存储
│   └── sqlite_store.py         # SQLite 去重 + 历史
├── scripts/                 # 部署脚本
│   ├── install_venv.bat
│   └── schedule_windows.bat
└── logs/                    # 运行日志
```

## 配置说明

### config.yaml

```yaml
topic:
  name: "搜广推前沿日报"
  max_items: 1              # 每次推送篇数（每2小时推1篇）
  keywords: [...]           # 搜广推主题关键词

llm:
  filter:                   # 初筛模型（便宜）
    provider: deepseek
    model: deepseek-chat
  digest:                   # 解读模型（强模型）
    provider: deepseek
    model: deepseek-chat

push:
  channel: feishu
  feishu:
    webhooks: [...]         # 支持多个 webhook

sources:
  arxiv:
    categories: [cs.IR, cs.LG, cs.AI, stat.ML]
  engineering_blog:
    blogs: [...]            # RSS feed 列表
```

### LLM Provider 支持

| Provider | 配置值 | API Key 环境变量 | 推荐用途 |
|----------|--------|-----------------|---------|
| OpenAI   | `openai` | `OPENAI_API_KEY` | filter + digest |
| Claude   | `claude` | `ANTHROPIC_API_KEY` | digest（解读质量高） |
| DeepSeek | `deepseek` | `DEEPSEEK_API_KEY` | filter（性价比最高） |
| Qwen     | `qwen` | `QWEN_API_KEY` | filter（国内直连） |

**省钱建议**：
- `filter` 用便宜模型（gpt-4o-mini / claude-haiku / deepseek-chat）
- `digest` 用强模型（gpt-4o / claude-sonnet）

## 飞书卡片效果

每日推送卡片长这样，每篇论文包含**中文精读 + 结构化深度分析**：

```
┌─────────────────────────────────────────────┐
│ 【搜广推前沿日报】2026-06-12                │
│ 今日筛选 42 篇，精选 1 篇                     │
├─────────────────────────────────────────────┤
│ 📄 1. 论文标题                              │
│    作者 | arXiv | 2026-06-11                │
│                                             │
│ 📖 中文精读（NEW！）                         │
│    "这篇工作来自 Google，核心思路是...        │
│     和传统方法最大的区别在于...              │
│     对推荐系统来说最有价值的是..."           │
│                                             │
│ 💡 一句话结论：xxx                          │
│ 🎯 30 秒类比：xxx（生活例子）              │
│ 🔬 要解决什么问题：xxx                      │
│ ⚔️ 和已有方法的区别：xxx（对比表格）        │
│ ⚙️ 核心方法：xxx（3-4 个模块拆解）          │
│ 📊 实验结果：xxx（表格 + 业务含义）         │
│ ⚠️ 局限性/坑：xxx（3-5 个）                │
│ 🔗 原文链接                                 │
├─────────────────────────────────────────────┤
│ 📄 2. ...                                   │
│ ...                                         │
├─────────────────────────────────────────────┤
│ 🤖 PaperDigestBot 自动生成                   │
└─────────────────────────────────────────────┘
```

## 命令行选项

```bash
python main.py --help

选项：
  --dry-run         不推送，只打印结果
  --skip-fetch      跳过抓取阶段（测试用）
  --max-papers N    覆盖每日最大论文数
  --config PATH     指定配置文件路径
```

## 论文源说明

| 源 | API | 速率限制 | 是否需要 Key |
|---|-----|---------|------------|
| arXiv | arXiv API | 未公开限制，建议 3s 间隔 | 否 |
| Semantic Scholar | REST API | 未认证 100/5min，认证 1000/5min | 可选 |
| OpenReview | REST API | 宽松 | 否 |
| 工程博客 | RSS/Atom | 取决于博客 | 否 |

## Pipeline 执行流程

```
定时触发 / 手动运行
    │
    ├─ Stage 1: 多源抓取（并发）
    │   ├── arXiv API（按 cs.IR/LG/AI/ML 分类）
    │   ├── Semantic Scholar（种子论文推荐）
    │   ├── OpenReview（ICLR/NeurIPS/ICML）
    │   └── 工程博客 RSS（Google/Netflix/Pinterest/美团/阿里妈妈）
    │
    ├─ Stage 2: 数据库去重（过滤已推送论文）
    │
    ├─ Stage 3: LLM 相关性筛选 → 排序取 Top N
    │   ├── 初筛：title + abstract → relevant / not_relevant
    │   └── 排序：按工程价值打分
    │
    ├─ Stage 4: LLM 深度解读（每篇独立，按 .提示词_论文精读飞书推送.md 格式）
    │   ├── 30 秒类比 + 问题分析
    │   └── 结构化字段（方法拆解/实验/局限）
    │
    ├─ Stage 5: 飞书卡片推送 + 记录历史
    │
    └─ 完成摘要打印
```

## 常见问题

**Q: 多久推送一次？一次几篇？**
每天 8:00 先生成 8 篇队列并推第 1 篇，10:00~22:00 每 2 小时再推 1 篇（共 8 次），每次 1 篇。通过 `topic.max_items` 调整每篇数量；collect 模式会临时覆盖为 8 以填满当天队列。

**Q: 想只推学术论文/只推工程博客？**
在 `config.yaml` 中设置 `sources.engineering_blog.enabled: false` 或 `sources.arxiv.enabled: false`。

**Q: 在国内服务器上，调不了 OpenAI/Claude 怎么办？**
用 DeepSeek 或 Qwen（国产模型），在 config 里改 `llm.filter.provider: deepseek` 即可，不需海外网络。

**Q: 怎么添加更多关键词？**
在 `config.yaml` 的 `topic.keywords` 列表中添加。

**Q: 为什么我运行报错 "No module named 'xxx'"?**
确保已激活虚拟环境并执行了 `pip install -r requirements.txt`。
