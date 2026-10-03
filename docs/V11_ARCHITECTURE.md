# FileTools V1.1 架构与信任边界

V1 基线 87f93acad75c7b92a091fe673e67326d6d640143，独立分支 feat/filetools-v1.1。参考检索基线 623aa73abcd0dc7f4854a58a8a42e8b6c4725072。没有修改检索数据库、Embedding、索引、查询/会话查询或私人/Family 导入契约。

一人一 Agent，沿用 channel/account/sender 绑定；兼容内部 user_id，配置不要求第二套账户。权限范围是 SHA256(sessionKey + NUL + sessionId)，不能由模型指定。main/chen 兼容 chen，ziling 兼容 azl；物理文件仍按Agent分开。陌生/重复绑定、缺上下文、群聊失败封闭。

真实插件基于 OpenClaw 2026.9.4 defineToolPlugin 注册9个工具。message_received 使用 canonical media 与公开 session-store-runtime 会话代次；首次创建由 session_start 关联，reset/end 不继承未处理附件。到达即后台复制，before_prompt_build 提供一次数据回执。既有自动附件预览无法由本插件保证关闭，部署后需核对重复提取情况。

布局为 agents/<agent>/inbox、snapshots/<category>、cache/<job_id>、saved/<category>/<version_id>；10类目录幂等初始化。快照用完整SHA256及file_id，同Agent去重，每次attachment_id记录上传事件，不同Agent不共享物理快照。签名/文本预检与解析能力分开，未知格式也归档。

独立SQLite WAL。独占暂存复制、流式计数/哈希、核对原件状态、fsync文件、rename，可靠副本完成后登记；Linux另fsync父目录。服务锁与唯一索引处理重复上传。失败不登记；崩溃留下未登记物理文件保留诊断，不自动当成有效快照。启动将缺失的LIVE快照标MISSING并停用引用。暂存/未登记残留需管理员核对后清理，不会自动误删原件。

缓存键包含原件SHA、范围、选项、引擎版本、模型配置、服务版本与限制。同会话复用，不跨会话继承任务。模型要求固定不可变快照，不能在相同路径偷偷替换；准备manifest记录revision。明确选择历史file_id后生成当前会话引用再提取。删除原件是显式删除此Agent快照全部引用，活动任务拒绝；保存成果保留且来源DELETED。

缓存闲置72小时从完成或有效读取/使用计算。状态/健康/无效请求/find无命中不续期；清理每小时，读/保存/清理共锁，活动/排队任务保护。过期read返回CACHE_EXPIRED；快照、注册与保存版本不过期。保存先复制依赖束和来源，修复MD相对图片链接，再发布登记；失败保留缓存。版本不覆盖，逐字稿/模型纪要可分别选ID。保存询问一次状态持久登记，不回复不自动保存。

全服务重任务并发1，每任务独立可终止进程；Linux进程组/PDEATHSIG管理ffmpeg等子进程。启动异常落FAILED；调度器异常停止主服务，由systemd/Docker监督恢复。重启RUNNING变INTERRUPTED，QUEUED继续。失败/取消/超时保留检查点，不冒充完成。

音频600秒主区间+2秒重叠，按块解码释放数组，检查点校验SHA/配置/任务指纹；按词时间中点归属主区间，保留全局时间。识别边界仍可能丢字/变化，不承诺无重复。恢复跳过DONE块，重试失败块；无可读内容记失败。总预算max(3600秒,时长×8)，上限72小时；无进展1800秒单独限制。参数按NAS实测调整，不承诺实时。

PDF逐页提取/OCR，全文也是逐页处理，非一次渲染。页数10000、像素2400万、输出200万字符、图片32MiB独立限额；成功针对请求范围，不保证复杂阅读顺序或扫描完整还原。DOCX保留正文段落/表格顺序及图片，不自动OCR图片，页眉/文本框等不完整。文字限UTF-8。

临时Python通用补充，不新增Excel业务接口。只将已登记当前会话原件复制到任务执行；脚本、日志、输出、SHA和断言登记。Linux Landlock ABI≥3限制系统库只读/当前任务读写，libseccomp禁止网络socket及部分进程控制；进程资源限制和Docker cgroup/pids控制总预算。系统库规则可读库目录中的公共文件，不是微虚拟机。development仅供可信Windows测试，无系统隔离，不能用于生产。输出存在/格式/声明断言验证不等于全部业务语义正确。

服务只监听固定Unix socket，不暴露公网；Gateway只挂socket，不挂全部原件。持有socket或同UID任意代码具有可信服务权限，既有不受控exec是另一条边界，部署前需审查。目录分区、提示词、模型参数校验不能抵御管理员/同UID任意代码；脚本Landlock不能替代Gateway权限审查。

V2路线图：MD/简单文本生成DOCX/PDF、尽量保留版式的转换、具体风险提示与质量验收。本轮未扩展办公平台、用户中心或向量索引。

原件精确删除先提交DELETING意图，完成物理删除后停用引用、更新保存来源状态；启动恢复已提交的删除意图。文件缺失和损坏不会被当成新上传成功。迁移保留旧接收时间和旧根，不把迁移时间伪装成第一次收到文件的时间。
