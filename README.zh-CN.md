# PoliticalEventTrackingResearch

[English](README.md) | [简体中文](README.zh-CN.md)

QuantStrategyLab 的确定性研究仓库，用来验证“公开持仓/交易披露 + 官方讲话/公开材料 + 政策资金事件”能否形成可追踪的美股事件线索。

## 仓库定位

这是研究证据仓库，不是 AI 仓库，也不是交易执行仓库。

它负责：

- 把公开披露、官方讲话、政策资金、发行人公告、财经媒体 lead、市场反应事件整理成统一 CSV 结构
- 从观察池和事件时间线生成候选追踪表
- 用本地日线收盘价做轻量事件研究
- 保留来源链接、置信度和人工复核入口

本次稳定发布版先不包含：

- X / Twitter 采集
- Truth Social 采集
- Longbridge 社区、用户主页、关注列表采集
- 登录态页面抓取或 Cookie 型采集器

它不负责：

- 券商 API、下单、账户同步
- Telegram 或实盘通知
- 受版权限制的行情数据分发
- 对利益冲突作法律结论
- AI 生成的长期影子信号；这类产物继续归 `AiLongHorizonSignalPipelines`
- 直接把信号推广到实盘策略

## 当前状态

当前提交的 `examples/` 数据是完全合成的 schema fixture，只用于跑通工具链，不是投资证据，也不是从任何文章抽取出来的样本。

事件类型：

- `disclosure_buy`：公开财务披露或交易披露中的买入
- `public_mention`：官方讲话、发行人声明或财经媒体 lead 中的公开点名
- `policy_capital`：政府入股、采购、产业政策资金支持
- `market_reaction`：财报、合同、分析师评级或价格反应标记

## 本地验证

生成合成示例追踪表：

```bash
python scripts/build_tracker.py \
  --watchlist examples/political_watchlist.example.csv \
  --events examples/political_events.example.csv \
  --output data/output/political_tracker.example.csv
```

把官方来源、发行人公告和财经媒体线索归一化为事件 schema：

```bash
python scripts/import_source_events.py \
  --input examples/official_records.example.csv \
  --output data/output/official_events.example.csv
```

从官方讲话 / RSS / 财经媒体导出的原始文本 CSV 抽取 mention 事件：

```bash
python scripts/extract_source_mentions.py \
  --raw-items examples/source_items.example.csv \
  --aliases examples/symbol_aliases.example.csv \
  --output data/output/source_events.example.csv
```

把 RSS/Atom 拉取为同一个原始文本 schema：

```bash
python scripts/fetch_rss_sources.py \
  --feeds examples/rss_feeds.example.csv \
  --output data/output/rss_source_items.example.csv \
  --max-items-per-feed 10
```

`.github/workflows/rss_source_pipeline.yml` 会拉取配置的 RSS/Atom，抽取 mention，生成 tracker，并上传为 artifact。

`.github/workflows/source_event_pipeline.yml` 可处理人工提供的 `source_items.csv`，生成 `source_events.csv` 和 `source_tracker.csv` 并上传为 GitHub Actions artifact。它只产出事件 artifact，不生成投资建议。

用合成价格样本跑事件研究：

```bash
python scripts/run_event_study.py \
  --events examples/political_events.example.csv \
  --prices examples/price_history.example.csv \
  --windows 1,2 \
  --output data/output/event_study.example.csv
```

运行测试：

```bash
python -m pytest -q
```

## 研究判断

这类“追踪效果”可以拆成三个可验证问题：

1. **能不能第一时间知道谁进入观察池**：需要结构化公开披露和政策/持仓来源。
2. **能不能捕捉公开点名**：需要按时间记录官方讲话、公告、新闻稿和媒体 lead。
3. **点名后是否有可交易的统计优势**：需要事件研究和样本外验证，不能只看少数轶事案例。

本仓库先解决前两步的数据结构和复盘框架；第三步需要更多点位和真实行情输入。后续如果需要 LLM 处理长文本，只能作为可替换的抽取工具，不能把模型判断结果写成核心信号合同。

免费数据源配置见 [docs/free_source_setup.zh-CN.md](docs/free_source_setup.zh-CN.md)。

## 跨板块来源原则

稳定源不局限于 AI 板块。半导体、数据中心电力、网络安全、国防、能源、金融、医疗、消费平台、工业和 EV/汽车等方向，只要有 SEC、官方政策、发行人公告、政府采购或其他一手来源，都可以进入同一套 `source_items.csv` / `source_events.csv` 结构。

主题归属和长期语义判断由 `AiLongHorizonSignalPipelines` 维护；本仓库只负责点时事实证据，避免因为短期热点临时改变采集边界。
