# NAS FileTools OpenClaw 插件 V1

目标 OpenClaw **2026.9.4**、Node **24.16+**，实际注册 7 个 `filetools_*` 工具；Skill 在 `skills/filetools-session/SKILL.md`。Python 核心/服务在仓库 `src/nas_filetools`，独立环境通过固定 Unix socket 服务。

本插件不安装 OCR/ASR 进 Gateway，不接受模型路径或身份，不修改永久知识库。只支持经过可信身份映射的 direct session，群聊 V1 拒绝。附件按 canonical message_received 登记，再用 before_prompt_build 运行/会话事实关联；缺少可信字段明确不可用。

```bash
npm ci --ignore-scripts
npm test
npm run plugin:build
npm run plugin:validate
```

`FILETOOLS_TEST_PYTHON` 指向开发 Python 时，tests/core-integration.test.mjs 运行真实 Python 核心流转；Gateway 上下文/传输仍由测试适配器提供，不是 QQ/Gateway E2E。`FILETOOLS_TEST_TMP` 可指定允许写入的测试临时目录。

工具参数/返回见 [INTERFACE](../../docs/INTERFACE.md)，部署/回滚见 [INSTALL](../../docs/INSTALL.md)，取舍和信任边界见 [ARCHITECTURE](../../docs/ARCHITECTURE.md)，生产执行清单见 [ACCEPTANCE](../../docs/ACCEPTANCE.md)。
