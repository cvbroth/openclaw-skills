# V1.2 开发验证与复现

本轮所有执行只在 Windows 开发机及其 Docker Desktop Linux。没有生产连接、QQ发送或 GitHub CI 执行。证据在 `docs/evidence/v12-*`；报告分别说明真实引擎、模拟和跳过。

## 独立开发环境

Python 3.12，Node 24.16.0。项目自己的虚拟环境，不使用检索引擎环境，也不安装到 Gateway。

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -c requirements.lock.txt -e '.[engines,test]'
.venv/bin/python -m ruff check src tests scripts
.venv/bin/python -m pytest -q
cd integrations/openclaw-filetools
npm ci --ignore-scripts
FILETOOLS_TEST_PYTHON=../../.venv/bin/python npm test
npm run plugin:build
npm run plugin:validate
```

Windows 将 Python 路径换为 `.venv\Scripts\python.exe`，用 PowerShell 设置 `FILETOOLS_TEST_PYTHON` 为绝对路径。默认 pytest 跳过真实引擎；Windows 另外跳过 Linux socket、权限、Landlock 和真实 symlink 创建。跳过不等于通过。

## 实际 OCR/ASR

自制文档由 tests/conftest.py 生成，OCR需要Arial或DejaVu字体；Linux另需FFmpeg/libseccomp2。音频下载脚本固定MIT许可Whisper测试录音与许可文件。

```bash
.venv/bin/python scripts/fetch_test_audio.py --output /tmp/filetools-samples
.venv/bin/python scripts/prepare_models.py --model small --cache /tmp/filetools-models --revision 536b0662742c02347bc0e980a01041f333bce120
FILETOOLS_REAL_ENGINES=1 FILETOOLS_AUDIO_SAMPLE=/tmp/filetools-samples/jfk.flac FILETOOLS_WHISPER_MODEL=/tmp/filetools-models/models--Systran--faster-whisper-small/snapshots/536b0662742c02347bc0e980a01041f333bce120 FILETOOLS_AUDIO_EXPECT=country .venv/bin/python -m pytest -m engines -q
.venv/bin/python scripts/benchmark_samples.py --shared-workspaces --output /tmp/filetools-benchmark --audio /tmp/filetools-samples/jfk.flac --model /tmp/filetools-models/models--Systran--faster-whisper-small/snapshots/536b0662742c02347bc0e980a01041f333bce120
```

下载只在准备阶段发生；实际处理 offline=true。10个引擎用例包括扫描/混合/图片OCR、真实短录音及时间范围、共享布局的文字PDF/DOCX/图片/音频提取、来源读取、保存后清缓存。DOCX图像-only块预期PARTIAL，图片仍保留；不能把它写成完整还原。

## 本机 Docker 验证

以下 `desktop-linux` 只用于本轮开发机，不是NAS或远程Docker上下文。确认 Docker context inspect 后执行。镜像不作为交付物，部署需从最终提交构建。

```powershell
docker --context desktop-linux build -t nas-filetools:1.2.0 -f deploy/Dockerfile .
docker --context desktop-linux build -t nas-filetools-test:1.2.0 -f deploy/Dockerfile.test .
docker --context desktop-linux run --rm --network none --cap-drop ALL --security-opt no-new-privileges:true --cpus 2 --memory 4g nas-filetools-test:1.2.0
.venv\Scripts\python.exe scripts/docker_workspace_smoke.py --output ..\v12-docker-smoke
```

完整真实引擎回归需另外把录音、固定模型快照只读挂进容器，设置以上四个 FILETOOLS 环境变量。开发时可以把最终源码只读挂到 `/opt/nas-filetools-check`，使用镜像固定依赖、容器内部 `/tmp` 做测试目录；不能在Windows bind上用chmod测试Linux权限。JUnit可独立挂可写证据目录导出。

docker_workspace_smoke 创建唯一命名的临时测试容器/卷，仅连接 desktop-linux，结束后清理自己的容器/卷；不删除原件或操作者卷。Gateway角色使用 `python -I -S` 固定管理CLI，验证无需引擎依赖。worker只映射各Agent卷的filetools子目录。实际完成Unix socket、隔离Python、MD/XLSX校验、Gateway普通读取、保存/清理与跨Agent拒绝。它不是OpenClaw daemon或QQ端到端。

目标SDK会话存储钩子在真实Node Linux容器验证：

```powershell
docker --context desktop-linux run --rm --network none --mount "type=bind,src=<本机插件绝对目录>,dst=/plugin,readonly" -w /plugin -e OPENCLAW_STATE_DIR=/tmp/sdk-state node:24.16.0-bookworm-slim node --test tests/runtime.test.mjs
```

须先准备对应SDK依赖；本轮已有2026.9.4锁定依赖可供该测试读取。工具工厂/生命周期是真实SDK，sender/会话与渠道客户端由测试注入；不能视为真实用户在Gateway发消息成功。

## 模拟及生产边界

四小时调度/块覆盖是生成元数据；24秒分块恢复用真实FFmpeg和注入ASR。4GiB是计数边界，真实写入/登记/完整哈希样本201MiB。失败注入、Compose发现命令替身、白名单有效性谓词与QQ回执替身均为模拟；勿改名成生产通过。

真实生产安装/回滚、完整QQ下载→Agent调用→实际发送和客户端下载、中文长录音/大本OCR及NAS资源峰值仍按 [生产清单](V12_ACCEPTANCE.md) 待验收。现有检索插件的本地测试属于接口回归，不能证明生产知识库服务状态。
