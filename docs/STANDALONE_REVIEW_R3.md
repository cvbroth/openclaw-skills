# 独立 HTTP 评审 R3：使用、配置与迁移

本轮基于 `9579d184889e179f21b0adf78a56037e18d84290`，只更新独立开发服务。识别器、生产 OpenClaw/FileTools、知识库与原件不变。实施顺序见 `STANDALONE_REVIEW_R3_PLAN.md`。

## 使用

按既有方式 SSH 转发 `ssh -N -L 18971:127.0.0.1:18971 USER@SERVER`，打开 `http://127.0.0.1:18971/`。项目详情的“仅重新排版”选择已有 Markdown 与已发布模板，后台追加 Word/PDF、内容结构和诊断，并实际渲染预览。不发起 OCR。模板入口 `/templates`，评审入口仍为项目的 `/review/index.html`。

工具栏收起后保留返回、双方文件/位置、分别翻页与展开。每项目浏览器偏好独立。折叠和专注不重建正文或评论；单侧专注可恢复，双侧独立滚动。窄屏切换单侧；评论与技术详情可折叠。Markdown可切换格式化阅读/源码；格式化阅读禁止原生HTML执行、外部资源及活动链接。

产物显示名称、下载名称与实际路径/ID分开。显示名称含性质、引擎、格式、版本及已知模板。项目改名只刷新展示和下载名，原件、正文、哈希、定位、缓存键和评论不变。详情按格式/引擎/模板保留最新在外、旧版折叠；评审下拉保留全部版本供选择。尚未核实题干/选项归属的结果叫“Markdown排版稿（题目结构未核对）”或旧“保真片段排版稿”，不冒称正式试题整理稿。

## 内容与样式分离

`standalone/content_structure.py` 使用 `markdown-it-py==3.0.0` CommonMark（关闭HTML）。派生结构保存原始片段、来源产物及SHA、源行区间、稳定块ID、类型及行内runs。支持1–3级标题、段落/段内换行、加粗/斜体、原号有序列表/无序列表。列表采用显式原编号/符号与缩进，不启用Word自动重编号。嵌套列表记录深度，目前按统一缩进显示。4–6级标题保留内容并诊断降为3级；代码块保留字面内容；图片仅保留替代文字与诊断引用，链接保留显示文字与审计URL；表格/公式无专用排版能力，保留原文并记录可检测的诊断。不执行HTML、脚本或宏，不承诺任意Markdown扩展。

已知单选结构仅在既有解析器无疑点、无移除页边内容且存在明确题块时沿用题干/选项及分页策略；其余按Markdown结构保留，不猜归属。整页未被可靠恢复成题目结构时，不宣称短题整体分页已验证。原始识别Markdown不写回，派生内容模型为单独 `content-structure.json`。输入位置与PDF物理页分开，第12页图片仅凭已核实 `sources/pdf-provenance.json` 的图片SHA关联到原PDF12页；没有证据则PDF页为null。

Word/PDF共同消费结构和模板参数。实测Story配合仅Regular的中文字体没有合成行内粗斜体，因此基础Markdown派生PDF改为由实际DOCX经现有LibreOffice导出（受整体60秒及导出40秒上限），同版式内容通常同页数；已知无行内强调的试题结构仍可用原生PyMuPDF生成，两种入口都记录pdf_renderer，允许分页不同。不新增办公套件，沿用已有安装。早期Story尝试保留为旧版本，不混称强调已通过。页码是生成文档页码。原图评价、评论和诊断不写正文。Word字体未嵌入；服务端安装字体及LibreOffice预览不代表用户电脑字体替换通过。

## 模板机制

复用既有 `catalog.json / published / drafts / schema.json`，服务在 `STORE/template-library` 建立私有开发库；保留包内公共1.0.0及原SHA，没有另设生产注册中心。包schema新增默认 `space_before_pt=0`、`page_numbers=true`，旧模板文件与既有默认行为不变。服务默认引用沿用catalog.default；项目可保存selected_template，派生任务记录实际模板SHA和不可变快照。

示例配置：`deploy/template-examples/markdown-readable-{1,2}.0.0.json`。它们是导入示例，不自动部署。schema_version=2，严格允许id/version/name/description/content_types/parameters；ID小写字母数字及连字符、语义版本，字段长度受限。配置导入只接受JSON，请求≤1MiB；不支持ZIP、脚本、宏、字体文件或Word/PDF自动转模板。未知字段拒绝，错误定位到字段；参数范围与关系沿用 `templates/schema.json` 和 `document_templates.validate_parameters`，包括字号/页宽高/厘米边距、行距1–2、段距0–48磅、短题占页0.01–0.49、最少开头行≥2、选项缩进与悬挂关系、页脚须在边距内、页数上限1–1000。界面显示中文参数名，完整配置可展开编辑。字体来自服务端fc-list，不接受客户端字体路径；缺字体拒绝，缺字生成失败。

步骤：载入现有模板→改ID复制或增加版本→编辑→另存草稿→固定合成内容后台生成→实际查看Word/PDF预览→发布。未保存改动不得预览/发布以免误看旧配置；发布要求匹配模板SHA的合成生成任务成功且两个真实预览均成功，**不自动等同人工视觉验收**。发布复制到新published文件，保留draft历史，不能覆盖已登记版本。项目选择已发布版本再排版，追加产物和模板快照。回退是选择旧已发布版本重新生成新产物，不改旧项目历史或覆盖文件。

## API与模块

HTTP/UI选择输入、模板与操作；持久化队列执行 `operation=format-artifact`；派生子进程 `standalone.documents` 消费明确输入，60秒/2线程，无识别器。输出复用已有 `publication.publish` 校验复制发布，再登记独立artifact_id/parents/版本。实际预览继续独立串行任务，不阻断正文保存。

- GET/POST `/api/templates`：清单/校验另存草稿。
- GET `/api/templates/:id/:version`：不含可执行代码的配置；POST其`/preview`或`/publish`，JSON body `{}`。
- POST `/api/projects/:id/template`：选择已发布模板；POST `/api/projects/:id/format`：`source_artifact_id`与`template:{id,version}`，返回task_id、engine_calls=0。

通用OpenAI/M3接口保留；本轮测试开发容器未注入云端凭据，真实新调用不可用而不是模拟成功。核心独立模块不依赖Agent会话，未部署OpenClaw插件。

## 迁移、导出与回退

首次启动备份现有project.json及登记文件SHA后，仅补展示字段、读取视图的安全HTML和视图资源哈希；旧正文、模型响应、ID、定位、评论及预览键保留。历史未知性质不推断为已整理试题。原始Markdown与原图评价各自独立。服务恢复将中断任务如实标INTERRUPTED，不自动重跑。

LibreOffice profile、HOME、缓存放外部TemporaryDirectory，正常结束与受控异常finally清理；进程强杀可能留下容器/tmp目录，容器重启清理。项目导出排除历史lo-profile、隐藏目录/锁文件、tmp/temp、~$、pyc/next等运行杂项，保留实际预览、产物、来源、评论与必要诊断。旧历史包不修改。离线file://下浏览器可能忽略download文件名，因此导出额外提供downloads/语义文件名副本，以download_path登记；内容SHA、原artifact_id及原路径不变，服务端不搬动原文件。别名按UTF-8字节限长，重名附短ID。检查Windows保留名/非法字符，实际Windows解压尚需用户验证；长路径风险另见报告。复制/移动新离线包，内部相对链接保持。

回退独立服务：空闲时停止R3容器，用旧提交的独立worktree+旧镜像启动、保持原store及完整配置挂载；新增产物不删。若需完整恢复R2展示，使用本轮私有metadata备份逐项目评估合并，不能拿旧metadata盲目覆盖已新增任务/评论。公共模板旧版本未改，不涉及生产回滚。

解析器依据：[官方使用文档](https://markdown-it-py.readthedocs.io/en/latest/using.html)、[安全说明](https://markdown-it-py.readthedocs.io/en/latest/security.html)。
