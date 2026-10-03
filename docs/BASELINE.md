# 基线与生产信息

> 下文记录初始 V1 开发。V1.1 于 2026-10-03/04 在已交付 V1 `87f93acad75c7b92a091fe673e67326d6d640143` 上建立 `feat/filetools-v1.1`，不是从 main 假设已有 V1。公开 GitHub API 核对 V1 分支仍是该提交，检索仓库仍是下列参考提交。V1.1 用户确认 QQBot 为 v2.0.3；本轮未连接生产。当前报告见 [V11_REPORT](V11_REPORT.md)。

2026-10-03（Asia/Shanghai）读取远端默认分支并建立独立开发副本。

| 仓库 | 当前基线提交 | 本轮范围 |
|---|---|---|
| cvbroth/openclaw-skills | 83014f7843f0fe0bcfbf872b3a3cf22c7cbd2d6f | 新增 V1 核心、插件、测试、文档；原独立引擎脚本保留 |
| cvbroth/vector-search-engine | 623aa73abcd0dc7f4854a58a8a42e8b6c4725072 | 只读接口/权限核对与原插件回归测试，未修改跟踪文件 |

两个仓库均未发现 AGENTS.md / CONTRIBUTING 开发说明；已读取根 README、filetools 的 Skill/setup、检索插件 README、manifest、package.json、工具、附件登记、客户端与测试。

现有独立脚本使用 PyMuPDF、RapidOCR、python-docx、faster-whisper；新核心复用同类引擎调用，不调用会打印进度/接受任意输出路径的旧脚本。旧 DOCX fallback 会把表格放到段落末尾，新核心按 XML 正文顺序处理。检索库的 Embedding、数据库、RRF、永久导入授权、NAS uploader 映射及 session_document_query 保持不变。

检索插件 0.2.6 固定开发依赖 OpenClaw 2026.9.4；读取同版本 npm 发布包的公开 SDK 类型与实际调用源码，核对 defineToolPlugin、message_received、session_start/session_end、公开只读 session-store-runtime、toolContext.requesterSenderId、sessionId。npm 包已在独立开发目录安装，不安装到生产 Gateway。

用户提供的生产事实（本轮未连接核实）：OpenClaw **2026.9.4 / 3a9d69d**；Docker 容器 `openclaw-openclaw-gateway-1`、镜像 `stockanalyse-openclaw-managed:latest`；Ubuntu **26.04 LTS / x86_64**；Intel Xeon E3-1270 v5（4 核 8 线程，AVX2）；总内存约 30 GiB、查询时可用约 23 GiB、Swap 8 GiB。与 Immich、MySQL、既有知识检索共享资源。主要 QQ 附件，实际私聊/群聊权限、渠道版本、可信字段和匿名真文件仍待验收。

本轮未连接服务器，未部署、修改 Gateway 或触碰 NAS 数据、永久检索/导入链路。生产版本与依赖包版本相符仍不等于 QQ 的具体可信字段已通过端到端验证。
