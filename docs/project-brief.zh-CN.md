# clash-verge-traffic-ledger 项目立项与 MVP 状态

日期：2026-07-02

## 一句话说明

`clash-verge-traffic-ledger` 是一个面向 Clash Verge Rev 的本机流量账本工具。它通过 Mihomo controller 的 `/connections` 接口持续采样，把未来发生的连接流量按进程和主机写入 SQLite，从而回答“今天哪些应用用了多少代理流量”。

## 立项背景

这个项目不是从一个抽象的流量监控想法开始的，而是从一次实际排查开始的。

最初目标是检查这台 Mac 上 Clash Verge Rev 的相关文件、运行状态、日志和流量异常。排查结果显示：

- Clash Verge Rev 正在运行，应用版本是 2.5.1。
- 实际核心进程是 `verge-mihomo-alpha`。
- Mihomo API 可以通过 Clash Verge 的 unix socket 访问：`/tmp/verge/verge-mihomo.sock`。
- 系统代理指向 `127.0.0.1:7897`，并且代理请求可以正常通过。
- Clash Verge 保存的历史日志能看到连接事件、域名和部分订阅余量快照，但不能可靠还原历史每条连接的上传/下载字节增量。

用户真正想回答的问题是：

- 每一天到底用了多少流量？
- 哪些应用用了最多代理流量？
- 有没有异常应用在偷偷跑流量？
- 后续能不能持续自动统计，而不是每次临时翻日志？

历史日志只能辅助判断连接活跃度，不能形成严格账本。因此项目方向从“解析旧日志”转成“从现在开始持续采样并记录未来流量”。

## 为什么不是直接用现有 Dashboard

调研过的相关开源项目包括：

- `MetaCubeX/metacubexd`
- `haishanh/yacd`
- `foru17/neko-master`
- `zhf883680/clash-traffic-monitor`
- `Mooouy/clash-traffic-monitor`
- `xth1227/Clash-Traffic-Bar`

这些项目提供了几个重要参考：

- MetaCubeXD/Yacd 很适合做实时 dashboard，但重点不是长期本机流量账本。
- Neko Master 有更完整的分析平台思路，但对这个本机 MVP 来说偏重。
- Go/Python 版本的 Clash traffic monitor 证明了 `/connections` + SQLite 这条路线可行。
- Clash-Traffic-Bar 证明了 macOS 上可以通过 Clash Verge 的 unix socket 和 `lsof` 做本机归因。

最终选择自己做一个很小的 MVP，原因是这个项目的核心需求不是“再做一个 dashboard”，而是把本机 Clash Verge 的未来代理流量变成可追溯的日账本。

## 名字为什么叫 clash-verge-traffic-ledger

底层协议依赖 Mihomo-compatible controller，所以它也可以连接普通 HTTP controller，例如 `http://127.0.0.1:9090`。

但这个项目的第一目标是这台 Mac 上的 Clash Verge Rev，默认入口也是 Clash Verge Rev 的 unix socket：

```text
/tmp/verge/verge-mihomo.sock
```

所以项目名把 `clash-verge` 放在前面，避免看起来像一个泛泛的 Mihomo 工具。

`ledger` 表示账本：它不是只显示当前速度，而是把每次采样的增量写入数据库，便于之后按天、按进程、按主机查询。

## 当前 MVP 已完成状态

当前 MVP 已经是可运行状态，并已推送到 GitHub。

GitHub 仓库：

```text
https://github.com/timmyagentic/clash-verge-traffic-ledger
```

本地路径：

```text
/Users/timmy/Projects/clash-verge-traffic-ledger
```

已完成能力：

| 模块 | 状态 | 说明 |
| --- | --- | --- |
| Clash Verge unix socket 连接 | 已完成 | 默认连接 `/tmp/verge/verge-mihomo.sock` |
| HTTP controller 支持 | 已完成 | 可用 `--controller http://127.0.0.1:9090` 指定 |
| `/connections` 采样 | 已完成 | 从 Mihomo controller 读取当前连接 |
| 字节增量计算 | 已完成 | 以 connection id 为单位计算 upload/download delta |
| 首次采样基线 | 已完成 | 第一次看到连接时只建立基线，避免启动时误记旧流量 |
| 进程归因 | 已完成 | 优先使用 Mihomo metadata，再用 `lsof` 回退解析 localhost 端口 |
| SQLite 存储 | 已完成 | 保存 raw delta、daily process、daily host |
| CLI `doctor` | 已完成 | 检查 controller、连接数、归因覆盖率和 `lsof` |
| CLI `run` | 已完成 | 前台持续采样并写库 |
| CLI `today` | 已完成 | 输出当天按进程或主机的汇总 |
| CLI `export` | 已完成 | 导出 Markdown 或 CSV |
| 单元测试 | 已完成 | 覆盖解析、增量、`lsof`、存储和导出 |

## 已验证结果

在这台 Mac 上已经验证：

- 单元测试 8 个全部通过。
- `python -m clash_verge_traffic_ledger doctor` 可以访问 Clash Verge 的 unix socket。
- 当前 Mihomo 核心返回版本 `alpha-0ddf4bb`。
- 最近一次检查看到 30 条连接，其中 19 条可以归因到具体进程。
- 短采样 smoke test 能生成 SQLite 记录，并通过 `today` 输出日报。

## 使用方式

开发模式运行：

```bash
cd /Users/timmy/Projects/clash-verge-traffic-ledger
PYTHONPATH=src python3 -m clash_verge_traffic_ledger doctor
PYTHONPATH=src python3 -m clash_verge_traffic_ledger run --interval 1
PYTHONPATH=src python3 -m clash_verge_traffic_ledger today
```

安装后运行：

```bash
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -e .
clash-verge-traffic-ledger doctor
clash-verge-traffic-ledger run --interval 1
clash-verge-traffic-ledger today
```

默认数据库位置是当前工作目录下：

```text
data/ledger.sqlite
```

## 当前 MVP 的边界

这个 MVP 有几个明确边界：

- 它只统计启动采样之后的未来流量，不能补算旧日志里的精确历史流量。
- 它目前是前台 CLI 工具，还没有 launchd 常驻服务。
- 它目前没有 Web UI 或菜单栏 UI。
- 它依赖 Mihomo metadata 和 `lsof` 做进程归因，TUN 场景下部分连接可能仍然显示为 `unknown`。
- 它还没有做异常检测规则，只提供可靠的基础账本数据。

这些边界是有意保留的。第一版先证明“连接采样、增量计算、进程归因、SQLite 汇总”这条主链路可靠，再决定是否做 UI、后台服务和异常检测。

## 为什么 MVP 先做 CLI + SQLite

CLI + SQLite 的组合适合这个阶段，原因是：

- 不需要引入 Web 框架，项目复杂度低。
- SQLite 适合本机账本数据，易备份、易查询、易迁移。
- CLI 可以直接跑在当前 Mac 上验证真实 Clash Verge 环境。
- 后续 Web UI、菜单栏、launchd 都可以复用同一套采样和数据库层。

MVP 的重点不是视觉展示，而是把流量数据采准、存稳、能查。

## 后续优先级

建议下一阶段按这个顺序推进：

1. 增加 launchd plist 和安装/卸载命令，让采样器开机或登录后自动运行。
2. 增加 `status` 命令，显示采样器是否在运行、数据库最后写入时间、今日总量。
3. 增加 `anomalies` 命令，按应用、主机、突增流量和未知进程比例做异常提示。
4. 增加简单 Web UI，只读展示 daily process、daily host 和趋势图。
5. 增加保留策略，例如按天压缩 raw delta 或清理旧明细。

## 项目判断

当前 MVP 已经完成了立项时最重要的技术验证：Clash Verge Rev 的本机 controller 可访问，未来流量可以被持续采样并写入账本，进程级归因在当前机器上有可用覆盖率。

它还不是完整产品，但已经是一个可继续迭代的本地项目，而不是一次性的排查脚本。
