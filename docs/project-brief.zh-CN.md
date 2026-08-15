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

## 当前版本与交付状态

截至 2026-08-15：

- 当前源码与正式发布线已升级为 `0.3.0`；不可变交付入口是 GitHub
  [`v0.3.0` Release](https://github.com/timmyagentic/clash-verge-traffic-ledger/releases/tag/v0.3.0)。
- `0.3.0` 包含策略 v2、TUN/UDP 归因、health/audit/evidence 加固、默认只读
  的 raw retention，以及可实际回收文件空间的 compaction。
- 仓库版本、本机安装版本与运行状态仍是三种独立事实；只有本机清单同时显示
  `0.3.0`、精确 tag commit 和 `source_modified: false`，才算从正式版本部署。
- `CHANGELOG.md` 记录正式版本内容，`docs/releasing.md` 定义干净源码、构建、
  tag、GitHub Release、下载回读和部署后健康检查的完整边界。

## 当前 MVP 已完成状态

`0.3.0` hardening 已作为当前 MVP 正式发布；`0.2.0` 保留为历史版本。

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
| 进程归因 | 已完成 | 优先使用 Mihomo metadata；controller 快照仍有缺口时至多批量读取一次 TCP/UDP `lsof` 表，支持 localhost 与 TUN 虚拟源地址回退，并在同一连接生命周期内复用最后一次已知进程 |
| SQLite 存储 | 已完成 | 保存 raw delta、daily process、daily host |
| CLI `doctor` | 已完成 | 检查 controller、连接数、归因覆盖率和 `lsof` |
| CLI `run` | 已完成 | 前台持续采样并写库 |
| CLI `today` | 已完成 | 输出当天按进程或主机的汇总 |
| CLI `export` | 已完成 | 导出 Markdown 或 CSV |
| CLI `status` | 已完成 | 显示数据库、launchd 采样器状态、最后采样时间、原始明细行数和今日总量 |
| CLI `anomalies` | 已完成 | 按高流量、未知进程占比和前日突增给出异常提示 |
| CLI `web` | 已完成 | 提供本机只读 Web dashboard，含汇总、7 日趋势、异常提示、进程和主机表 |
| CLI `prune` | 已完成 | 默认只预演；显式 `--apply` 才删除指定日期之前的 raw delta，daily rollup 保留 |
| CLI `compact` | 已完成 | 默认只预演；显式 `--apply` 后删除选定 raw 明细、保留 daily rollup、执行 SQLite `VACUUM` 并报告实际回收字节 |
| launchd 安装/卸载 | 已完成 | 生成并加载 per-user LaunchAgent，让采样器登录后自动运行 |
| 单元测试 | 已完成 | 覆盖解析、增量、`lsof`、存储、导出、服务、状态、异常、Web dashboard 和压缩 |

## 已验证结果

2026-08-15 01:04（CST）在这台 Mac 上的实机快照：

- `0.3.0` 发布候选的 60 个单元测试全部通过，Skill 校验、Python 编译和
  `git diff --check` 通过。
- wheel 与 sdist 构建成功，Twine 元数据检查通过；sdist 包含 Runtime、Skill、
  Changelog 与发布文档且不包含 Python 缓存，全新 venv 安装 wheel 后报告
  `0.3.0` 并能打开完整 CLI。
- health 为 `healthy`：sampler 和 Web LaunchAgent 均在运行，controller 可达，
  43 条实时连接全部归因，最新样本年龄约 0.06 秒。
- 本机 dashboard 返回 HTTP 200，单次请求约 0.04 秒。
- 账本已按 hardening 部署时间清理，仅保留
  `2026-08-09T18:17:32.703480+08:00` 之后的数据；最早实际样本是
  `2026-08-09T18:17:43.883615+08:00`，旧库副本已删除。
- 这仍是 `source_modified: true` 的本机验证，不是 tag、Release 或正式部署证明。

连接数、归因率、样本时间和账本大小是运行时数据，后续会变化。2026-07-19
的 `0.2.0` 历史验证保留在
`docs/test/runs/2026-07-19-skill-first-auditor.md`；本次候选验证记录在
`docs/test/runs/2026-08-15-v0.3.0-release-candidate.md`。

## 使用方式

开发模式运行：

```bash
cd /Users/timmy/Projects/clash-verge-traffic-ledger
PYTHONPATH=src python3 -m clash_verge_traffic_ledger doctor
PYTHONPATH=src python3 -m clash_verge_traffic_ledger run --interval 1
PYTHONPATH=src python3 -m clash_verge_traffic_ledger today
PYTHONPATH=src python3 -m clash_verge_traffic_ledger status
PYTHONPATH=src python3 -m clash_verge_traffic_ledger anomalies
PYTHONPATH=src python3 -m clash_verge_traffic_ledger web --port 8765
PYTHONPATH=src python3 -m clash_verge_traffic_ledger compact --before 2026-07-01 --dry-run
```

安装后运行：

```bash
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -e .
clash-verge-traffic-ledger doctor
clash-verge-traffic-ledger run --interval 1
clash-verge-traffic-ledger today
clash-verge-traffic-ledger status
clash-verge-traffic-ledger anomalies
clash-verge-traffic-ledger web --port 8765
```

默认数据库位置是当前工作目录下：

```text
data/ledger.sqlite
```

## 当前 MVP 的边界

这个 MVP 有几个明确边界：

- 它只统计启动采样之后的未来流量，不能补算旧日志里的精确历史流量。
- 它已有 launchd 安装/卸载命令，但还没有图形化安装器。
- 它已有本机只读 Web UI，但还没有菜单栏 UI。
- 它依赖 Mihomo metadata 和采样瞬间仍可见的本地 socket 做进程归因；端口归属有歧义或 socket 已消失时仍会保守显示为 `unknown`。
- 它已有基础异常提示，但还没有长期趋势建模或可配置规则集。

这些边界是有意保留的。第一版先证明“连接采样、增量计算、进程归因、SQLite 汇总”这条主链路可靠；当前阶段已经在这条主链路上补了常驻采样、状态查询、异常提示、本机只读展示和 raw 明细压缩。

## 2026-08-09 审计器加固

针对长期账本实测中暴露的归因和解释问题，审计策略升级到版本 2：

- TUN 的 `198.18.0.1` 源地址不再绕过进程查询，并补齐 UDP socket；`lsof` 从“每连接一次”改为“controller 快照之后按需至多一次”。
- 同一 connection id 偶发丢失进程 metadata 时复用最后一次可靠归因，连接消失后立即清除缓存。
- 采样周期扣除本轮工作耗时，避免实际采样间隔持续漂移。
- `unknown_process_ratio` 增加 100 MiB 最小字节门槛，并从流量异常结论中分离；长期不变的高 unknown 只作为覆盖率诊断，不再仅凭 75% 比例升级为 critical。
- health 同时报告 `sampling_ready` 与 `attribution_ready`；采样新鲜但归因率低时整体状态为 degraded。
- audit 报告最新样本、样本年龄和窗口是 complete、partial 还是 missing；当天数据不再伪装成完整日。
- evidence 增加源地址、逐连接流量统计和连接起始分钟分布，并按源地址识别周期簇，避免 localhost 杂流量掩盖 TUN 的固定分钟重复下载模式。
- compact 在保留日汇总的同时执行 `VACUUM`，输出压缩前后文件大小与实际回收量。

## 为什么 MVP 先做 CLI + SQLite

CLI + SQLite 的组合适合这个阶段，原因是：

- 不需要引入 Web 框架，项目复杂度低。
- SQLite 适合本机账本数据，易备份、易查询、易迁移。
- CLI 可以直接跑在当前 Mac 上验证真实 Clash Verge 环境。
- 后续菜单栏、趋势图和更完整的异常规则都可以复用同一套采样和数据库层。

MVP 的重点不是视觉展示，而是把流量数据采准、存稳、能查。

## 非 MVP 后续优先级

当前本地 CLI/SQLite/Web MVP 已收口。后续如果要从 MVP 走向更完整产品，可以按这个顺序推进：

1. 实机安装并长期观察 launchd sampler 的稳定性和资源占用。
2. 为异常规则增加配置文件和多日趋势基线。
3. 为 Web UI 增加更长时间范围、筛选和导出入口。
4. 评估菜单栏入口或打包成轻量 macOS app。
5. 在首次 schema 变更前增加数据库迁移版本号；`0.3.0` 已建立并走通手工
   发布流程，后续再决定是否自动化 tag/Release 与产物校验。

## 项目判断

当前 MVP 已经完成了立项时最重要的技术验证：Clash Verge Rev 的本机 controller 可访问，未来流量可以被持续采样并写入账本，进程级归因在当前机器上有可用覆盖率。

它还不是完整产品，但已经是一个可继续迭代的本地项目，而不是一次性的排查脚本。
