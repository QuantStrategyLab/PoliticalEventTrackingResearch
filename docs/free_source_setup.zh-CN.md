# 免费数据源配置

## 已落地文件

- `config/free_rss_feeds.csv`：无需账号的官方 RSS 源。
- `config/core_us_equity_aliases.csv`：核心美股观察池别名。
- `data/live/political_watchlist.csv`：真实发布链路的初始观察池。
- `data/live/political_events.csv`：人工核验后的真实事件输入，初始为空表头。

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
  -f max_items_per_feed=25
```

## 暂缓的数据源

本版本先不接入：

- X / Twitter。
- Truth Social。
- Longbridge 社区 topics、profile activities、关注列表。
- 任何需要 Cookie、验证码或登录态页面抓取的数据源。

这些源后续可以重新评估，但不进入当前稳定发布版。

## 推荐运营流程

1. RSS 或人工整理先生成 `source_items.csv` / `source_events.csv`。
2. 人工核验后，把确认事件写入 `data/live/political_events.csv`。
3. 发布 Advisor 时使用：

```bash
gh workflow run "Publish Model Recommendations Site" \
  --repo QuantStrategyLab/QuantAdvisorResearch \
  -f as_of=2026-05-30 \
  -f political_events_path=data/live/political_events.csv \
  -f political_watchlist_path=data/live/political_watchlist.csv \
  -f ai_signal_path=data/output/latest_signal.json
```

如果 `political_events_path` / `political_watchlist_path` 不在 `examples/` 下，Advisor 输出会标记为 `source_mode=operator_supplied`。
