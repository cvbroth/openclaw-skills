# V1.2.1 兼容契约与取舍

十个工具名称、身份映射、旧配置、任务和知识库接口保持。新增参数全部可选，详见 [完整 V1.2 契约](V12_INTERFACE.md)。配置/身份仍来自可信运行时，文件正文、名称和source描述不可信。

| 变化 | 行为 |
|---|---|
| filetools_register.select | 默认true保持原行为；false登记目录快照/引用，不激活当前会话附件。返回REGISTERED、file_id、selected:false、来源/分类/文件引用；没有attachment_id。选择时再files/select(file_id)，仍受32个活跃附件限制 |
| filetools_inspect.registration_only | true仅查询当前可信session epoch回执，不重试/读取文件正文；false或省略触发有界登记/重试并返回原inspect结果 + registration页 |
| filetools_inspect.receipt_offset | 默认0，页的 next_offset 续取；不能与其他身份/epoch混用 |
| files/list | 仍最多100记录/页，增加响应字节预算，须以实际next_offset续取；来源uploads摘要最多20条，uploads_truncated明确提示 |

回执页：`{status:"REGISTRATION_RECEIPTS",receipts:[...],total,offset,next_offset,truncated,continuation}`，最多16条、6500字符的回执负载，整体完整JSON。每项有request_id、短filename及必要attachment_id/file_id/status/mode/reused/bytes；失败有code/recovery，不包含任意异常路径、凭据、文件正文或完整后台日志。所有字符串作为数据，不作为权限或指令。

会话额度溢出明确报告 `unregistered_count`，这些文件未获得可处理的附件ID；不能把错误回执request_id当attachment_id。已接受的重复 canonical 事件先去重，不因会话刚好满32槽位而误报新的额度错误。

提示构建最多等5秒（测试用更短可注入时限），之后后台管理进程继续原请求。pending可重复看到，最终结果去重一次注入提示；失败后重试成功是新终态可报告。查询模式能再读已报告回执，分页不因提示消费而丢失编号。会话reset不能收养旧附件。无新Agent运行时不承诺主动回复，下次用户查询/Agent运行查看完成状态。登记暂时性故障用原request_id重试，输入变更不能伪装同版本。

目录整理由 Agent 用现有目录查看能力判断业务资料，再逐文件 register(select:false)。没有新增自动扫描器、账户平台、通用原件迁移或自动永久导入。catalog-only 使用已有非活跃来源事件记录，不新增表；同 Agent 内容快照SHA去重保留上传事件来源。分类来自既有类型识别，不宣称按业务语义自动重命名原目录。

宿主映射查找与可写要求分离，最深 bind 优先；workspace必须RW，来源可RO，拒绝非绝对路径/..。Worker NAS reference一直默认RO。只读和版本检查不等于判断上传已完成；Uploading/Incoming为用户显式发布约定。

Samba是可选管理员功能，结果仅暴露saved，state_dir权限备份是部署审计文件，不是第二套文件数据库。plan、rollback计划及安装记录中每个share返回 `permission_mode`：同UID为 `owner_samba_readonly`，不同UID为 `reader_acl`。同UID不改新旧保存区ACL/所有者权限，依靠Samba只读配置；不同UID保留现有读者ACL修复及Unix不可写检查，已有自定义named ACL拒绝自动覆盖。saved发布器忽略所有者自己的named-reader条目，仅有非所有者只读named-user默认ACL时修复新版本access/defaultACL。没有读者ACL时发布行为不变。不增加Gateway广泛组，不扩展身份系统。

重复apply、diagnose和rollback比较当前UID/模式与安装记录，身份/模式改变拒绝自动处理。旧记录没有模式时明确按reader_acl解释。diagnose同UID返回 `unix_reader_access:READ_TRAVERSE_OWNER_PERMISSIONS_PRESERVED` 及“Samba 访问只读，服务器本地所有者仍可写。”；不同UID返回 `READ_TRAVERSE_NO_WRITE`。两者仍返回 `production_acceptance:PENDING`，实际SMB读写及账号隔离须单独验证。

保存目录仍为分类/版本ID/产物、saved.json、sources.json和必要图片。原转写和派生纪要保留独立来源。不扩展引擎、向量索引、Family授权、数据库/Embedding/搜索算法。真实QQ、生产长附件与开机挂载验收见 [测试及生产清单](V121_TESTING.md)。
