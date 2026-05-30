# PoliticalEventTrackingResearch

[English](README.md) | [简体中文](README.zh-CN.md)

QuantStrategyLab 的确定性研究仓库，用来验证“公开持仓/交易披露 + 公开讲话/社媒点名 + 政策资金事件”能否形成可追踪的美股事件线索。

## 仓库定位

这是研究证据仓库，不是 AI 仓库，也不是交易执行仓库。

它负责：

- 把公开披露、公开讲话、政策资金、市场反应事件整理成统一 CSV 结构
- 从观察池和事件时间线生成候选追踪表
- 用本地日线收盘价做轻量事件研究
- 保留来源链接、置信度和人工复核入口

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
- `public_mention`：白宫、演讲、采访、社媒或媒体中的公开点名
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

把官方来源、认证社媒和财经媒体线索归一化为事件 schema：

```bash
python scripts/import_source_events.py \
  --input examples/official_records.example.csv \
  --output data/output/official_events.example.csv
```

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
2. **能不能捕捉公开点名**：需要按时间记录白宫讲话、采访、社媒和新闻文本。
3. **点名后是否有可交易的统计优势**：需要事件研究和样本外验证，不能只看少数轶事案例。

本仓库先解决前两步的数据结构和复盘框架；第三步需要更多点位和真实行情输入。后续如果需要 LLM 处理长文本，只能作为可替换的抽取工具，不能把模型判断结果写成核心信号合同。
