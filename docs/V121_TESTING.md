# V1.2.1 验证与生产待验收

本文主体保留 `69c194c` 的历史验收记录；后续同 UID Samba 小补丁的本轮测试、模式区别及待验收项见 [UID 修复报告](V121_SAMBA_UID_FIX.md)，不能把旧结果当成本轮重测。

执行范围仅开发机 Windows、Docker Desktop Linux。所有测试文档为自制样本，11秒英语 JFK 录音沿用固定 MIT 许可样本；模型固定 small 离线快照。没有连接NAS/QQ/远程Docker或运行GitHub CI。原引擎和覆盖/来源行为保留，扫描提取非空不等于完整还原。

## 实际结果及边界

| 检查 | 本轮执行结果 | 证据与边界 |
|---|---|---|
| Ruff / git diff --check | 通过 | src/tests/scripts静态检查，非真实处理证明 |
| Windows完整Python回归 | 78通过、24跳过 | 最后补充目录分页后另跑修订目标4通过/3跳过；跳过Linux、真实引擎和可选Samba，不相加冒充独立总数 |
| Linux完整Python回归，真实引擎开启 | 99通过、3跳过，144.16秒 | 10项真实引擎包含扫描/混合PDF、DOCX、印刷图片、11秒录音和来源/保存；3项为Windows专属、可选root Samba两项 |
| 最后核心目标回归 | 22通过、6跳过 | 新1.2.1固定依赖镜像 + 最终源码RO，含目录字节预算分页/元数据；6项真实引擎在这次目标运行未开启，前述全量已真实执行 |
| Windows插件+真实核心桥接 | 19通过、1跳过 | 真实SDK工厂、管理CLI、后台核心及MD/XLSX；会话/渠道客户端测试注入，Linux SDK存储项跳过 |
| Linux SDK钩子/回执 | 18通过、无跳过 | 真实OpenClaw2026.9.4 SDK与原生会话存储；含before_prompt_build pending→success；不是Gateway daemon/QQ端到端 |
| root manager + 双非root容器 | PASSED | umask022/077，真实UID10001双角色读写、标记清理、真正RO NAS挂载快照/引用、版本变更拒绝、只解除引用、原saved入口可写。角色容器不是OpenClaw daemon |
| 实际Samba集成 | 2通过 | smbd/smbclient、3真实临时Unix/Samba账号、旧0440/新0600原子JSON、新核心提取→save→立即下载、写/跨用户拒绝、绑定挂载、幂等与回滚数据保留；全局写/强制身份参数不泄入本共享，配置/片段漂移拒绝，busy故障后回滚续作 |
| 独立1.2.1运行/测试镜像 | 构建通过 | CLI/依赖准备证据，不代替真实处理；镜像不是交付二进制，部署从提交重建 |
| 现有知识库插件 | 49通过、1跳过，TypeScript noEmit通过 | 参考仓库623aa73未改，私有/Family导入同意门、scope/query等测试；Windows symlink项跳过 |
| 参考检索Python全量 | **未验证完成** | 收集4项失败：独立文件工具开发环境缺pypdf/sqlite_vec，未给既有检索/Gateway环境安装依赖；不是检索算法失败，也不算通过 |

以上全量与最后目标回归有重叠，不累加数量。具体日志位于交付 evidence 和 docs/evidence/v121-*。完整Python回归执行后新增一项分页测试与登记返回元数据，经最后目标回归验证；引擎代码本轮未修改。

## 真实CPU样本耗时

Linux本机Docker，限2CPU/4GiB、引擎线程2、重任务并发1，小模型离线CPU int8；以下为独立Worker wall time，含启动，不能外推Xeon NAS性能：

| 自制/许可样本 | 实际结果 | 秒 |
|---|---|---|
| text.pdf 两页 | SUCCEEDED | 0.922 |
| scan.pdf 一页 | SUCCEEDED | 3.236 |
| mixed.pdf 三页 | SUCCEEDED | 2.920 |
| ordered.docx 表格/图片 | PARTIAL，图片独立保留/图片-only块不当可靠文字 | 1.012 |
| printed.png 印刷字 | SUCCEEDED | 2.258 |
| notes.md | SUCCEEDED | 0.971 |
| jfk.flac 11秒英语 | SUCCEEDED，真实时间来源 | 7.973 |

benchmark JSON包含配置/覆盖/警告/各项状态和注册、检查耗时。4GiB完整传输、4小时中文ASR、真实复杂扫描表格/手写/公式没有执行。本轮全量还实际复核旧201MiB快照测试，不把计数边界当4GiB真文件。

## 本地复现

核心独立环境与模型准备沿用 [V1.2测试说明](V12_TESTING.md)。Ruff检查、Windows/Linux区别和依赖固定值见pyproject及requirements.lock。测试不需要生产身份或真实密码。

```bash
python -m ruff check src tests scripts
python -m pytest -q
cd integrations/openclaw-filetools
FILETOOLS_TEST_PYTHON=../../.venv/bin/python npm test
npm run plugin:build
npm run plugin:validate
```

以下命令仅针对开发机本地 Docker `desktop-linux`，不能改为未知远程context：

```powershell
docker --context desktop-linux build -f deploy/Dockerfile -t nas-filetools:1.2.1 .
docker --context desktop-linux build -f deploy/Dockerfile.test -t nas-filetools-test:1.2.1 .
.venv\Scripts\python.exe scripts/docker_v121_smoke.py --output ..\v121-evidence
docker --context desktop-linux build -f deploy/Dockerfile.samba-test -t nas-filetools-samba-test:1.2.1 .
docker --context desktop-linux run --rm --privileged --network none -e FILETOOLS_SAMBA_TEST=1 -e PYTHONPATH=/opt/nas-filetools-check/src -v "${PWD}:/opt/nas-filetools-check:ro" nas-filetools-samba-test:1.2.1 -m pytest /opt/nas-filetools-check/tests/test_v121_samba.py -q -p no:cacheprovider
```

privileged仅用于本地一次性容器内实际bind mount，没有宿主生产目录/网络端口映射；不会给生产Worker增加权限。Samba测试调用testparm/mount/umount/runuser/smbd/smbclient是真实；systemctl的daemon-reload/enable/disable明确记录为替身，真实开机/服务重载未运行。Samba临时密码从随机生成的0600测试认证文件提供，终了删除，不输出到报告。

批量45个实际小文件登记/完整SHA/快照/去重/32槽位选择限制、系统文件排除及受限字节分页是真的文件系统测试；登记慢服务、错误重试、身份上下文、容量/故障、diagnose命令失败和权限失败注入是模拟。不能把这些称为真实QQ或NAS故障复现。

## 部署后待验收（全部待验收）

1. **安装前身份和目录**：实际Gateway主进程/exec UID/GID一致、Compose源/多重bind、各Agent分离、FS/ACL、磁盘余量。已有插件loaded列表只是诊断证据；还需验证活跃Agent真实工具清单及实际调用，tools.effective预览不能代替。
2. **QQ私聊**：同一用户上传附件-only与附件+任务；模拟较慢登记可见pending，不重传；完成后下一次运行/查询见ID；先检查再按范围处理/读取引用；故障恢复同ID重试；/new旧epoch不得采用旧附件。chen/liang/azl及main独立目录均验证，发真实结果后由客户端下载核对哈希。
3. **QQ群聊**：当前策略明确拒绝群聊FileTools工厂/登记，不读取任何私聊附件或跨人文件，不把群员正文当可信身份。同群两个用户也不可共享private ID。群聊授权扩展不属于此版，不能配置成任意sender。
4. **NAS大文件**：Uploading中的文件拒绝；完成移动Incoming后容器真实UID可读且不可改；分别快照/引用、来源变更拒绝、取消与重启状态。4GiB与4小时中文录音、长PDF实际资源/速度和共享服务峰值需实测，再调线程/超时/内存。
5. **Samba结果**：先plan/testparm/ACL/路径遍历，再apply；核对每个share的permission_mode，同UID保留所有者本地权限，不同UID检查读者Unix不可写。旧文件和保存新版本可从对应个人账号立即下载、图片和JSON完整、无缓存/登记表暴露；所有交叉账号和guest拒绝，上传/覆盖/删除/重命名拒绝，Gateway/Worker保存仍可用。检查全局write-list/admin/force参数不会泄入本共享。
6. **重启与回滚**：真实systemd开机持久挂载、源目录缺失明确失败、重复apply不叠mount、错误mount/后续配置变动诊断、真实smbd reload；先撤Samba再撤插件，保存数据和原个人/Family/隧道/知识库配置保持。Windows/macOS/iPhone与远程既有客户端各自下载验证，不能只看ls成功。
