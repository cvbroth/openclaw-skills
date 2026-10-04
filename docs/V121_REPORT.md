# FileTools V1.2.1 本地交付报告

已完成增量源码、测试、插件/通用Skill、NAS只读输入示例、可选Samba结果入口及安装/诊断/迁移回滚说明。没有连接或部署生产、修改现有检索仓库或导入链路、推送GitHub、创建PR或执行远程CI。

## 基线与提交

| 项目 | 记录 |
|---|---|
| 已审查V1.2基线 | feat/filetools-v1.2，e3ba3db219d1a133971bc78dee1aeea9d8635930，开始前工作树干净，没有后续修复 |
| 修订分支 | fix/filetools-v1.2.1 |
| 核心修订 | 171922bbe15d644610a438e997154c50f7bd962c：登记反馈/权限/只读映射、目录模式和可选Samba |
| Samba继承权限修复 | 91d53b3669e9ea528c215e0ef8504a256a21f478：结果共享不继承全局write-list/admin/force身份 |
| 回执额度边界修复 | f9f0043ac328205fcb2f975ba2b61dda9bdceee1：满额度的重复事件去重，溢出明确未登记数量 |
| 最终文档交付提交 | 本报告与证据归档后生成；确切最终HEAD记录在交付目录delivery.json和FINAL_COMMIT.txt及对话最终回复，避免提交内自引用哈希 |
| 参考检索项目 | 623aa73abcd0dc7f4854a58a8a42e8b6c4725072，tracked源码和配置未改 |

两仓库本地开发说明/既有接口沿用，未发现新增AGENTS/CONTRIBUTING约束。源码版本1.2.1，插件目标OpenClaw2026.9.4，QQBot2.0.3为生产参考；本轮没有验证生产运行实例。

## 对应问题与实现

1. before_prompt_build不再字符串切断JSON；pending、终态错误和重试成功均有可报告状态。5秒有界等待，背景继续，回执白名单/分页/明确续取。错误不吞终态，旧epoch拒绝采用；没有新Agent运行时不假称主动通知。
2. 诊断只对新的随机标记设置实际Gateway UID/GID、0660，无视宿主umask；显式Gateway身份读写，核对Worker默认UID/GID一致，失败finally清理。没有整工作区chown/chmod或开放/root。
3. 最深bind映射仍优先，工作区要求RW，NAS/download来源发现允许RO，Worker reference继续RO。拒绝..和相对映射；外部删除只取消登记，版本变化拒绝复用。
4. register新增可选select:false目录模式，不激活32个当前会话槽位，不增大上限/表结构；现有list/select复用。Skill在用户要求时用现有目录能力枚举本Agent业务资料、分批报告来源ID/去重/失败，不自动搬原件、提取或永久入库。
5. 个人Uploading→Incoming人为发布约定、3个人明确只读bind与source_root示例。Uploading/部分后缀明确拒绝，稳定哈希不承诺上传关闭。快照有独立空间成本，reference也不宣称所有处理零副本。
6. 可选samba-results复用管理员CLI，plan默认无系统修改，apply显式。已有账号按真实UID，saved-only ACL与bind/systemd单位/私有配置片段/testparm/幂等/诊断/回滚；只暴露saved，不暴露registry/cache。新版发布器修复0440/0600/原子JSON的ACL掩码，旧新产物立即可读；回滚保留新旧结果，保护后来管理员修改过的配置。

仍保持一人一Agent、独立Worker并发1、共享目录与UnixHTTP控制；十个工具名称不变，无账号平台/MCP/同步daemon/新索引。旧配置与数据兼容；新增参数、产物、架构取舍见 [接口文档](V121_INTERFACE.md)。运行时新增ACL逻辑用stdlib，无新Python引擎依赖，不向Gateway/检索虚拟环境临时安装包。

## 验证结论

- 静态检查和插件build/validate通过；Windows全量78通过/24跳过，最后目标4通过/3跳过；Linux全量真实引擎99通过/3跳过，最后核心目标22通过/6跳过。重叠用例不累加。
- Windows真实SDK/核心桥接19通过/1跳过，Linux实际SDK会话钩子和回执18通过。上下文/渠道为测试注入，**不是完整Gateway/QQ端到端**。
- 真正root管理容器 + 双UID10001角色容器权限/只读NAS来源验证通过，含umask022/077。不是实际NAS宿主/生产Gateway。
- 真正Samba daemon/客户端、三个临时真实账号、旧/新ACL和核心保存立即下载、写/跨用户拒绝、真实bind及幂等回滚：2通过。systemctl调用替身、故障注入单独标为模拟；真实开机和服务reload仍待验收。
- 7类实际CPU样本测时已记录；扫描PDF3.236秒、混合PDF2.920秒、11秒英语录音7.973秒，均为开发机Docker限2CPU/4GiB，不是NAS速度。DOCX带图片样本按实际PARTIAL报告，未伪称完整还原。
- 参考知识插件49通过/1跳过、TypeScript noEmit通过；参考Python全量因开发环境缺pypdf/sqlite_vec产生4个collection错误，**未完成验证**。该环境缺口未通过改生产/检索依赖规避。

完整命令、真实/模拟范围、计时与生产清单在 [验证文档](V121_TESTING.md)；可审查日志/JSON在docs/evidence/v121-*及交付evidence目录。独立镜像成功构建，最终回归通过readonly挂入当前源码验证；镜像不作为交付物，管理员从最终提交重建。

## 安装、诊断与回滚入口

核心入口 `python3 scripts/filetools_admin.py install|diagnose --config <install.json>` 保持；Samba入口 `samba-results --config <results.json>` 默认plan，修改需`--action apply --apply`，回滚需`--action rollback --apply`。仅管理员做NAS ACL/挂载/配置/reload，普通Agent不取得这些权限。配置和迁移/回滚顺序见 [安装文档](V121_INSTALL.md)；客户端与快照/移动区别见 [普通用户说明](V121_USER_GUIDE.md)。

V1.2→此版不需数据迁移。回滚先取消Samba再撤新版插件，保留数据/回滚审计。旧发布器不能保证新增saved ACL掩码，不能只降代码保留共享后声称完全兼容。旧V1.1迁移入口及知识库授权流程保持，main/chen不合并。

## 已知限制及待生产信息

生产全部待验收：真实UID/GID/进程用户、Ubuntu26.04实际FS/ACL与父级遍历、Compose源与私人Incoming授权、既有Samba全局配置及账号读取、systemd重启持久挂载、真实QQ/消息交付和各客户端/既有隧道、共享服务资源峰值。用户需提供匿名真实附件及私聊/群聊范围；当前群聊保守拒绝，不提供private群聊授权扩展。

没有4GiB完整传输/4小时中文ASR实测；自制小样本和201MiB快照不能代替。OCR手写/公式/复杂表格/照片理解不可靠；部分处理按覆盖和警告回答。公网/下载渠道、移动原件整理、结果展平/网盘UI、完整办公转换仍不扩展。V2路线图保留在V1.2支持文档。

Samba部署拒绝现有自定义named ACL、saved所有者不一致、未知入口/单位/挂载和后续配置漂移，需管理员审查明确小范围权限。系统ctl持久化本轮仅配置/模拟调用，不能标为真实NAS重启通过。可选共享是Linux功能，Windows仅开发与客户端下载。

## 交付及手动推送

最终交付目录含源码ZIP、完整Git bundle、相对V1.2基线的补丁序列、报告、证据、delivery.json与SHA256SUMS.txt；依赖/模型/私人配置不打包。具体最终提交和归档校验以交付清单为准。本轮没有GitHub推送。

```powershell
Set-Location "C:\Users\18296\Documents\Codex\2026-10-03\nas-openclaw-v1-https-github-com\work\openclaw-skills"
# 如果当前普通用户仍报 dubious ownership，只信任这一个已核验目录：
git config --global --add safe.directory C:/Users/18296/Documents/Codex/2026-10-03/nas-openclaw-v1-https-github-com/work/openclaw-skills
git switch fix/filetools-v1.2.1
git status --short
git log -4 --oneline
git push -u origin fix/filetools-v1.2.1
```

本地已提交，不必再次git add/commit。若推送提示远端同名分支有新提交，先fetch/review差异，勿直接force push。推送成功以后再在GitHub创建审查PR，未创建的PR不能称已存在。
