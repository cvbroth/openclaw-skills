> 这是87f93ac交付的V1历史记录，限额/接口不代表当前V1.1。当前说明见 [V11_INTERFACE](V11_INTERFACE.md)。本轮远程CI未执行，不能将历史或已编写工作流视为V1.1 CI通过。

# 工具、服务与产物契约 v1.0

## 模型侧工具

所有参数对象均拒绝未知字段。ID 均是 32 位小写十六进制，必须来自本用户/Agent/会话的登记结果。参数不能包括路径、身份、URL、scope、目标知识库或输出目录。所有返回 `content:[{type:"text",text:JSON.stringify(result)}]` 和相同 `details`。服务/机器日志不进入 JSON。

| 工具 | 参数 | 主要返回 |
|---|---|---|
| filetools_inspect | `{attachment_id?}` | 无 ID 返回 AVAILABLE 和附件列表；有 ID 返回 INSPECTED、格式、SHA256、字节数、units/duration、preview、preview_coverage、warnings、requires_explicit_scope |
| filetools_extract | `{attachment_id,config}` | job_id、attachment_id、status、progress、expires_at、reused |
| filetools_status | `{job_id}` | status、progress、cancel_requested；终态包含 coverage、failures、warnings、artifacts 及计数 |
| filetools_cancel | `{job_id}` | 当前状态和 cancel_requested。RUNNING 是待取消，查询直到 CANCELLED；终态操作幂等 |
| filetools_read | `{job_id,artifact_id?,pages?,time_range?,paragraphs?,offset?,max_chars?}` | READ、evidence（或 sources/minutes 的 text）、next_offset、truncated、coverage、失败、质量警告 |
| filetools_find | read 的参数加 `{keyword}` | MATCHES/NO_MATCH、附近 evidence、定位来源；字面大小写无关匹配，每段至多首处，非向量搜索 |
| filetools_save_minutes | `{job_id,text,source_segments}` | SAVED、artifact_id、reused；不覆写原始转写 |

extract.config：`mode` 必填 `preview|range|full`，可选 `ocr:auto|always`（默认 auto），`language:zh|en`（不设置则音频自动检测）。range 必须且只能有与格式一致的一个范围：PDF/图片 `pages:[1,3]`，DOCX/文本 `paragraphs:[2,5]`（含端点），音频 `time_range:[60,120]`（秒，片段交叠匹配）。preview 默认前 3 页/正文块或 60 秒；full 是显式请求全文。图片页码指 TIFF frame；DOCX paragraphs 实际是正文 p/tbl 块索引。range 不能倒置/越界。

read/find 的 offset 是**所选证据文本拼接后的 Unicode 字符偏移**，不是文件字节、PDF 页或全局段号；find 为每个命中片段附近上下文拼接偏移。继续读取必须保持过滤范围/keyword 相同。max_chars 默认为 12000、范围 1–12000；返回 evidence 的文本总长不超过该限额。元数据另有截断摘要/计数。time_range 为秒区间，返回交叠原始片段并保持原始起止时间，不人为截断 ASR 句子。PDF pages、body paragraphs 从 1 开始，页码/段号永不随范围提取重编号。

默认读取 content；可提供来源、转写或纪要 artifact_id。sources.json 及 minutes 以有界 text 分段返回，sources 的 offset 上限仍是 200 万字符，完整大 manifest 供管理员离线检查。图片 artifact 记录保存在任务目录，V1 工具不把原始图片二进制发给模型；不可读类型返回 UNREADABLE_ARTIFACT。

`SUCCEEDED`：请求范围流程成功；`PARTIAL`：有证据也有失败；`FAILED`：无可靠识别内容/引擎失败。`QUEUED/RUNNING/CANCELLED/TIMED_OUT/INTERRUPTED` 区分任务生命周期。success 不等于文字准确、扫描版完整还原或知识库入库。

错误统一 `{status:"ERROR",code:<稳定码>}`，包括 NOT_FOUND（未知/过期/未授权 ID 同形），INVALID_PARAMETERS/INVALID_RANGE/INVALID_ID，UNSUPPORTED_TYPE，SIZE_LIMIT/PAGE_LIMIT/DURATION_LIMIT/PIXEL_LIMIT/EXPANDED_SIZE_LIMIT/OUTPUT_LIMIT，ATTACHMENT_CHANGED，NOT_READY，OCR_UNAVAILABLE/ASR_UNAVAILABLE/MODEL_UNAVAILABLE，NO_CONTENT，FFPROBE_UNAVAILABLE，SERVICE_UNAVAILABLE、ATTACHMENT_SESSION_UNRESOLVED 等。页/块失败出现在 failures 内而不是冒充空白成功；部分失败返回可用证据和总失败数。临时 Gateway 登记拒绝超限文件时 inspection 会列 registration_errors，不能把没有可用登记解释为该文件已成功处理。

status/read 中 metadata_truncated 表示只返回前 20 个处理来源、失败、警告及前 64 个附件；failure_count/warning_count/artifact_count 保留真实总数。sources.json 保留完整明细。find 的 NO_MATCH 仅针对已提取、所选范围的字面匹配，不证明原始全文没有相关语义。

示例：

```json
{"attachment_id":"0123456789abcdef0123456789abcdef","config":{"mode":"range","pages":[11,20],"ocr":"auto"}}
```

```json
{"job_id":"abcdef0123456789abcdef0123456789","pages":[12,12],"max_chars":6000}
```

## 可信服务协议

固定 `/run/nas-filetools/service.sock`、HTTP POST，不开放 TCP/远程 URL。

- `/v1/attachment`：raw 文件字节（禁止 chunked），Content-Length ≤64 MiB，受信任头 `X-Filetools-Identity`、`X-Attachment-Id`、JSON 转义 `X-Filename`、`X-Content-SHA256` 和可信 canonical `X-Source-Message-Id`（CLI 管理登记可省略）。摘要不符不登记。使用 15 秒独立检查进程，probe 不运行 OCR/ASR，只有有界原生文字预览/元数据。限制/解析失败返回稳定错误。
- `/v1/tool`：`{identity:{user_id,agent_id,session_hash},operation,params}`，请求 JSON ≤32 KiB。operation 为 inspect/extract/status/cancel/read/find/save_minutes。身份由 Gateway/CLI 注入；服务复核固定 Agent-user 映射及范围。Socket 访问权限是信任边界，同 UID 任意代码不属于强隔离保障。
- 成功与业务错误均 HTTP 200 的结构化结果，未知路由/格式仍明确 ERROR。插件超时/中断及非 JSON 响应不得冒充无结果。插件限制响应 2 MiB、请求 60 秒；重任务返回队列状态，不能占用工具请求等待整小时。

## 管理员 CLI

`nas-filetools serve --root STATE --config CONFIG`（global `--socket` 必须放在子命令前）。`nas-filetools cleanup --root STATE` 只允许服务停止、锁空闲。诊断 `--identity-file` 是 operator-only、Linux 权限 0600：

```json
{"user_id":"chen","agent_id":"chen","session_hash":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"}
```

```bash
nas-filetools --identity-file identity.json register sample.pdf
nas-filetools --identity-file identity.json call inspect --params '{}'
nas-filetools --identity-file identity.json call extract --params '{"attachment_id":"...","config":{"mode":"preview"}}'
```

CLI 与服务同协议，stdout 只有 JSON，错误退出码 1。serve 不输出文档内容。register 接受本地路径是**可信管理员入口**，不能放进 Agent 的 shell 技能来绕过授权。

## 产物格式

```text
state/
  jobs.sqlite3
  originals/<opaque-scope>/<attachment_id>.<ext>
  tasks/<job_id>/
    content.md
    sources.json
    transcript.md                   # 仅音频
    minutes-<artifact_id>.md         # 用户要纪要后派生，最多 32 份
    assets/<content-hash>.<ext>      # PDF OCR 页预览 / DOCX 必要图像
    engine.log                      # 私有诊断日志，不返回模型
    result.json                     # 内部原子结果标记
```

排队时 content.md 为空、sources.json 明确没有已发布证据；查询 SQLite 状态是运行/取消/重启的实时依据。正常处理完成后原子发布完整来源记录。进程失败时保留已有可信附件/配置记录及错误；中断状态不允许读取暂存正文。

sources.json schema_version="1.0"：job_id、attachment_id、original（basename/sha256/bytes/canonical message_id）、created_at/expires_at、status、config、limits、engines 实际版本、coverage（总页数/时长、mode、requested、processed、full_document）、segments（segment/text/source/engine/incomplete、OCR box/置信度）、failures、warnings、artifacts。content.md 每段以页码/秒范围/正文块标题和稳定 segment 注释定位；图片使用 `artifact:<id>` 引用，管理员可根据 manifest 的固定相对路径查看，图片不是网页 URL。

transcript.md 保持识别原文，与 content 音频证据同源；minutes 独立，记录 source_segments、author=agent-derived-unverified，不声称是源录音。engine/config/覆盖记录可供复核，不记录原始服务器任意路径或模型凭据。
