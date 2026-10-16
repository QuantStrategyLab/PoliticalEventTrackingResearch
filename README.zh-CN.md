# PoliticalEventTrackingResearch

面向美股研究的公开政治与政策事件证据管线。

[English](README.md) | 简体中文

## 状态

实验性项目，使用风险自负。本项目不构成投资建议，也不保证任何交易结果。它的输出是研究证据，不是交易指令。

## 简介

PoliticalEventTrackingResearch 采集公开的政治与政策来源（例如免费的 RSS feed 和官方披露），并生成可追溯的研究产物：来源条目、抽取出的活动、关注列表匹配结果和事件研究输入。它只读取公开来源，输出 CSV 和 JSON，让研究者可以复现一条美股研究所需的证据链。它面向研究与工程审阅，不面向实盘交易。

## 不适用范围

它不提交券商订单。它不改变实盘仓位分配。它不产生自动交易指令，其报告也不构成投资建议。

## 快速开始

需要 Python 3.11 或更高版本。

```bash
python -m pip install -e '.[test]'
python -m pytest -q
```

命令行入口（均支持 `--help`）：

```bash
petr-fetch-rss-sources --help
petr-import-official-events --help
petr-build-tracker --help
```

## 配置

本管线通过输入文件配置，而不是环境变量。把 `examples/` 中的对应文件复制出来再修改。

| 文件 | 必填 | 用途 |
|---|---|---|
| `config/free_rss_feeds.csv` | 否 | 默认的公开 RSS feed 列表。 |
| `config/core_us_equity_aliases.csv` | 否 | 把来源匹配到代码时使用的符号与名称别名表。 |
| `examples/*.csv` | 否 | 本地运行用的示例输入。 |

## 仓库结构

```
src/        库代码和命令实现
scripts/    命令行辅助脚本
config/     默认 feed 与别名表
examples/   示例输入
docs/       设计说明与输出契约
tests/      单元与契约测试
```

## 参与贡献

见 [CONTRIBUTING.md](CONTRIBUTING.md)。

## 安全

见 [SECURITY.md](SECURITY.md)。安全漏洞不要开公开 issue，也不要让凭据、私有数据和外部服务 token 进入 Git 或日志。

## 许可证

MIT，见 [LICENSE](LICENSE)。
