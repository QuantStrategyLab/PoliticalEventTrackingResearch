# 免费数据源配置

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
- 人工整理后的官方来源、发行人公告和财经媒体 lead CSV。

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

1. RSS pipeline 定时生成并提交 `data/live/source_items.csv`、`source_events.csv`、`political_events.csv` 和 `source_tracker.csv`。
2. 人工来源仍可以通过 `Source Event Pipeline` 输入 `source_items.csv`，再选择 `commit_outputs=true` 写回 live CSV。
3. 如果 RSS 拉到了文章但事件为空，优先检查 alias 覆盖；很多官方政策只写主题词，不写公司名。
4. 发布 Advisor 时使用：

```bash
gh workflow run "Publish Model Recommendations Site" \
  --repo QuantStrategyLab/QuantAdvisorResearch \
  -f as_of=2026-05-30 \
  -f political_events_path=data/live/political_events.csv \
  -f political_watchlist_path=data/live/political_watchlist.csv \
  -f ai_signal_path=data/output/latest_signal.json
```

如果 `political_events_path` / `political_watchlist_path` 不在 `examples/` 下，Advisor 输出会标记为 `source_mode=operator_supplied`。
