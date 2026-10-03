# V1.1 安装、诊断、迁移和回滚

本轮没有连接或部署生产。目标：Ubuntu 26.04 x86_64、Docker、自定义 stockanalyse-openclaw-managed 镜像、OpenClaw 2026.9.4（3a9d69d）、QQBot v2.0.3；NAS 共享 Immich/数据库，CPU-only。Linux安装/资源边界/Docker增量覆盖仍须测试机和生产验收。

## 一个管理员入口

从交付源码目录运行 `python3 scripts/filetools_admin.py`，宿主只需Python 3.11+标准库与Docker/Compose客户端；引擎在单独Python 3.12 worker镜像，不向Gateway或检索venv装包。独立开发venv内也可使用 `nas-filetools` 同一入口。

只编辑 `deploy/install.example.json` 的一个副本：data_root（专用本地持久目录，例如/var/lib/nas-filetools-v11）、agents（已有Agent ID）、bindings（现有可信QQ channel/account/sender映射）。不新增账号密码。可选limits覆盖中央参数；只有多候选/无法推断时配置 gateway_container/gateway_config/compose_service。不要把示例sender当真实值。Gateway配置当前要求标准JSON，JSON5注释/复杂路径无法自动处理时明确失败，管理员先准备兼容副本，不静默改写。

```bash
python3 scripts/filetools_admin.py install --config /etc/nas-filetools-install.json
# 审阅计划、版本、现有Compose/持久挂载、磁盘、模型网络准备和重建范围后执行：
python3 scripts/filetools_admin.py install --config /etc/nas-filetools-install.json --apply
python3 scripts/filetools_admin.py diagnose --config /etc/nas-filetools-install.json
```

apply会构建独立镜像、准备typebox插件依赖，必要时下载固定small模型（revision 536b0662742c02347bc0e980a01041f333bce120），初始化各Agent文件区、备份Gateway配置/原插件、生成增量Compose并启动worker/重建Gateway，随后自检。首次需要网络、镜像仓库/HuggingFace可达和磁盘空间；模型约数百MiB，缓存部署后只读，运行network:none/offline:true。自定义模型必须给worker内可读的不可变路径并自行准备；下载只在安装阶段。没有GPU依赖。

需要Docker操作权限和持久目录owner管理权限（通常需管理员/root执行）。worker固定非root UID10001，socket采用已核实Gateway GID、目录0750/socket0660；原件目录0700由worker独占。插件文件和Gateway配置保留其实际UID/GID；必要时管理员以具备权限身份执行。不在任务中运行sudo或pip。默认2CPU、4GiB cgroup内存、96进程/线程，工作子进程另4GiB RLIMIT_AS（虚拟空间，并非RSS）；应据NAS实测调参。镜像需libseccomp2；宿主内核Landlock ABI≥3。Docker宿主权限是安装者权限，不挂Docker socket给worker或Agent。

自动读取Docker白名单信息：版本、UID/GID、Compose标签、挂载。保留原自定义Compose、其他插件、模型与工具配置；只合并nas-filetools条目和启用Agent工具名，不替换官方Compose。若现有策略deny这些工具则报错，不自动移除deny。数据根必须专用，拒绝混入其他服务目录。

新增文件位于data_root/installation/1.1.0；worker数据挂到/var/lib/nas-filetools，模型到/var/cache/nas-filetools，Gateway只增加/run/nas-filetools socket挂载。真实原件不挂给Gateway。插件安装在现有持久state/extensions/nas-filetools，旧版先备份。插件卸载默认不删除数据。

诊断检查持久目录/配额/可信绑定数量、Gateway版本/插件加载报告/socket挂载、service调度器健康，并在空闲worker内检查真实合成OCR、离线Whisper模型加载、临时Python隔离写入及网络拒绝。忙时DEFERRED；等待空闲后重试。缺模型/权限/依赖时输出明确问题，不泄露令牌或完整配置。模型加载成功不是中文转写准确度证明；plugins list的loaded也不是QQ端到端。

Windows只支持本地核心/开发测试。`install --local-only --apply`仅初始化工作区，不装Docker运行时；`diagnose --local-only`不检查Gateway/服务，不得称生产部署成功。development脚本模式仅可信测试，无强隔离。

## NAS inbox 大文件

[QQBot v2.0.3 attachment.ts](https://github.com/tencent-connect/openclaw-qqbot/blob/v2.0.3/src/middleware/attachment.ts#L301) 对应下载调用设置 maxBytes=500×1024×1024、timeoutMs=120000。这是插件实现值，不是QQ平台保证，不维护私有QQBot分支。

经现有Samba将文件放在自己的agents/<Agent>/inbox。Samba权限仅开放此人的inbox，不开放其他人的快照/保存区，不让Guest访问。先写 `recording.wav.part`，上传完成后原子改为 recording.wav，再在同目录写 recording.wav.ready：

```json
{"bytes":12345678,"sha256":"完整64位SHA256"}
```

标记自身也先写 `.tmp` 再改名，防止读到半份JSON。Windows可用 `(Get-Item 文件).Length` 和 `(Get-FileHash 文件 -Algorithm SHA256).Hash.ToLower()`生成值；Linux用stat/sha256sum。工具列inbox返回inbox_id，登记校验完成标记/大小/完整SHA，原inbox文件保留；未完成明确INBOX_INCOMPLETE。模型不能指定其他主机路径。接收4GiB不意味着无限展开/解析，超限需分批。

## V1迁移：先预览，旧根保留

V1 SQLite owner只有散列，无法可靠反推出Agent/会话，禁止猜测归属。管理员从旧可信绑定/会话备份提供 scope-map.json：旧owner散列 → 原可信 `{user_id,agent_id,session_hash}`，工具验证散列吻合。不能用聊天文本伪造迁移映射。旧服务须停止，迁移取得单例锁；新根必须与旧根分离。

```bash
python3 scripts/filetools_admin.py migrate --old-root /var/lib/nas-filetools-v1 \
  --new-root /var/lib/nas-filetools-v11 --identity-map /secure/scope-map.json
python3 scripts/filetools_admin.py migrate --old-root /var/lib/nas-filetools-v1 \
  --new-root /var/lib/nas-filetools-v11 --identity-map /secure/scope-map.json --apply
```

先校验原件哈希，备份旧SQLite，再复制归档到新Agent结构；旧原件/元数据/旧任务不删除。新根重新提取以采用V1.1配置和来源格式；旧结果仍在旧根，可回到旧环境读取。重复迁移相同ID内容复用，冲突明确报错。V1物理根不能直接由V1.1 serve打开，返回V1_MIGRATION_REQUIRED。新格式不能由V1直接降级。

## 回滚、升级和卸载

每次apply保留对应配置/插件备份及rollback.json。重复安装幂等合并目录/工具列表，不覆盖用户文件；最新回滚记录恢复上一次运行配置，重复安装V1.1后回滚可能仍是V1.1，初次升级记录需归档。

```bash
python3 scripts/filetools_admin.py rollback --record /var/lib/nas-filetools-v11/installation/1.1.0/rollback.json
python3 scripts/filetools_admin.py rollback --record /var/lib/nas-filetools-v11/installation/1.1.0/rollback.json --apply
```

回滚停止新worker，保留新数据和新插件副本，恢复旧配置/插件，以原Compose重建Gateway；原Compose若含旧worker则恢复它。没有数据库/索引回退。若安装后管理员又改过配置，摘要不匹配明确拒绝自动覆盖，按备份手工合并FileTools范围，再用原Compose恢复；避免丢后续修改。安装失败尝试按记录回滚，失败则INSTALL_FAILED_RECOVERY_REQUIRED，保留备份供人工恢复。

卸载是禁用nas-filetools entry、移除仅新增filetools工具/加载路径、归档对应插件、移除socket增量覆盖并停止worker；按原Compose重建。默认保留快照、保存、缓存和模型，不能rm整个数据根。既有知识库服务/导入链路不改变。

离线清理仅停止worker后执行 `nas-filetools cleanup --root <实际V1.1根>`，活动服务存在则拒绝；在线由每小时调度器清cache。清原件使用明确file_id工具请求或独立管理员政策。Samba inbox暂存和崩溃孤儿不自动删除，管理员核对后处理。
