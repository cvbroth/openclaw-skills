# NAS FileTools OpenClaw 插件 V1.2

目标 OpenClaw **2026.9.4**、Node **24.16+**，公开SDK defineToolPlugin实际注册10个工具；通用Skill在 `skills/file-workspace/SKILL.md`。Python共享核心在仓库src/nas_filetools；Gateway固定标准库管理入口负责登记/保存，单个独立worker经Unix socket后台处理。实际Agent filetools子目录共享，正常控制请求只传ID，不上传原件字节。

管理员配置bindings、workspaces、management（python/entry/config），模型不能指定身份或注册表。已落盘文件只能登记明确允许根内路径；media根只供可信到达适配。canonical media绝对路径或相对path+可信workspaceDir支持，正文附件文字不授权。批准direct会话，群聊拒绝；到达先登记/回执一次，无任务不处理。

before_tool_call/after_tool_call为普通read/read_file建立短租约，成功续期；外部OS/任意Python读取不可观测，需要协作touch。产物Gateway路径可由现有message入口使用，经QQBot sendMedia→sendFile；真实QQ回执/客户端下载待验收。不向Gateway装OCR/ASR，不自动入永久知识库。

```bash
npm ci --ignore-scripts
npm test
npm run plugin:build
npm run plugin:validate
```

`FILETOOLS_TEST_PYTHON` 指向独立Python时，两个集成测试实际运行核心/后台worker；workspace-integration验证共享路径、管理CLI、MD/XLSX与保存/清理。Gateway sender/session与控制传输仍由测试注入，发送回执明确模拟，不是QQ/Gateway模型端到端。`FILETOOLS_TEST_TMP`可指定测试临时目录。

工具/产物见 [INTERFACE](../../docs/V12_INTERFACE.md)，安装/迁移/回滚见 [INSTALL](../../docs/V12_INSTALL.md)，边界见 [ARCHITECTURE](../../docs/V12_ARCHITECTURE.md)，生产清单见 [ACCEPTANCE](../../docs/V12_ACCEPTANCE.md)。缺management的V1.1兼容代码仅供历史迁移；V1.2部署必须选shared-v1.2。
