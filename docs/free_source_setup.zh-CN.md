# 免费数据源配置

[English](free_source_setup.md)

## 已落地文件

- `config/free_rss_feeds.csv`：无需账号的官方 RSS 源。
- `config/core_us_equity_aliases.csv`：核心美股观察池别名。
- `data/live/political_watchlist.csv`：真实发布链路的初始观察池。
- `data/live/source_items.csv`：定时 RSS pipeline 最近一次拉取的公开原始文本。
- `data/live/source_events.csv`：从 `source_items.csv` 确定性抽取出的事件。
- `data/live/political_events.csv`：Advisor 稳定读取的真实事件输入，由 RSS/source pipeline 刷新，也可以人工核验后维护。
- `data/live/source_tracker.csv`：观察池与事件合并后的 tracker。

## 当前稳定版保留的数据源

当前可直接跑：

- White House presidential actions RSS。
- SEC press releases RSS。
- SEC speeches/statements RSS。
- Federal Reserve press releases RSS。
- Federal Reserve speeches/testimony RSS。
- NIST general / cybersecurity / energy RSS。
- CISA news RSS。
- 人工整理后的官方来源、发行人公告和财经媒体 lead CSV。

FTC press release RSS 暂时只作为候选源记录在 `docs/source_registry.md`；当前 Python fetcher 验证时返回 403，因此不放入默认稳定配置。

运行 RSS：

```bash
gh workflow run "RSS Source Pipeline" \
  --repo QuantStrategyLab/PoliticalEventTrackingResearch \
  -f feeds_path=config/free_rss_feeds.csv \
  -f aliases_path=config/core_us_equity_aliases.csv \
  -f watchlist_path=data/live/political_watchlist.csv \
  -f max_items_per_feed=50 \
  -f commit_outputs=true
```

## 暂缓的数据源

本版本先不接入：

- X / Twitter。
- Truth Social。
- Longbridge 社区 topics、profile activities、关注列表。
- 任何需要 Cookie、验证码或登录态页面抓取的数据源。

这些源后续可以重新评估，但不进入当前稳定发布版。

## 推荐运营流程

1. RSS pipeline 定时生成并提交 `data/live/source_items.csv`、`source_events.csv`、`political_events.csv`、`source_tracker.csv`、`source_fetch_status.json` 和 `source_manifest.json`。
2. 人工来源仍可以通过 `Source Event Pipeline` 输入 `source_items.csv`，再选择 `commit_outputs=true` 写回 live CSV。
3. 如果单个 RSS 源失败，workflow 会继续处理其他源，并把失败写入 `source_fetch_status.json`；连续失败的源再单独移除或替换。
4. 如果 RSS 拉到了文章但事件为空，优先检查 alias 覆盖；很多官方政策只写主题词，不写公司名。
5. 发布 Advisor 时使用：

```bash
gh workflow run "Publish Model Recommendations Site" \
  --repo QuantStrategyLab/QuantAdvisorResearch \
  -f as_of=2026-05-30 \
  -f political_events_path=data/live/political_events.csv \
  -f political_watchlist_path=data/live/political_watchlist.csv \
  -f ai_signal_path=data/output/latest_signal.json
```

如果 `political_events_path` / `political_watchlist_path` 不在 `examples/` 下，Advisor 输出会标记为 `source_mode=operator_supplied`。

## 长线证据边界

本仓库可以给长线推荐提供官方来源加分，但不要求每个长线候选都必须有近期政策/新闻事件。长线主题归属和语义背景由 `ResearchSignalContextPipelines` 维护；本仓库只在存在 SEC 文件、发行人公告、政府采购、Federal Register、官方拨款或政策文件时提供点时事实证据。

因此 Advisor 里出现“政策/新闻分数低”并不必然是采集失败，也可能只是该标的当前主要来自主题背景和动量。
