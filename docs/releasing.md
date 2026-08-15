# 发布流程

这份流程用于准备和发布 `clash-verge-traffic-ledger`。版本号写入源码、
本机安装成功、Git tag 存在和 GitHub Release 已发布是四个不同状态，不能
互相代替。

## 1. 发布边界

- 从干净、已评审并与 `origin/main` 对齐的 checkout 发布。
- dirty worktree、`source_modified: true` 的本机运行时只能作为候选验证，
  不能作为正式发布来源。
- Tag 和 Release 不覆盖；已发布版本需要修复时递增 patch 版本。
- 发布流程不自动修改、删除或迁移本机账本。
- PyPI 不在当前发布范围内；正式载体是 GitHub tag、GitHub Release、源码包
  和 wheel/sdist 构建产物。

## 2. 准备版本

1. 在 `pyproject.toml` 和
   `src/clash_verge_traffic_ledger/__init__.py` 中写入同一版本。
2. 在 `CHANGELOG.md` 新增对应章节；准备阶段使用 `Unreleased`。
3. 更新项目状态和验证记录，明确哪些是实机快照。
4. 运行元数据预检：

```bash
python3 scripts/check_release.py --allow-dirty
```

`--allow-dirty` 只用于准备阶段。正式 tag 检查不能带这个参数。

## 3. 验证候选版本

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src \
  python3 -m unittest discover -s tests -v
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src \
  python3 -m compileall -q src tests scripts
python3 "$CODEX_HOME/skills/.system/skill-creator/scripts/quick_validate.py" \
  .agents/skills/clash-verge-traffic-auditor
git diff --check
```

在 macOS 实机上继续验证：

```bash
python3 .agents/skills/clash-verge-traffic-auditor/scripts/bootstrap.py status --pretty
python3 .agents/skills/clash-verge-traffic-auditor/scripts/traffic_auditor.py health --pretty
curl -fsS -o /dev/null -w '%{http_code}\n' http://127.0.0.1:8765/
```

实时连接数、流量、样本时间和归因率只能记录为带时间戳的快照。

## 4. 构建并检查产物

```bash
python3 -m venv .venv-release
.venv-release/bin/python -m pip install --upgrade build twine
.venv-release/bin/python -m build
.venv-release/bin/python -m twine check \
  dist/clash_verge_traffic_ledger-0.3.0-py3-none-any.whl \
  dist/clash_verge_traffic_ledger-0.3.0.tar.gz
python3 scripts/check_release.py --allow-dirty --dist-dir dist
```

确认 sdist 包含运行时代码、Skill、Changelog 和发布文档：

```bash
tar -tf dist/clash_verge_traffic_ledger-*.tar.gz | \
  rg 'src/clash_verge_traffic_ledger|\.agents/skills/clash-verge-traffic-auditor|CHANGELOG.md|docs/releasing.md'
```

再用全新的临时 venv 安装 wheel，至少验证导入、版本和 CLI：

```bash
python3 -m venv .venv-release-smoke
.venv-release-smoke/bin/python -m pip install dist/*.whl
.venv-release-smoke/bin/python -c \
  'import clash_verge_traffic_ledger as p; print(p.__version__)'
.venv-release-smoke/bin/python -m clash_verge_traffic_ledger --help
```

`.venv-release-smoke/` 只用于本地验证，完成后可删除；不要提交生成的
`dist/` 或虚拟环境。

## 5. 合并后创建正式版本

将 `CHANGELOG.md` 的 `Unreleased` 改为发布日期并合并到 `main`。在干净的
最新 `main` 上重新运行全部检查，然后验证 tag：

```bash
git status --short --branch
git fetch origin
git rev-parse HEAD
git rev-parse origin/main
python3 scripts/check_release.py --tag v0.3.0 --dist-dir dist \
  --notes-output dist/release-notes-v0.3.0.md
git tag -a v0.3.0 -m 'Release v0.3.0'
git push origin v0.3.0
gh release create v0.3.0 \
  dist/clash_verge_traffic_ledger-0.3.0-py3-none-any.whl \
  dist/clash_verge_traffic_ledger-0.3.0.tar.gz \
  --repo timmyagentic/clash-verge-traffic-ledger \
  --title 'v0.3.0' \
  --notes-file dist/release-notes-v0.3.0.md \
  --verify-tag
```

版本示例随下一版本调整。任何 `git push`、tag 或 `gh release create` 都是
外部发布动作，必须得到明确授权。

## 6. 发布后验证

```bash
gh release view v0.3.0 --repo timmyagentic/clash-verge-traffic-ledger
release_download_dir="$(mktemp -d)"
gh release download v0.3.0 \
  --repo timmyagentic/clash-verge-traffic-ledger \
  --dir "$release_download_dir"
shasum -a 256 "$release_download_dir"/*
```

从下载的 wheel 重复安装烟测。只有 tag、Release 资产、版本元数据和下载
回读一致，才可以称为“已发布”。

如需更新本机运行时，先从干净 tag checkout 预演，再显式加载服务：

```bash
python3 .agents/skills/clash-verge-traffic-auditor/scripts/bootstrap.py \
  install --source "$PWD" --database /absolute/path/to/ledger.sqlite --dry-run --pretty
python3 .agents/skills/clash-verge-traffic-auditor/scripts/bootstrap.py \
  install --source "$PWD" --database /absolute/path/to/ledger.sqlite --load --pretty
python3 .agents/skills/clash-verge-traffic-auditor/scripts/bootstrap.py status --pretty
python3 .agents/skills/clash-verge-traffic-auditor/scripts/traffic_auditor.py health --pretty
```

部署完成证据必须包含：tag/commit、`source_modified: false`、运行时版本、
账本原路径、sampler/Web 状态和 fresh health。
