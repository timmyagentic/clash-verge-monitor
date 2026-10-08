# 0.4.0rc1：可靠采集、可解释分析和维护

这是本地候选实现，尚未发布、合并或替换正式服务。运行时版本、源码版本和正式发布各自独立。

## 采集与计量

默认 `--controller auto`，依次探测当前 UID 的系统服务 socket、用户临时目录和旧 `/tmp/verge` 路径；已连通地址优先重用，失败后重新发现。明确指定的 HTTP/socket 地址永不自动切换目标。不会扫描其他用户的目录，也不会修改 Clash 路由。

采样事务同时保存字节增量、日/小时汇总、最近尝试和成功时间、分钟覆盖、内核总计数对照。零连接的成功采样也产生心跳。连续失败仅保存错误类别，连接/断连/基线重置记录为事件。重试采用有上限的退避。

同一数据库的常驻采样、迁移和维护互斥。旧版 0.3 不认识新锁，因此从旧版本升级前必须停止旧采样服务；安装器的 `--load` 会在迁移前停止这两个服务。

中断、负计数重置、控制接口身份改变、时钟倒退或超过 `max(5 秒, 3 × interval)` 的采样间隔都会重建基线。不会将休眠期间的累计流量记入唤醒分钟。初次看到连接时默认仅建基线；只有内核开始时间证明其是在连续成功采样区间新建，才计入初始字节。

**不可消除的轮询边界**：两个采样点之间建立并消失的短连接，以及在最后一次采样后立刻关闭的尾部流量仍可能漏计。内核总计数差额在可比较区间内报告这一缺口；它不能把漏计流量可靠归回应用。不要把可观察长连接的测试精度承诺给所有连接。

## 覆盖率与历史兼容

数据库 schema v2 使用 `PRAGMA user_version`，迁移在事务中追加表和索引，并从仍保留的原始明细生成小时汇总；原始明细与日汇总不重写。拒绝写入更高版本 schema。

- 心跳按分钟聚合，成功采样之间的有界间隔才算覆盖；失败、初次启动和断档不算。
- 历史没有心跳的日期显示 unknown，不补造历史状态，不把缺失画成零流量。
- 已结束日期至少 99% 覆盖才标记 complete；当天永远标记 partial。覆盖率采用本机记录日期的 24 小时日口径；跨时区/DST 的日期不能用于严格在线时长证明。
- 健康取决于最近成功心跳和最后一次尝试结果，进程存活不代表健康。
- policy v3 在分析窗口或基线覆盖不完整时降低案例置信度，将 critical 降为 warning。没有规则命中且覆盖未知时返回 insufficient_data。
- v2 case ID 不按 v3 静默重解释，须重新 audit 获取新 ID。

## 分析与导出

```sh
python -m clash_verge_traffic_ledger explore --database data/ledger.sqlite \
  --start 2026-08-22 --end 2026-08-22 --process codex --by minute --pretty
python -m clash_verge_traffic_ledger explore --database data/ledger.sqlite \
  --start 2026-08-22 --end 2026-08-22 --by route --pretty
python -m clash_verge_traffic_ledger web --database data/ledger.sqlite --port 8765
```

支持应用、域名、线路类型、小时、分钟、连接、规则、代理链。过滤参数为精确匹配；日期范围最多 367 天。应用/域名可点击进入分钟分布。网页每页 100 组，支持上一页/下一页及总量、上传、下载、时间排序，CSV 导出当前页；CLI 可指定 `--limit`（最大 1000）、`--offset` 和 `--sort`。响应包含 `total_groups` 和 `truncated`。

小时汇总保留应用、域名和代理/DIRECT/未知线路维度。分钟、连接、规则、链路仍依赖原始明细；`retained_detail` 对照日汇总报告明细是否已缺失，不能把部分明细误当完整历史。现有日级 `today`/`export` 可读取所有保留的日汇总。

网页仅监听 loopback，校验 Host/Origin，拒绝写请求，设置 no-store/CSP，并转义记录内容与 CSV 公式。页面及 `/api/explore`、`/api/audit`、`/api/evidence` 都只读。

## 保留与备份恢复

```sh
python -m clash_verge_traffic_ledger backup --database data/ledger.sqlite --output backups/ledger.sqlite
python -m clash_verge_traffic_ledger restore --database backups/ledger.sqlite --output data/restored.sqlite
# 审阅后添加 --apply；只能恢复到不存在的新路径，永不替换活跃数据库。
python -m clash_verge_traffic_ledger retention --database data/ledger.sqlite --config retention.toml
# 审阅计划后添加 --apply。没有自动定时删除。
```

配置示例：

```toml
[retention]
raw_days = 30
heartbeat_days = 90
event_days = 90
compact = false
```

保留小时与每日汇总。删除心跳后，旧日期覆盖变成未知。备份使用 SQLite backup API 获取一致性快照、校验完整性，再以不覆盖方式发布为权限 0600 的文件。备份文件包含本机联网元数据，按私有数据保存。

## 安装、升级和回滚

使用 Skill 的 `bootstrap.py install --dry-run --source <源码>` 查看计划。源码通过验证后，显式 `--load` 才切换后台服务；未指定 `--load` 不重启服务。

新运行时目录包含版本和源码摘要，同一版本不同源码不会覆盖正在运行的目录。更新保存安装清单及两个 plist 的 checkpoint；`--load` 时先备份已有数据库，再停止旧服务、迁移、切换新版。若迁移或加载失败，会返回失败；不得将此状态当成上线成功，使用 checkpoint 恢复或解决错误后重试。

```sh
python .agents/skills/clash-verge-traffic-auditor/scripts/bootstrap.py rollback \
  --checkpoint '<app-root>/backups/checkpoint-....json'
```

默认仅预览；`--apply --load` 才恢复并加载服务。旧 0.3 不支持 schema v2，回滚到旧版必须先把升级前备份恢复到新路径，再通过 `--database` 指定；不会降级或覆盖新账本。回滚可能不包含升级之后的新记录，两份数据库均应保留。

## 验证入口

```sh
PYTHONPATH=src python -m unittest discover -s tests -v
PYTHONPATH=src python scripts/verify_live_meter.py --database data/qa/new-live.sqlite
```

第二条需要本机 Clash 运行，只向 loopback 服务收发已知大小数据，经现有 mixed port。它不修改 Clash、正式数据库或正式服务。默认 7897，可传 `--proxy-port`。测试显式保留可观察传输尾部，短连接漏计由另外的内核差额回归覆盖。
