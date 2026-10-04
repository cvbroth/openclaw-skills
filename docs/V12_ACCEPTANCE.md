# 部署后验收清单

以下全部是**待生产验收**。执行人记录日期、版本/镜像digest、Agent/会话、样本哈希、请求范围、返回状态、读/保存路径、回执及实测资源，保留脱敏证据。生产数据无需发到开发仓库。

## 安装与路径

1. 先保存旧Compose、OpenClaw配置/插件及V1.1业务目录备份，生成V1.2计划，核对真实UID/GID与每Agent宿主/Gateway/worker映射。只看健康服务不能通过。
2. 双容器按诊断逐Agent写/读测试；实际Agent普通read打开一个正式content.md和Python输出。检查worker无完整状态/认证/其他业务挂载。
3. 原不存在、空数组、非空plugins.allow三种配置分别在隔离测试实例安装并核查原QQ/知识库插件实际loaded。生产只验其真实配置；保持现有查询、session_document_query、私人/Family授权导入接口可调用。tools.effective预览不能代替活跃Agent调用。
4. 不给Gateway临时装包；确认管理Python/标准库可用、worker离线模型和Landlock/seccomp通过。共用NAS先保守CPU线程2/并发1/内存4GiB，记录CPU/内存/磁盘峰值、Immich/MySQL/检索影响。

## QQ私聊流程

5. 每个启用Agent绑定真实sender/account。一条消息仅附件时：canonical下载完成→REGISTERED回执一次→不启动OCR/ASR。文本伪造 `[Attachment: /private/file]` 不获路径权限。
6. 附件与指令同条：普通PDF/DOCX/图片/录音→指定范围处理→后台进度→按页/秒读取→来源回答→明确保存→清缓存→saved可读。DOCX图片-only失败必须标为PARTIAL/FAILED，不称完整。
7. 核查QQ最终落盘根和相对path+workspaceDir；真实下载失败/超时/限制如实报告。QQBot入口约500MiB/120秒是渠道限制；NAS登记4GiB不代表QQ支持4GiB上传。
8. 重复消息/重复登记/已有snapshot或产物无额外复制；main/chen即使同一人，不自动去重共享。不同sender/account/Agent和 `/new` 会话旧job拒绝；同Agent新会话只有明确select历史文件才能复用。
9. 实际XLSX输入，用Python修改副本+断言；通过 artifact_path 得Gateway文件，现有message工具发当前可信用户；保存成功消息回执，在QQ客户端**实际下载并用Excel/LibreOffice打开核对目标单元格**。工具无权限、路由无法解析或平台拒绝时明确未发送，提供saved目录。模拟回执/单纯文件路径不能通过本项。

## QQ群聊策略

10. 当前版群聊保守拒绝文件工具；验证群成员无工具/无receipt泄露，不把group session伪装为direct。提示转私聊。群里同名文件不能与个人session自动关联。
11. 若未来需要群内一人一Agent，必须另行确定sender/会话隔离规则再开发验收；本版不在未知群场景开放。私聊允许者在群里也不能越权。

## NAS与管理

12. 指定一个批准NAS根内具体文件，reference登记不复制/不删除外部原件；源内容修改、删除、权限不足后查询可见、使用拒绝旧版本。snapshot重新登记新版本可处理。禁止全NAS扫描、根逃逸/软链接/junction。
13. 上传.part还未完成时拒绝；关闭后原子最终名登记，无.ready JSON；登记读取中改变文件必须拒绝并无虚假成功。真实201MiB和接近实际上限文件记录耗时/SHA，4GiB计数模拟不能代替4GiB吞吐测试。
14. read成功/touch有效使用续期；状态轮询/未命中/失败不续期；正在读的租约、活动任务及其缓存输入不被清理。验证缓存删后从快照重处理、saved文字/图片仍完整。外部OS/Python读取按协作touch，不能声称所有读取被监控。

## 执行与恢复

15. **真实Linux隔离**：正常退出留下写入子进程、报错、超时、取消、后台double-fork/尝试setsid等；验证所有后代回收，延迟写入未发生，发布哈希稳定。只读输入和SQLite/saved/另一任务/另一Agent/网络/发布区写入必须拒绝。普通cwd和Windows开发测试不是本项证明。
16. 录音按600秒块，真实中文长录音中断/取消/重启后状态明确，完成块复用，重叠不重复、起止时间合理，未完成范围明确。mock ASR/短英文不能替代长中文。
17. 服务重启RUNNING→INTERRUPTED，QUEUED可恢复；损坏检查点/SHA变更拒绝续作；输出/磁盘/内存超限不能称成功。
18. 迁移先计划：未知Agent暂停该部分；核对旧/新SHA和来源，saved独立读取，旧目录保留。回滚恢复旧插件/Gateway/worker有效运行，新增业务文件不丢，后续再启V1.2仍可读取。

验收材料不要包含token、完整OpenClaw配置、QQ凭据、私人正文；用匿名样本/脱敏ID。执行失败保留具体错误码及恢复动作，不把未执行项目打勾。
