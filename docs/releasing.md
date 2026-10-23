# 发布流程

源码版本、Git tag、GitHub Release 和本机安装分别验收。正式载体为 GitHub wheel、sdist 与 SHA256SUMS；本项目不发布到 PyPI。

## 版本与兼容性

稳定版沿现有版本线连续递增 patch：`0.3.0` → `0.3.1` → `0.3.2`。原 `0.4.0rc1` 从未正式发布，其功能整合进入 `0.3.1`，旧候选验证记录保留原标签。应用版本不等于数据库 schema；`0.3.1` 与该候选均使用 schema 2。Agent HTTP 结果在 `data` 字段，旧客户端须按[机器契约](../.agents/skills/clash-verge-monitor/references/output-contract.md)读取。

发布不清理历史、不改保留策略、不自动覆盖或移动账本。schema 2 升级只采用原库；仅低于 schema 2 的数据库需要迁移前备份与事务迁移。

## 准备与 PR 门禁

在受管工作树中修改 `pyproject.toml`、包内 `__version__`、Changelog、README、Skill 契约和官网版本入口。准备时 Changelog 可为 `Unreleased`，正式 tag 必须有发布日期。

```sh
python3 -m pip install -r requirements-dev.txt
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src python3 -B -W error::ResourceWarning -m unittest discover -s tests -v
PYTHONPATH=src python3 -m compileall -q src tests scripts
python3 scripts/check_repository_policy.py --allow-dirty
python3 "$CODEX_HOME/skills/.system/skill-creator/scripts/quick_validate.py" .agents/skills/clash-verge-monitor
git diff --check
python3 -m build
python3 -m twine check dist/*.whl dist/*.tar.gz
python3 scripts/check_release.py --allow-dirty --dist-dir dist
python3 scripts/verify_distribution.py --dist-dir dist
```

提交并推送 PR 后，等待精确 head 的六项检查：Repository policy、四组 OS/Python Tests、Distribution。规则来源为 `.github/main-ruleset.json`，要求分支最新、讨论解决、squash 合并、禁止 force/delete，无 bypass actor。单维护者不设第二人批准要求。确认 Ready、可合并、head/base 未漂移后，用 `gh pr merge --squash --match-head-commit <sha>`；禁止 `--admin`。

`.github/tag-ruleset.json` 禁止更新和删除已创建的发行 tag。配置改动通过 GitHub API 应用，并读回完整规则，不能只提交 JSON 就声称门禁生效。

## 正式发布

只从干净、与远端 main 对齐且合并后 CI 通过的工作树发 tag。发布 tag 必须显式得到用户授权。以 `0.3.2` 为例：

```sh
git fetch origin main --tags
python3 scripts/check_repository_policy.py --tag v0.3.2
git tag -a v0.3.2 -m 'Release v0.3.2'
git push origin v0.3.2
```

Tag 推送触发 Release 工作流，重复完整 CI，要求 tag commit 等于当前 main；随后构建、Twine 校验、包内容与版本检查、隔离 wheel 安装烟测，再生成校验和并创建 Release。只有 publish job 拥有 `contents: write`。已存在的 Release 创建失败，不覆盖或删除资产。不要并行手动创建同名 Release。

```sh
gh run list --repo timmyagentic/clash-verge-monitor --workflow release.yml --limit 5
gh release view v0.3.2 --repo timmyagentic/clash-verge-monitor
gh release download v0.3.2 --repo timmyagentic/clash-verge-monitor --dir /absolute/new/download-directory
```

在下载目录执行 `shasum -a 256 -c SHA256SUMS`；用下载的 wheel 再执行隔离安装烟测。核对 tag、main commit、Release 资产版本、下载哈希与工作流结论后，才称为正式发布。官网更新在 Release 可下载后部署，并读回版本链接。

## 本机升级与历史保留

先运行 bootstrap status 和 health，记录安装清单、数据库绝对路径、schema、服务参数与心跳；从干净 tag 工作树预演：

```sh
python3 .agents/skills/clash-verge-monitor/scripts/bootstrap.py install --source "$PWD" --database /absolute/existing/ledger.sqlite --dry-run --pretty
```

确认 `database_action=adopt_existing`、schema 2、控制器/采样间隔/监听范围正确。切换前记录原始明细最大 ID、行数、内容校验和和已结束日期汇总。升级仅切换运行时，保留原库、旧运行时、安装清单/plist checkpoint 和日志；不执行 retention、prune、compact、VACUUM 或历史重建。

```sh
python3 .agents/skills/clash-verge-monitor/scripts/bootstrap.py install --source "$PWD" --database /absolute/existing/ledger.sqlite --load --pretty
python3 .agents/skills/clash-verge-monitor/scripts/bootstrap.py status --pretty
python3 .agents/skills/clash-verge-monitor/scripts/monitor.py health --pretty
```

升级后验收：版本/tag commit、`source_modified: false`、原数据库路径/schema、切换前所有原始行内容相同、已结束日期日/小时汇总及心跳不变，两个服务 running、心跳推进、自然流量增长、网页与 API 可用。维护期间的采样断档应如实记录。失败时使用安装 checkpoint 恢复旧运行时，不覆盖或降级真实账本。

真实整机休眠/唤醒、整机重启及无法执行的外部场景标记 UNVERIFIED；服务重启和合成测试不能替代这些证据。
