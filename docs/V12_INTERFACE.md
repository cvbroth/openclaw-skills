# V1.2 工具与产物契约

目标 OpenClaw 2026.9.4，`defineToolPlugin` 注册下列10个工具，JSON schema 与 manifest 一致。工具参数均不接受 user_id/agent_id/session/注册表或输出根；上下文不可信或缺失时 factory 不提供工具。当前渠道适配策略只开放明确绑定私聊，群聊拒绝。

| 工具 | 主要参数 | 返回 |
|---|---|---|
| filetools_register | source_path+source_root（默认workspace）**或** file_id；mode:snapshot/reference（默认snapshot）；request_id可选32位小写hex；source.description可选不可信说明 | REGISTERED，attachment_id/file_id、类型/分类/字节/SHA、mode/reused/file_reference |
| filetools_inspect | attachment_id可选 | AVAILABLE附件列表；指定文件INSPECTED，有界元数据/预览/限制，不是全文 |
| filetools_extract | attachment_id；config.mode:preview/range/full，pages/time_range/paragraphs、ocr:auto/always、language:zh/en可选 | job_id、QUEUED或可复用终态 |
| filetools_status | job_id | 状态/进度/取消标志/过期时间；终态coverage、artifacts、失败与警告 |
| filetools_cancel | job_id | 取消请求状态；须查询终态确认 |
| filetools_read | job_id；artifact_id、范围、offset、max_chars可选 | READ，text或来源evidence，truncated/next_offset；output文本允许读取 |
| filetools_find | 同read，另keyword（1–200字符） | MATCHES/NO_MATCH，邻近上下文及来源；字面未命中不代表全文没有 |
| filetools_save_minutes | job_id、text（≤12000字符）、source_segments | SAVED，新派生缓存minutes产物，与原始transcript分离；长期保留仍需files/save |
| filetools_files | action和对应ID | 文件管理结果，见下表 |
| filetools_python | attachment_id、description、code（≤64000字符）、outputs（1–8个平面名称）、checks可选 | 后台脚本job_id；成功后正式输出、SHA、检查/警告 |

登记 source_path 可为允许根内绝对路径或相对路径；根/父目录/文件的软链接、junction及 `..` 逃逸拒绝。不能把 source 标签或聊天附件文字当允许根。source_root 为管理员配置名；media 根仅私有 canonical 到达适配可使用，模型 register 不可使用。公开工具不接受 URL 下载，也不扫描整个 NAS。

| files.action | 其他参数与语义 |
|---|---|
| list | area:snapshots（所有管理文件记录，包括快照、引用、临时/保存产物）或 saved；offset，分页100。含 state、availability、来源、输入/任务关系、缓存期限；引用查询是元数据检查，使用时完整SHA校验 |
| select | file_id，将该 Agent 历史文件明确关联当前会话；新会话不自动继承旧任务 |
| artifact_path | job_id+artifact_id，返回真实 Gateway 路径/字节/SHA；本操作不续期也不表示已发送 |
| touch | job_id+artifact_id；调用方实际使用后标记，验证所有权/过期/产物；不能靠轮询保活 |
| save | job_id，artifact_id可选；保存独立版本和依赖，返回saved_id |
| saved_read | saved_id，artifact_id/offset可选；文本分段，二进制返回真实路径/格式/大小/SHA |
| offer_save | job_id，ask_once:true才询问一次；已明确请求save无需询问 |
| remove_reference | attachment_id，只移除当前会话引用 |
| delete_original | file_id，明确删除快照与上传引用；reference仅取消登记，外部原件不删除；saved保留 |
| delete_cache | job_id，只删除非活动且未租用/作为活动输入的任务缓存 |
| capacity | 配额、使用量、磁盘余量和警告 |
| resume | job_id，提取任务中断/失败终态可续作，验证原件/配置和音频检查点 |

inbox_register/area:inbox 只为 V1.1 历史兼容；shared-v1.2 返回 LEGACY_INBOX_DISABLED，NAS 直接登记最终文件名，不要求 `.ready` JSON。

区间：页/正文块从1开始，闭区间；音频秒区间按相交范围选片段。最多一次返回12000字符；标注 offset/next_offset/truncated。filters 不同类型不能混用。结构化结果不混入进度日志；日志留私有任务目录。

## 状态与错误

QUEUED、RUNNING、SUCCEEDED、PARTIAL、FAILED、CANCELLED、TIMED_OUT、INTERRUPTED 可区分；FAILED不能读伪造正文，空识别产生 NO_CONTENT。SUCCEEDED 是请求范围完成，不保证扫描完整还原。音频中断处理过的块另有 processed_time_ranges。

共享布局中，过期任务 status 保留历史执行状态，同时返回 `availability:CACHE_EXPIRED`、空 artifacts 及重处理建议；不将旧成功状态当作当前文件仍可用。实际丢失的产物标为 ARTIFACT_UNAVAILABLE 并移除可读路径。读取过期文件返回 CACHE_EXPIRED，清理后未知 job 返回 NOT_FOUND。

| 错误码 | 恢复方式 |
|---|---|
| CHOOSE_FILE_OR_PATH / INVALID_PARAMETERS | 提供唯一具体路径或file_id及有效参数 |
| SOURCE_ROOT_DENIED / SOURCE_PATH_ESCAPE / SOURCE_SYMLINK_DENIED | 选已配置根内真实文件，不扩大权限 |
| SOURCE_NOT_FOUND / SOURCE_PERMISSION_DENIED | 核对落盘和实际权限，不把不存在当空正文 |
| SOURCE_INCOMPLETE / SOURCE_CHANGED / ATTACHMENT_CHANGED | 上传关闭后原子发布最终名，稳定后同请求重试；变更版本使用新request_id |
| REFERENCE_CHANGED / REFERENCE_ROOT_UNAVAILABLE | 登记新版本/快照，或管理员配置指定NAS只读根 |
| REQUEST_CONFLICT / REGISTRY_BUSY | 同请求内容保持一致；锁忙重试原请求 |
| UNSUPPORTED_TYPE / BINARY_ARTIFACT | 分类保留；换适合工具或取二进制文件，不乱码解码 |
| CACHE_EXPIRED / FILE_UNAVAILABLE / NOT_FOUND | 选择持久快照重处理或saved版本；不猜他人ID |
| FILE_BUSY | 等访问/任务终止，不删除输入 |
| SCRIPT_ISOLATION_UNAVAILABLE / SCRIPT_TREE_RECLAIM_FAILED | 拒绝发布；管理员核查隔离与进程，不绕过限制 |
| RECEIVE_SIZE_LIMIT / PROCESS_SIZE_LIMIT / DISK_QUOTA / DISK_RESERVE | 分范围/减小输入/调整批准配额与磁盘空间 |
| MANAGEMENT_NOT_CONFIGURED / MANAGEMENT_UNAVAILABLE / SERVICE_UNAVAILABLE | 运行诊断、检查固定Python入口/映射/socket；不在Gateway临时装包 |

错误返回 `{status:"ERROR",code,recovery?}`；核心直接调用抛 Fault(code,message)，CLI/适配转JSON。错误/状态信息不能替代证据。管理CLI不输出源路径/凭据到共享错误日志。

## 产物

`cache/<job_id>/sources.json` 记录 schema_version（兼容1.1字段并增加V1.2引用）、original附件ID/文件名/SHA/字节/message_id，引擎与配置、coverage、segments、failures/warnings和artifacts。私有输入、脚本执行与检查点在 `.private/`；业务产物在 `published/`。状态输出上限64个产物，完整元数据另用sources读，metadata_truncated明确说明。

正式artifact字段：artifact_id、file_id（sources为管理元数据没有业务file_id）、kind、file、format/actual_type、bytes、sha256、workspace_relative_path、gateway_path。saved产物有新的独立file_id、source_file_id与saved_id；历史sources保留生成来源，不依赖缓存存活。Markdown图片采用相对链接。

```json
{
  "status": "FILE_REFERENCE",
  "artifact_id": "0123456789abcdef0123456789abcdef",
  "workspace_relative_path": "filetools/cache/<job>/published/execution/result.xlsx",
  "gateway_path": "/home/node/.openclaw/workspace-chen/filetools/cache/<job>/published/execution/result.xlsx",
  "bytes": 4820,
  "sha256": "<actual SHA-256>"
}
```

上例是字段示意，非生产验收。路径可由普通read/Python或当前渠道现有message入口使用；不能把 `/workspaces/...` worker路径交给用户，也不能把FILE_REFERENCE当发送成功。

## CLI与调用约定

管理员入口 `python3 scripts/filetools_admin.py install|diagnose --config ...`；运行服务 `nas-filetools serve --root <control> --config <derived-worker.json>`。管理适配 `python3 -I scripts/filetools_manage.py --config <fixed-gateway.json>`，stdin唯一JSON `{identity,operation,params}`，stdout唯一JSON结果。identity只从可信调用端提供，不能暴露给模型；register_media、lease_path/finish_access为内部适配操作，不是可伪造的公开工具。核心 register_source/store/dispatch 可直接复用。

典型顺序：取得具体文件→登记或查历史→自主选普通read/专用extract/Python→后台状态→按需读证据/取得二进制→当前会话渠道发送并检查回执→明确保存。登记不是所有普通文件读取的系统许可门槛。
