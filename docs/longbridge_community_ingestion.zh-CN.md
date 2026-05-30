# Longbridge 社区内容接入

## 结论

Longbridge 可以作为“社区高手观点/高收益用户观点”的研究线索源，但不应直接当作一手事实源。

当前官方能力更适合两种方式：

- 优先用 topic search 按主题关键词搜索，再拉详情，从正文里抽股票。
- 按股票代码拉社区 topics 只适合补充验证，不适合作为“大佬先说了什么股票”的主入口。

我没有在官方文档里看到“我关注的人动态流” endpoint。因此如果要只追踪你关注的大佬，需要维护一个本地作者白名单：

```csv
member_id,name,label,notes
10086,Jane Doe,top_performer,example
```

运行导入时用 `--author-allowlist` 过滤。只填 `member_id` 最稳；如果拿不到 `member_id`，先填显示名，后续从 topic detail 的 author 信息补全。

## 推荐流程

1. 用 Longbridge 官方 CLI/SDK 获取 topics 或 detail JSON。
2. 把 JSON 放到仓库外部或 `data/input/`。
3. 用本仓库归一化成 `source_items.csv`：

```bash
python scripts/import_longbridge_topics.py \
  --input data/input/longbridge_topics.json \
  --author-allowlist data/live/longbridge_followed_authors.csv \
  --min-likes 5 \
  --output data/output/longbridge_source_items.csv
```

如果本机已安装并登录 Longbridge CLI，也可以由本仓库调用 CLI 拉取：

```bash
python scripts/fetch_longbridge_cli_topics.py \
  --keywords config/longbridge_topic_keywords.csv \
  --include-details \
  --raw-output data/output/longbridge_topics.raw.json \
  --source-items-output data/output/longbridge_source_items.csv \
  --author-allowlist data/live/longbridge_followed_authors.csv \
  --min-likes 5
```

4. 抽取个股 mention：

```bash
python scripts/extract_source_mentions.py \
  --raw-items data/output/longbridge_source_items.csv \
  --aliases config/core_us_equity_aliases.csv \
  --output data/output/longbridge_source_events.csv
```

## 置信度规则

- `community_research_lead` 默认 low confidence。
- 大佬观点只能说明“值得看”，不能说明事件真实发生。
- 如果帖子提到政策、订单、公司动作，应继续匹配 White House、SEC、公司 IR、X/Truth Social 一手帖或可信媒体。
- 只有经过一手源确认后，才把确认事件写入 `data/live/political_events.csv`。

## 不建议做的事

- 不建议抓取 Longbridge 私人关注流、登录态页面或绕过平台访问控制。
- 不建议把关注作者的历史收益率直接当作未来信号权重。
- 不建议把单篇社区观点直接推到自动交易链路。

## 需要你提供的配置

- 如果只导入 JSON：你需要从 Longbridge CLI/SDK 或网页手工拿到 topic list/detail JSON。
- 如果自动拉取：需要安装 Longbridge CLI，并完成官方 OAuth 登录。
- 如果要只看“你关注的大佬”：需要把作者 `member_id` 或显示名填入 `data/live/longbridge_followed_authors.csv`。
- 如果要先听大佬说股票：维护 `config/longbridge_topic_keywords.csv`，从宽主题搜索开始，不要从股票列表开始。
