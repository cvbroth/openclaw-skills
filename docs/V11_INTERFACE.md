# V1.1 工具和产物契约

身份来自可信运行时。参数拒绝额外字段，模型不能指定path/user/agent/session；只使用已登记ID。结果JSON，日志留私有任务目录。content_trust:untrusted。

| 工具 | 参数 | 返回 |
|---|---|---|
| filetools_inspect | attachment_id可选 | AVAILABLE列表/INSPECTED元数据、预览范围、parse_error；未知格式仍有归档ID |
| filetools_extract | attachment_id、config(mode必需，范围/ocr/language可选) | job_id、状态、reused |
| filetools_status | job_id | progress、覆盖、失败、警告、artifacts、已完成音频块；不续TTL |
| filetools_cancel | job_id | 状态/cancel_requested；须等终态确认 |
| filetools_read | job_id、artifact_id、一个来源范围、offset、max_chars（后4项可选） | evidence(text/source/segment/engine/incomplete)、next_offset/truncated；来源/纪要/脚本/日志文本分页 |
| filetools_find | read参数+keyword | MATCHES/NO_MATCH、附近上下文；只查已提取范围 |
| filetools_save_minutes | job_id、text≤12000字符、source_segments≤100 | 独立模型整理纪要artifact_id/reused |
| filetools_files | action和对应ID/area/offset | 文件管理，见下文 |
| filetools_python | attachment_id、description≤1000、code≤64000字符、outputs(1–8平面文件名)、checks可选 | 后台job_id；终态输出artifact_id/SHA/断言/警告 |

config.mode:preview/range/full；PDF/图片pages含端点从1开始，录音time_range秒，DOCX/文本paragraphs正文块（表格算块）。range只准对应范围，full不夹带range。language:zh/en，ocr:auto/always。

files动作：list(area:snapshots/saved/inbox，默认snapshots，offset分页100条)、select(file_id)、capacity、save(job_id,artifact_id可选)、saved_read(saved_id,artifact_id可选,offset)、delete_original(file_id)、remove_reference(attachment_id)、delete_cache(job_id)、inbox_register(inbox_id)、resume(job_id)、offer_save(job_id)。offer_save第一次ask_once:true；明确保存可直接save。save不指定artifact保存全束，指定则保留选定成果及来源资源，可能包含关联产物。二进制saved_read返回元数据，由管理员配置的合法交付方式取得，本版不声称已通过QQ发回编辑文件。

XLSX checks例：`[{"file":"result.xlsx","sheet":"Budget","cell":"B2","equals":24,"min_rows":3,"min_columns":2}]`。读取input.xlsx另存result.xlsx；多表分别断言。无公式缓存不是零，宏/版式/重算无可靠保留保证。

SUCCEEDED、PARTIAL、FAILED、CANCELLED、TIMED_OUT、INTERRUPTED可区分。错误返回`{status:"ERROR",code:...}`，常见：FORBIDDEN/NOT_FOUND、UNSUPPORTED_TYPE、CACHE_EXPIRED、RECEIVE_SIZE_LIMIT/PROCESS_SIZE_LIMIT、PAGE_LIMIT/PIXEL_LIMIT/EXPANDED_SIZE_LIMIT/OUTPUT_LIMIT、SESSION_REFERENCE_LIMIT/JOB_QUOTA、DISK_QUOTA/DISK_RESERVE、FILE_BUSY、INBOX_INCOMPLETE、CHECKPOINT_MISMATCH、SCRIPT_ISOLATION_UNAVAILABLE/SCRIPT_FAILED/OUTPUT_NOT_VERIFIED/OUTPUT_ASSERTION_FAILED/SCRIPT_TIMEOUT。不能解释为原文空或成功。

缓存每任务content.md、sources.json；音频另transcript.md/checkpoint.json；纪要minutes-<id>.md；脚本operation.py/stdout.log/stderr.log/input副本/编辑输出。sources schema_version:1.1含原文件名/SHA/大小/附件ID/消息ID/job_id、ISO带时区时间、配置/引擎/模型、覆盖范围、来源段、失败警告及产物ID。saved.json保留版本/来源状态；MD图片改为相对链接，不依赖cache。持久时间ISO UTC，用户展示Asia/Shanghai（UTC+8），SQLite内部调度用Unix秒。

正式提取：PDF、DOCX、MD/TXT、PNG/JPEG/WebP/BMP/TIFF、MP3/M4A/WAV/FLAC/OGG。分类还包括DOC/XLS/XLSX/CSV/TSV/ODS、JSONL/Parquet/Arrow/Feather、JSON/YAML/XML与other；分类不是解析支持。ZIP/OLE子类型、UTF-8文本有界识别，记录置信范围和扩展名差异；未知other。没有照片画面理解/手写/公式/复杂表格可靠承诺。

中央默认Limits：接收4GiB，处理4GiB（仍受格式展开/时长/输出限制），控制JSON512KiB，响应2MiB，read12000字符；TTL72h/每小时清理；音频6h/600秒块+2秒重叠；全服务重任务1、2线程、工作进程4096MiB；单任务3600秒/音频因子8/总72h/无进展1800秒；上传总3600秒且单次读取20秒；脚本60秒/输出256MiB；快照100GiB、保存50GiB、缓存20GiB（各按Agent）、磁盘预留1GiB、80%告警。大文件复制/哈希多遍磁盘I/O，不等于即刻完成。

接收`/v1/attachment`，控制`/v1/tool`；capabilities传回中央限制供JS/CLI使用，启动探测响应安全上限2MiB。health/diagnostics为管理员入口，不注册给模型；diagnostics空闲时在真实worker环境检查合成OCR、离线ASR加载和脚本权限，忙时DEFERRED。它不证明中文准确率或QQ端到端。

SDK canonical media只提供path，不含独立originalFilename字段；filename记录可信暂存文件的basename，不从正文猜原名。渠道若改过文件名，原始客户端名称需在真实渠道验收核对。QQ原生语音可能只提供远端URL或渠道已有转写，当前不从URL自行下载；提供原始音频文件附件或NAS inbox可获得可靠快照。

补充独立处理上限：10000页、单页渲染2400万像素、UTF-8文本16MiB、DOCX/脚本ZIP展开128MiB、产物200万字符/20000段、来源清单64MiB、资源32MiB、引擎日志2MiB。排队任务实际启动时再次检查缓存配额与磁盘预留；不足明确失败。引擎日志由调度轮询限额，不能当文件系统硬配额。脚本文件总量采用轮询加结束校验，Linux另有单文件RLIMIT_FSIZE。

来源清单的expires_at是生成时记录；有效使用可延长缓存闲置期限，查询status返回的数据库expires_at才是当前清理依据。
