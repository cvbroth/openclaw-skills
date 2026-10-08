# 独立任务项目与通用离线产物评审（开发实验）

沿用既有离线HTML和回执校验思路，新增产物层适配；不替代 `ocr_review_bundle` 的文字修订账本，不新增服务、模型调用或转换引擎。没有部署或接入生产FileTools。

## 项目与产物

每次显式新建转换任务调用 `artifact_project.create_project(root, name, task_id)`，生成独立UUID project_id；**不是按原件SHA聚合**。同一任务继续生成格式时读取其project.json，将新文件放进该项目，用 `register_artifact` 加入新artifact_id/版本/SHA及真实父产物ID，再 `emit_viewer`。同一内容不同版本亦分别登记，不覆盖旧文件；需变更项目定位契约时显式增加project.revision，旧回执被拒绝，不迁移确认。新增文件的生产job生命周期接入尚未实施。

目录为project.json、sources、content、templates、outputs、review、diagnostics。登记路径为项目内相对路径，拒绝绝对路径、上级跳转和逃逸符号链接；原件采用单独external_reference，保存确切外部路径和预先核对的SHA，模块不会跟随该路径读取、复制或修改原件。浏览器不自动访问外部原件，始终提示它不在包内，可能不可访问；包内已有预览支持移动目录后查看。浏览器不能可靠探测任意服务器路径当前可达性，不作已验证可访问承诺。

模板按实际版本/ID/SHA快照保存在templates；核对历史generation-metrics的模板SHA才允许加入。本次M3直接转写未使用文档模板，明确记录not-used，不编造模板配置。小样保留questions-zh-cn/1.0.0原字节快照，不修改公共版本。

registry提供format、version、sha256、parents、pages/locator、preview与映射边界。预览资源记录各自SHA。Markdown优先沿用既有稳定块ID，缺少则来源页定位；Word缺少段落ID时只评价文档或明确的历史渲染页，不伪造段落映射。输出PDF/Word预览页码是输出自身页号，**不等于原PDF物理页码**。位置独立选择，不同步滚动或按页数猜配。Excel只预留格式与sheet_range定位字段，没有本轮转换或预览能力。

## 构建与查看

`scripts/build_artifact_projects.py --help`接受明确的旧50页交付目录、小样产物目录、已有预览目录、模板和外部原件引用，输出路径必须不存在。它创建两个独立项目：旧50页M3实验，以及真实第6–10页生产小样，避免虚构衍生关系。原文件和旧交付包均不修改。

完整解压，打开顶层index.html选择项目。选择左右产物后分别选择位置；顶部不随长文滚动，左右独立滚动，底部评论无需滚到底。窄屏按钮切换参考/结果视图。技术资料默认折叠。正文以textContent展示，保留Markdown原文换行，不执行附件HTML。当前页文本使用本地脚本资源按需加载，支持file://无fetch；只给当前预览设置图片src，技术资料和原始响应只在用户打开时读取。没有CDN、在线字体或UI框架，使用本地系统字体。

PDF优先已有页面预览；没有时可用浏览器object预览，并始终提供打开／下载入口，浏览器内嵌不可用不能冒充成功。Word使用明确标注的历史LibreOffice渲染图片；没有预览时提供文件及文档级评论，不声称原生显示或用户字体替换已验证。没有新安装办公套件。

质量、评论和处理错误筛选可组合。质量仅来自相应模型质量记录；未提供独立显示，不当作图像低质或处理错误。原有质量JSON格式失败仍是解析错误，正文继续显示。模型质量自评与人工评论分区，均不是确认正文正确。

## 评论回执

草稿键包括project_id、目标artifact_id及SHA、目标locator、参考artifact_id及SHA、参考locator。输入即保存到本机localStorage，切换前再次保存；不同项目、版本和对照位置不串用。file://的localStorage兼容性和移动目录后的保留受浏览器限制，**导出JSON才是可移植备份**。不可用时提示导出，不承诺服务端自动保存。

导出schema=filetools-artifact-feedback-v1，含project_revision、reviewer_type（用户自行声明，不是认证）、comments（正文与UTC更新时间等）。初始没有人工评价。浏览器导入先整体校验，拒绝项目、目标／参考哈希、定位及现有草稿冲突；文本不作为HTML执行。开发侧入口：

```bash
python scripts/import_artifact_feedback.py --project PRIVATE/project --receipt PRIVATE/feedback-export.json
```

开发导入再次验证身份类型声明、版本、ID、哈希、位置及重复目标；并核对被评论的包内原文件字节。以base_feedback_revision做乐观并发检查，默认0；后续更新必须基于最新回执版本，不自动覆盖历史。追加review/feedback-history/revision-N.json，再原子更新feedback.json，原正文/原图不变；锁及历史序号冲突时停止。若中断留下历史文件或暂存文件，需要人工核对，不自动删除或越过。该最小入口不提供账号认证、电子签名或服务器协同编辑。

这是**评论接口**，不会自动改字、批准整页或改变旧OCR确认账本。单条评论不等于整份文档通过；原有OCR修订仍使用原专用校验入口。模型自评与开发Agent测试不能变成人类验收。

## 验证与后续接入

合成单元测试 `tests/test_artifact_project.py`；真实浏览器机制测试 `scripts/browser_smoke_artifact_projects.py --root PRIVATE/package --output PRIVATE/check.json`，使用既有开发Playwright，不是生产依赖。操作使用合成评论，不写回交付包，不冒称用户意见。

未来生产接入点是：可信job_id确定任务实例 → 在许可工作区创建project → 正式登记/受限处理/发布回执返回后追加实际artifact及SHA → 保存真实模板快照和来源映射 → 生成静态review。不能让模型自行指定任意服务器目录、把附件配置当模板执行或以项目路径替代正式附件回执。当前仅准备通用开发模块，尚需生产生命周期、可信身份、清理策略、受限权限与正式发布集成验收；本轮不实施。
