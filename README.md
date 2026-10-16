# PoliticalEventTrackingResearch

Research-only pipeline that tracks public political and policy event evidence for US equity research.

English | [简体中文](README.zh-CN.md)

## Status

Experimental. Use at your own risk. This project is not financial advice and
does not guarantee any trading result. Its outputs are research evidence, not
trading instructions.

## What this is

PoliticalEventTrackingResearch ingests public political and policy sources,
such as free RSS feeds and official disclosures, and builds traceable research
artifacts: source items, extracted events, watchlist matches, and event-study
inputs. It reads only public sources and writes CSV and JSON output, so a
researcher can reproduce an evidence trail for US equity context. It is aimed
at research and engineering review, not at live trading.

## What this is not

It does not place broker orders. It does not mutate live allocations. It does
not produce automatic trading instructions, and its reports are not
recommendations.

## Quick start

Requires Python 3.11 or newer.

```bash
python -m pip install -e '.[test]'
python -m pytest -q
```

Explore the command-line entry points (each supports `--help`):

```bash
petr-fetch-rss-sources --help
petr-import-official-events --help
petr-build-tracker --help
```

## Configuration

The pipeline is configured through input files rather than environment
variables. Copy the matching file from `examples/` and edit it.

| File | Required | Purpose |
|---|---|---|
| `config/free_rss_feeds.csv` | No | Default public RSS feed list. |
| `config/core_us_equity_aliases.csv` | No | Symbol and name aliases used when matching sources to tickers. |
| `examples/*.csv` | No | Sample inputs for local runs. |

## Repository layout

```
src/        library code and command implementations
scripts/    command-line helpers
config/     default feed and alias tables
examples/   sample inputs
docs/       design notes and output contracts
tests/      unit and contract tests
```

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md).

## Security

See [SECURITY.md](SECURITY.md). Do not open a public issue for a vulnerability.
Keep credentials, private data, and external service tokens out of Git and logs.

## License

MIT. See [LICENSE](LICENSE).
