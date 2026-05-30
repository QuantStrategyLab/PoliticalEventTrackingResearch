# 免费数据源配置

## 已落地文件

- `config/free_rss_feeds.csv`：无需账号的官方 RSS 源。
- `config/core_us_equity_aliases.csv`：核心美股观察池别名。
- `config/free_x_queries.csv`：X recent-search 查询模板，需要 `X_BEARER_TOKEN` 后才能运行。
- `data/live/political_watchlist.csv`：真实发布链路的初始观察池。
- `data/live/political_events.csv`：人工核验后的真实事件输入，初始为空表头。

## 免费且无需注册

当前可直接跑：

- White House presidential actions RSS。
- SEC press releases RSS。
- SEC speeches/statements RSS。
- Federal Register API：无需 API key，适合作为下一步 API adapter。
- USAspending API：公开 endpoints 当前不需要 authorization，适合做政府合同/资金流 adapter。

运行 RSS：

```bash
gh workflow run "RSS Source Pipeline" \
  --repo QuantStrategyLab/PoliticalEventTrackingResearch \
  -f feeds_path=config/free_rss_feeds.csv \
  -f aliases_path=config/core_us_equity_aliases.csv \
  -f max_items_per_feed=25
```

## 免费但需要注册 key

- X API Recent Search：需要 X Developer / App Bearer Token。免费层是否够用取决于 X 当前政策和额度。
- Congress.gov API：需要 api.data.gov key，通常可免费申请。

配置 X：

```bash
gh secret set X_BEARER_TOKEN \
  --repo QuantStrategyLab/PoliticalEventTrackingResearch
```

运行 X：

```bash
gh workflow run "X Recent Search Pipeline" \
  --repo QuantStrategyLab/PoliticalEventTrackingResearch \
  -f queries_path=config/free_x_queries.csv \
  -f aliases_path=config/core_us_equity_aliases.csv \
  -f max_results=10
```

## 免费但建议谨慎

- Truth Social 没有稳定官方公开开发者接口。当前建议先用导出 JSON 或经确认合规的第三方工具，再导入 `source_items.csv`。
- 开源 `truthbrush` 可作为候选工具，但应先做合规和稳定性验证，不能直接作为高置信来源。

## 开源项目候选

- Federal Register 官方 API core：`usnationalarchives/federalregister-api-core`
- USAspending 官方 API：`fedspendingtransparency/usaspending-api`
- SEC EDGAR downloader：`jadchaar/sec-edgar-downloader`
- SEC EDGAR package：`sec-edgar/sec-edgar`
- Truth Social candidate：`w2rc/truthbrush`

这些项目只作为 adapter 参考，不直接引入依赖。当前仓库优先用标准库和 CSV artifact，降低 VPS 与供应链风险。

## 推荐运营流程

1. RSS/X/Truth Social 先生成 `source_items.csv` 和 `source_events.csv`。
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
