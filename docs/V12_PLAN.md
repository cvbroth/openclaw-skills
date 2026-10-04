# V1.2 实施方案与接口草案

基线ec6ea15f2ec833473bc776cbbb3e7f533ae86373；远程V1.1与本地一致，main仍83014f7；参考检索623aa73未变。独立分支feat/filetools-v1.2。开发不连接生产。

顺序：工作区/路径契约 → 共享登记核心和管理CLI → 处理/发布/读取/访问标记 → 插件与渠道交付 → 安装/诊断/迁移回滚 → 真实文件、引擎和失败回归 → 源码提交/报告。

实际Agent工作区下filetools/{snapshots,cache,saved,registry.sqlite}，共享核心只装一份。可信Gateway管理CLI处理原件复制/登记；worker只挂filetools子目录和明确授权的NAS引用根，不挂整个状态/认证目录。每Agent独立SQLite，服务仍一个Unix socket和全局单重任务队列，不增加管理容器或MCP。

| 接口 | 输入 | 结果/执行位置 |
|---|---|---|
| filetools_register | source_path + source_root或已登记引用，mode:snapshot/reference，request_id，说明元数据 | 可信Gateway管理核心：file_id/attachment_id、真实类型/SHA/状态/相对引用；不携带原件字节 |
| filetools_files | list/select/save/saved_read/delete/容量/touch/产物位置 | 管理核心；touch只用于真实访问后，不标记状态轮询 |
| 现有inspect/extract/status/cancel/read/find/save_minutes | 已登记ID和有界参数 | 独立处理服务，保留分页、范围、检查点和来源 |
| filetools_python | 已登记输入、脚本、声明输出与检查 | 私有执行→始终回收全部后代→校验→发布→登记；文本和二进制统一返回路径/格式/SHA |
| 交付 | 已验证Gateway路径 | 复用目标版已有message/QQ文件发送能力，只有真实发送回执才称发送；不存在能力时明确替代结果目录 |
| 管理CLI | 固定配置+可信身份+JSON操作 | 与插件共用Python核心，模型不能选Agent/注册表位置 |

snapshot优先reflink，安全回退流式复制；reference保留外部根映射/版本，变化不可复用产物。管理区已有发布产物直接登记，无额外快照。注册来源标签没有权限作用。普通read/Python可按自身权限读发布路径，登记不是系统读取的唯一许可。

Linux脚本Landlock只读本次输入、只写执行目录；发布区不授予脚本写权。Windows开发模式必须真实验证进程树回收，但不是Linux隔离证明。文件系统/容器、权限和QQ实际发送均分别报告实测与未验证项。

安装只增量挂载各filetools子目录，使用实际Gateway UID/GID，不递归chown原工作区。不存在或空plugins.allow保留开放语义；非空才追加。V1.1迁移独立备份+显式映射，旧数据保留，回滚不丢新增业务文件。
