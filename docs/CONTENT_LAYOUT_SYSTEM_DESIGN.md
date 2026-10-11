# FileTools 通用内容结构与排版系统设计（待审核）

日期：2026-10-12。实际远端基线：`ae5a5ebdddd7fbc2b1ed7a196fe7dc84b90a28a4`，分支 `eval/filetools-paddleocr-vl-20261006`。

本轮仅设计：从远端获取最新提交，在隔离工作树编写本文；没有修改产品代码、运行识别或付费模型、变更数据或部署，也没有实施段落点击定位。已读取根目录 `AGENTS.md`；其日常部署授权在本轮受用户明确“只设计、不部署”的范围限制。日常服务挂载工作区保持原样。

建议保留 python-docx → LibreOffice → PDF 主链，扩展已有 `standalone-structure-v1` / `markdown-content-v1` 及不可变修订机制，把导出中的结构猜测移到一次、有版本的结构派生过程。普通新书选择内容规则包和样式即可；不通过书名分支、题号补丁或生成器正则不断适配。现有输出先保留兼容，分阶段切换，不能因本文被提交就自动实施。

## 1. 当前实现及问题依据

下文“已实现”表示基线代码有实际执行路径；“部分/仅配置”说明局限；“拟议/未实现”不是现有能力。源码链接相对 `docs/`，函数名为主要定位依据；审计固定在上述 SHA，不能把后来工作区变化当成本轮基线。可通过[固定基线源码树](https://github.com/cvbroth/openclaw-skills/tree/ae5a5ebdddd7fbc2b1ed7a196fe7dc84b90a28a4/src/nas_filetools)复核。

### 1.1 数据存放与权威关系（已实现）

以项目数据根 `projects/<pid>/` 为相对根；日常实际父根为 `runtime/standalone-http-r1/data`。下列是代码路径盘点，不是本轮重新提取真实文件。

|数据|当前存储与关系|依据|
|---|---|---|
|项目及原件|`project.json` 登记 artifact UUID、format、version、sha256、parents、pages；原件在 `sources/`，上传时复制保存，分析与渲染另存|[tasks.py](../src/nas_filetools/standalone/tasks.py) `Projects.upload/render`；[artifact_project.py](../src/nas_filetools/artifact_project.py) `create_project/register_artifact`|
|上传分析|`diagnostics/analysis/<analysis_id>/analysis.json` 及 project.analysis 引用，记录实际类型、页数、尺寸等；独立于文字提取|[analysis_jobs.py](../src/nas_filetools/standalone/analysis_jobs.py) `AnalysisJobs.analyze/execute_analysis`|
|原始提取与失败|`diagnostics/tasks/<tid>/page-<n>/...` 的各次尝试 request/result，经 `latest.result` 引用；返回 `text/blocks/input/native/raw_response/quality/error`，并非所有引擎都有全部字段|`Projects.execute/run_child`；[engine_worker.py](../src/nas_filetools/standalone/engine_worker.py) `main`；[adapters.py](../src/nas_filetools/standalone/adapters.py) `recognize/separate`|
|发布 Markdown|`diagnostics/tasks/<tid>/generation-<v>/published/content.md`，每页正文前附来源物理页与 task HTML 注释；登记为 markdown artifact|`Projects.publish_results`；[publication.py](../src/nas_filetools/publication.py) `publish`|
|提取结构 JSON|同批 `published/structure.json`，`standalone-structure-v1` 包含 pages、physical_page、status、text、blocks、input、error、diagnostic；没有题目树的统一保证|`Projects.publish_results`|
|阅读片段与来源映射|`content/<tid>/v<v>/page-<n>.js`，保存 text、reading_html、质量和诊断引用；artifact.pages 的 locator、source_page、data、data_sha256 为登记关联。默认每页一阅读片段，即使引擎有多个框；来源信息并非从题号推导|`Projects.publish_results`；`artifact_project.page_data/emit_viewer`；`text_revisions.mapped_text`|
|人工修订|`content/revisions/<revision_uuid>/content.md`、`page-<i>.js`、`structure.json`、`revision.json`；JSON 分别为 `manual-text-structure-v1` 和 `manual-text-revision-v1`。新 artifact 指向 parent，head 独立登记；恢复历史会创建新版本|[text_revisions.py](../src/nas_filetools/standalone/text_revisions.py) `TextRevisions.save_text_revision/text_artifact/text_diff`|
|评论与质量|评论回执经 `review/feedback.json` 等独立保存；绑定 artifact、哈希和 locator。原图质量在来源评估记录中，正文和准确率不能由其替代|`artifact_project.validate_feedback/import_feedback`；[source_quality.py](../src/nas_filetools/standalone/source_quality.py) `migrate`|
|导出及快照|`diagnostics/format/<tid>/template.json`、`work/request.json`、`published/document.docx/document.pdf/content-structure.json/layout-validation.json`，来源分页另有 `pagination-report.json`；登记 `export_source` 与 source_output_mapping|[format_jobs.py](../src/nas_filetools/standalone/format_jobs.py) `format_artifact/execute_format`；[documents.py](../src/nas_filetools/standalone/documents.py) `generate`|

当前 Markdown 与页面 JS 的一致性由 `mapped_text` 校验：文件哈希、唯一 locator、页面 data_sha256、整稿与所有片段按顺序拼接一致（支持带来源注释的旧拼接）。JSON 目前主要是提取证据或派生诊断，**不是与 Markdown 同等可编辑的正文权威**。修订会重建所有片段的 Markdown 结构并将精确坐标置空，保留片段 locator 和来源关系。启动恢复已取消为历史 JS 原地补写 reading_html，不能把页面资源刷新当作正文迁移（`Projects.recover`）。

### 1.2 导出调用链、重解析与重复转换

当前主调用关系：

```mermaid
flowchart LR
  A[HTTP显式导出] --> B[export_documents / export_options]
  B --> C[format_artifact：文字与模板快照]
  C --> D[execute_format：读Markdown及页面JS]
  D --> E[documents.generate]
  E --> F[每片段 structure_ocr 猜测试题]
  F --> G[成功：paragraphs 后再 parse_markdown]
  F --> H[有issue或去边界内容：直接 parse_markdown]
  G --> I[扁平 style/RichText 元组]
  H --> I
  I --> J[write_docx / apply_styles]
  J --> K[LibreOffice实际转PDF及验证]
  K --> L[不可变发布及预览]
```

依据：[http.py](../src/nas_filetools/standalone/http.py) `Handler.dispatch`；[document_exports.py](../src/nas_filetools/standalone/document_exports.py) `export_options`；`FormatJobs.export_documents/format_artifact/execute_format`；`documents.generate`；[document_sample.py](../src/nas_filetools/document_sample.py) `structure_ocr/paragraphs/write_docx`。

实际重复点及影响：

1. 提取发布时 `parse_markdown` 生成 reading_html；人工修订再次生成结构；**导出不消费这些已生成结构**，而是重新读取文字。`existing_structure_sha256` 目前仅在 `documents.generate` 的输出诊断中取值，`execute_format` 没传入现有结构供渲染，因此不能宣称“已有结构复用”。
2. 每个片段先以人工拼接的 `## 第 n 页` 调用 `structure_ocr`，只有无 issues、无 removed_headers_footers 且存在 question 才使用其结果；之后语义段又经 Markdown 解析。否则逐片段 CommonMark 解析。每片段独立解析也使跨片段/跨页题目无法形成可靠整体。
3. `content_structure.items` 将 block 压成 `(style, RichText)`，丢失树、block ID、组所属关系；`write_docx` 又用 `item_groups` 与 `option_layout_items` 重新决定组和选项。结构判断分散在解析器、样式映射、布局层。
4. 来源分页会逐组、多次实际 Word→PDF 后再合并、重新渲染并逐页比对；这是必要的渲染反馈，但不是重复 OCR。Word 单选或 PDF 单选仍生成两种文件作验证，只把用户所选格式标为 export。
5. Word 独立预览会再次由 LibreOffice 渲染；PDF 预览直接栅格化。缓存可复用但不能拿独立 PDF 替代 Word 实际渲染。依据：`source_pagination.generate_source_pages`、`FormatJobs.execute_format`、[preview_worker.py](../src/nas_filetools/standalone/preview_worker.py) `export_docx/render`。

### 1.3 通用能力、试题规则与书本特例

|类别|实际能力及状态|文件/函数依据|
|---|---|---|
|通用且已实现|CommonMark 标题、段落、基本列表、粗斜体、raw/source_lines；禁原始 HTML，链接保留显示文字；无 OCR 的修订和显式导出|`content_structure.parse_markdown/items/reading_html`、`TextRevisions.save_text_revision`|
|通用但部分|`markdown-content-v1.blocks` 为扁平数组，列表有 depth 但无列表容器；H4–H6 输出压至H3；Markdown ID 含 source、行范围和 raw 哈希，修改前文后不保证跨版本稳定；literal ID 依数组位置|`content_structure.parse_markdown`|
|通用尚未实现|统一文档/章节树、图片资产输出、原生内容表格、公式结构、稳定对象修订关联、统一结构缓存消费、声明式规则版本|`parse_markdown` 对图片仅留文字/引用诊断、疑似表格仅保留文字；`documents.generate` 仅走现有块/试题路径。Word内部布局表格不是内容表格支持|
|试题专用且已实现|题号和A–D正则、题干/选项/材料/要点、中文章节关键词、按短题高度保留整题、短选项行数及悬挂缩进|`document_sample.structure_ocr/heading_style/paragraphs/item_groups/StoryLayout/write_docx`|
|仅配置或非主链保证|`content_types` 目前只是受限标签及验证，没有据此选择独立内容规则；`minimum_start_lines` 主要服务 Story/PyMuPDF 直接PDF算法，不是当前LO主链的等价孤行控制；没有可配置整组选项策略|`TemplateLibrary.validate/load`；`document_sample.write_pdf/StoryLayout.long_option_tail` 对比 `write_docx`|
|书本配置|`xiao-1000-compact-a4-1.1.0.json` 的A4、1.5cm、11pt、1.05行距、短选项两列属于样式预设，不应进入内容协议|[真实模板配置](templates/xiao-1000-compact-a4-1.1.0.json)|
|带样本背景的代码约束|`structure_ocr` 默认页范围6–10（日常显式传n,n覆盖）；`finish` 的题干以“著”结尾判截断；章节层次关键词推测；A–D及三位题号限制。不是按书名执行的分支，但有领域/样本经验，不能视为普适语义|`document_sample.structure_ocr/heading_style` 及文件级 QUESTION/OPTION/CHAPTER 常量|
|当前主要风险|两列模式会把单独A–D行标成Option，然后只看相邻AB/CD与宽度配对；一组长短混合时可能一行两列另一行单列。布局没有携带完整组选项ID，可能跨错误边界配对|`document_sample.option_layout_items/write_docx`，尤其两个元素的pair扫描；不是新增缺陷复现结论，而是可直接确认的代码决策边界|

用户反馈“层次混乱、缩进不齐、过紧却留白大”与上述路径存在合理关联，但本轮没有重新做跨书实测，不能把所有视觉现象都认定为同一根因。比如短题整组防拆可能产生页尾空白；原件分页下稀疏页也可能合理留白。应记录是哪条规则导致，不以页面填充率一项判错。

### 1.4 Word样式导入的实际范围和优先级冲突

依据：[word_import.py](../src/nas_filetools/standalone/word_import.py) `extract/_extract/suggestion/WordImports.import_word/select_word_import`；[word_styles.py](../src/nas_filetools/standalone/word_styles.py) `validate_styles/apply_styles`；`TemplateLibrary.validate/load`；`document_sample.write_docx`。

- 已实现：无宏 DOCX/DOTX 包检查，保存原包及哈希/提取报告；展开 docDefaults、basedOn 继承；提取 Normal、Title、Heading1–3、Footer 的字号、粗斜体、段距、倍数/固定/最小行距和左右/首行/悬挂缩进；读取各节纸张/页边距/页眉页脚距离，多种节设置要求选一个。
- `word_styles` 校验还允许 Option；但导入器没有自动提取任意自定义 Option 样式。正文直接格式、主题、复杂表格样式、编号、制表位、边框、浮动对象、多栏、装订线和对称页边距不能完整还原。页眉页脚内容不复制。
- 中西字体只记录，不原样恢复字体继承/主题；用户须明确选择已安装统一字体，再建立草稿、合成预览和发布。导入参考样式不等于扫描版面复刻，也不等于完整复制一个Word模板。
- 当前执行先由 `write_docx` 设参数和直接 keep_* 格式，再 `apply_styles` 覆盖部分样式/纸张。Normal 扩展会复制给 Question/Option/Point/Material 等；特定 Option 覆盖 Normal，但 OptionPair 不继承 Option 的独立修改。表格两列可能直接把缩进置0；只要提供 section，`apply_styles` 会按可用宽度重设表格均分列宽。
- 来源分页 `materialize=True` 将段落样式写成直接格式、字号适配再覆盖，连续模式不 materialize；直接粗斜体优先于样式，不同运行路径可能表现不同。补充字体运行段的 font.name 会保留。现有接口未表达“标题跟随”和“孤行”规则，导入提取也不覆盖这些属性；不能据字段存在宣称可配置。
- 拟解决：一次解析继承/优先级，生成 effective-style 与来源说明；移除布局后到处重复覆写同一属性，渲染器仅执行解析后的结果。

### 1.5 字体、分页、验证、快照与兼容

|事项|已实现|边界/待改进与依据|
|---|---|---|
|字体|主字体文件哈希；Noto补充链清单/上游/OFL/hash；按缺字分run，Word嵌入补充字体；LO进程临时fontconfig；实际PDF字形检查|[document_fonts.py](../src/nas_filetools/document_fonts.py) `fallback_records/font_runs/font_audit/embed_fonts`；`documents.generate` 校验快照；`preview_worker.export_docx`。主字体不等于全部内嵌，桌面Word跨平台分页未无条件保证|
|分页|continuous或source-pages；同一来源物理页相邻片段聚合，逆序拒绝；实际渲染、最终合并逐页全文比对；空页保留|[source_pagination.py](../src/nas_filetools/standalone/source_pagination.py) `options/group_pages/generate_source_pages`。无更细映射的跨页片段不能准确按页拆分；当前导出主要接受单值source_page|
|溢出|先原字号，再压段距；可选0.5pt降字号至下限；续页需显式允许，失败保留报告|同上。当前“压段距”第二尝试自动执行，即使font_fit关闭；新设计应把该授权独立并显式快照，不能把它描述为现有独立开关|
|正文验证|原件/文字/data哈希、整稿拼接；DOCX段落和PDF文本去空白比较；实际页界/缺字；部分旧路径用Story估算；视觉效果仍需检查|`mapped_text`、`documents.generate`、[document_layout_checks.py](../src/nas_filetools/document_layout_checks.py) `check_layout`、`document_sample.validate_pair`；不能证明语义、空格忠实、图片表格完整或所有遮挡；派生输出一致也不能证明前面语义解析从未改变原文|
|快照|来源文字ID/version/hash、模板ID/version/hash及模板字节快照、页范围、分页、来源输出关系、renderer/formatter诊断；新tid发布新目录|`FormatJobs.format_artifact/execute_format`、`artifact_project.snapshot_template`、`documents.generate`。缺独立结构/规则/effective-style版本快照；字体审计有记录，模板JSON本身未囊括所有运行环境|
|历史兼容|模板v1读取时内存转v2；v2/v3，旧format接口/显式export并存；历史文字只读恢复成新版本；来源阅读识别source_pages并保留跨页事实|`TemplateLibrary.load`、`TextRevisions.save_text_revision`、[source-reader.js](../src/nas_filetools/project_assets/source-reader.js) `explicitSources/sourceMatches/renderSourceReading`。阅读多页映射比导出更丰富；不能把source_pages[0]当作精确归属|

既有真实证据范围：上一轮[修复记录](WORKBOOK_TEMPLATE_EXPORT_FIX.md)覆盖同一本肖1000的20/50及已有178来源组。它不证明普通文章、另一本试题、图表报告都已通过。本文公开部分不复制真实正文或截图。

## 2. 统一结构：扩展已有协议，保持一个权威入口

### 2.1 协议演进及职责

建议将已有 `standalone-structure-v1` 演进为 `standalone-structure-v2`：仍是项目原件—文字版本—结构的封装，保留 pages 证据；增加 document/root、objects、版本依赖与映射索引。叶节点延用 `markdown-content-v1` 的 `type/text/runs/raw/source_lines` 概念，并扩展层级和来源字段。`manual-text-structure-v1`、`derived-content-v1` 只作为旧包适配输入，不发展第三套可编辑模型。导出诊断改为引用此统一结构和排版计划，而不是再存另一套自称权威的正文。

不在本轮发布新schema。以下v2、字段、接口、规则包都为拟议；真实schema须在获批实施阶段版本化校验。

权威分工：

1. 原件及原始提取结果是不可变证据，原始 blocks/native 不因修订覆盖。
2. **正文权威继续是选中文字版本的 Markdown artifact**，并以登记片段和hash确保完整拼接；保留现有编辑/恢复用户流程。结构text/runs只是绑定该hash的派生视图，不允许另行直接编辑JSON正文。
3. 人工结构纠正仅写“语义标注操作”（如把已有span设为Heading2、把指定span组为option_group），绑定文字hash和稳定对象/span；不复制并改写一份正文。改变文字必须创建新文字版本。结构标注是分类/组织权威，不能覆盖正文权威。
4. 结构可有多个**不可变派生版本**（解析器升级或语义标注变化），每次导出固定其中一个，缓存必须按文字hash、片段映射hash、解析器/规则版本、标注hash命中。缺少/过期时本地派生一次；不可在Renderer中重新猜结构。
5. 图片资产用已有项目artifact/相对路径及SHA引用；表格单元格的文字也须来自权威文字span。纯Markdown不能完整表达的已登记图片/表格形状由来源证据和语义标注描述；新增/删减资产或改变单元格文字应形成带manifest的新内容修订事务，而不是单独偷改结构JSON。早期未支持该事务时只保留原引用与原文降级，不假装双向编辑已实现。

这样不要求更换现有项目注册/文字协议；结构是同一内容版本的可重建索引，不成为另一份可随意修改的真相。

### 2.2 对象、层次及保留策略

|对象|最小语义及层次|不可靠时的处理|
|---|---|---|
|document / section|根children有序；section按明确标题形成，可嵌套；章节属于section语义，不独立复制正文|无可靠章节证据则根下保留原顺序，不按关键词强行分层|
|heading / paragraph|heading保留原level（1–6及扩展），角色title/chapter仅有依据才设置；paragraph有runs与raw/span|未知标题为普通段落，候选和诊断置于正文外；不插“待审核”字样|
|list / list_item|列表容器、类型、有序起点/原marker；item有子段落及嵌套列表|原标号冲突保留原marker；不自动重编号改正文|
|image|已有资产ID/hash、alt、可选caption引用、原始尺寸、来源；排版尺寸属样式/规则|无图片字节时保留原引用/说明并给出能力诊断，禁止网络自动补图或静默丢弃|
|table / row / cell|有序行列、header标志、rowspan/colspan、单元格children及原始文本覆盖|未可靠提取形状则literal原表文本；不得凭竖线猜成错误表格；复杂合并先降级且提示|
|question / stem / option_group / option / answer / explanation|可选语义扩展；同一question明确拥有stem及完整option_group；答案/解析仅在有已提取内容和明确归属时建立|无法证明归属时普通段落/列表；不补答案、不依题号连续性串题|
|literal / unknown / formula|保留原raw与文字span；公式保留原LaTeX/字符，不执行未知代码|已有可靠公式图片可用原资产表示；暂不宣称OMML/Typst公式可编辑双向转换；无法忠实输出须明确能力冲突，不能丢公式|

`section/question/list/option_group/table` 等容器不重复计算自身text；叶节点拥有权威span，正文覆盖检查避免容器与叶子双计。题干可包含paragraph、image、table等通用对象，不创建另一套试题图片/试题表格协议。布局中的两列表格不是内容table，须在layout-plan中标记其为presentation container。

### 2.3 稳定ID、顺序及来源

- `artifact_id`、`revision_id`、当前片段locator继续使用。新增对象ID初次派生时以项目命名空间及“初次文字artifact ID + 稳定片段locator + 初始span + 初始对象类型”生成UUIDv5并保存，使相同输入重建可复现；这些是身份初始化信息，后续修订不重新按新span计算同一对象ID。不把题号、页码或数组位置当全局ID。原生引擎block ID只在task/page上下文中唯一，不能直接当全项目对象ID。
- 对象身份和对象内容哈希分离。同一对象明确的文字编辑保留ID并变更内容hash；拆分/合并分配新ID并记录replaces/derived_from。只有显式编辑事务或唯一、可证明的span对齐能继承ID；模糊匹配不能静默继承。初期全文Markdown重解析时，无法唯一对齐的对象生成新ID并记下旧关联未解析。
- 父children顺序是阅读顺序唯一权威，parent_id是可校验反向索引；不同时维护一份可独立变化的order。来源reading_order只作证据，不覆盖人工明确顺序。禁止孤儿、环、多父复用；同一资产可被多个image对象引用。
- `source_refs[]` 引用source artifact/hash、physical_page、原生block ID、region及坐标语义。正文`text_refs[]`引用稳定片段locator、选中文字hash和半开Unicode码点区间[start,end)；JSON保存码点，JS UTF-16必须显式转换；禁止字节/码点混用。
- 区分原件物理页physical_page、原件printed_label（可空字符串）、片段locator/显示位置、输出output_page。书上题号作为原文属性，不能用于来源定位。
- 来源region仅保留已知polygon/bbox、单位和原点；像素须有图片hash、width/height，PDF点须有page box、rotation。裁剪/旋转变换不全则geometry_valid=false，仍保留原坐标证据，不假装可映射到原图。此处仅设计数据保留，不实施点击跳转。
- 当前RapidOCR有输入图片像素四边形、输入尺寸/hash；pdf-text有PDF点框、page_size及原生顺序；远端文字引擎通常无统一框，由 `publish_results` 生成无坐标unsegmented块。统一的旋转/裁剪变换链尚缺。依据：`adapters.recognize`、`engine_worker.main`、`Projects.render/publish_results`。PPStructure原生探索记录不等于日常adapter已消费统一region。

跨页与多对象：同一页可有任意多个对象，各自引用同页source_ref；同一对象可引用多页。只有原生/人工证据提供页内文字区间时才建立 `page_slices`。仅知“涉及23–24页”的一个片段，必须保留为不可精确拆分的跨页对象；连续排版可整体输出，按页选取或严格一来源页一输出页应返回冲突或要求扩大选择及明确选择非严格策略，不能把全文复制到两页，也不能默认挂到23页。来源阅读仍可在两页入口显示“跨页整体”，保持已有边界说明。

### 2.4 少量拟议示例（全部合成）

下列为文档示意，不是已可提交的API载荷。hash用占位符；区间与text在第一例可核对。实际JSON Schema后续阶段提供。第一例覆盖结构完整性，第二例只解释跨页关系，第三例只解释配置边界。

```json
{
  "schema": "standalone-structure-v2",
  "project_id": "synthetic-project",
  "text_version": {"artifact_id": "text-v3", "sha256": "<text-sha256>"},
  "derivation": {"id": "struct-v1", "parser": "markdown-adapter@1", "annotations_sha256": "<annotations-sha256>"},
  "root_id": "doc-uuid",
  "objects": [
    {"id": "doc-uuid", "type": "document", "children": ["heading-uuid", "paragraph-uuid"]},
    {"id": "heading-uuid", "parent_id": "doc-uuid", "type": "heading", "level": 1,
     "raw": "# 示例", "text": "示例", "runs": [{"text": "示例"}],
     "text_refs": [{"locator": {"kind": "block", "id": "fragment-a"}, "range": [0, 4]}],
     "source_refs": [{"artifact_id": "source-pdf", "sha256": "<source-sha256>", "physical_page": 23, "region": null}]},
    {"id": "paragraph-uuid", "parent_id": "doc-uuid", "type": "paragraph",
     "raw": "正文。", "text": "正文。", "runs": [{"text": "正文。"}],
     "text_refs": [{"locator": {"kind": "block", "id": "fragment-a"}, "range": [6, 9]}],
     "source_refs": [{"artifact_id": "source-pdf", "sha256": "<source-sha256>", "physical_page": 23, "region": null}]}
  ],
  "coverage": {"fragment_text": "# 示例\n\n正文。", "syntax_ranges": [[0, 2]], "separator_ranges": [[4, 6]]}
}
```

raw/text_refs可覆盖Markdown语法；coverage中的syntax_ranges是其内部语法分类，不是重复正文。实现应由parser token明确标记syntax与分隔符，不能把所有标点/空白统统忽略；这里inline范围简化为raw整个block。

```json
{
  "id": "question-uuid", "type": "question", "children": ["stem-uuid", "options-uuid"],
  "option_group": {
    "id": "options-uuid", "type": "option_group", "children": ["opt-a", "opt-b", "opt-c", "opt-d"],
    "group_evidence": {"kind": "explicit-annotation", "text_sha256": "<text-sha256>", "operation_id": "annotation-uuid"},
    "labels": ["A", "B", "C", "D"], "membership_complete": true
  },
  "source_refs": [{"artifact_id": "source-pdf", "physical_page": 23}, {"artifact_id": "source-pdf", "physical_page": 24}],
  "page_slices": null,
  "diagnostics": [{"code": "CROSS_PAGE_WITHOUT_TEXT_SLICES", "effect": "strict-source-pagination-unavailable"}]
}
```

第二例是关系片段，option_group在实际objects中单独登记并经children引用，不能同时维护两份对象；所有实际source_ref还须带hash。没有上述可靠分组证据时，选项按普通list_item保存，即使看上去恰好ABCD。

### 2.5 修订失效与评论保护

|变化|保留|重新派生/失效|
|---|---|---|
|未改文字，仅换样式或分页|正文版本、结构ID与来源证据|layout-plan及输出页映射重算；旧导出不变|
|编辑一个已选片段|原件、原提取坐标证据、片段locator与已登记source_pages|该片段文本span、派生runs/标题/列表；包含它的题组、前后边界和跨页关系重验。未改对象只有依赖哈希一致才可复用|
|插删/重排、拆合片段|旧版本和其评论/回执；显式事务可保留来源片段关系|跨对象text anchors失效，新的父子关系及阅读索引重建；未证明位置的精确坐标禁止当修订文字坐标使用|
|历史恢复成新版本|被恢复版本正文与证据，原历史仍只读|新artifact/revision及结构绑定；不可把旧output_page直接沿用|
|解析器或语义规则升级|文字与原证据|新的结构派生ID/hash；不能原地升级旧结构或旧导出快照|

精确几何关联绑定原提取text hash；改字后相应geometry-to-current-text标为失效，不删除原框。来源页归属保留，页内精确锚点不能靠相似文字自动重激活。评论仍按原artifact/hash/locator绑定；新对象ID映射不改变旧回执，跨版本显示只能显式标“来自旧版”，不能自动附到相邻重排对象。现有保存/取消、幂等request、head冲突、失败草稿、文件/页切换保护不改变（`TextRevisions` 与现有工作台修订脚本）。结构不确定性用诊断和能力说明表达，不新增人工审核状态或导出前强制审核关卡。

## 3. 分离内容、规则、样式与分页

### 3.1 四类职责及接口边界（拟议）

|职责|输入/产物|允许配置|禁止承担|
|---|---|---|---|
|内容结构|已选正文与来源证据→不可变v2结构|声明式语义识别profile、显式标注；只有证据充分才分类|字体、列宽、输出页码；按书名写语义分支|
|排版规则|结构+解析后的样式→layout-plan|完整组选项单/双列、标题跟随后若干行、统一缩进、孤行、允许拆分的语义边界|重新猜题目归属、补正文、修改文字；任意用户Python/Lua执行|
|样式模板|版本化配置→effective-style|字体链、各角色字号、纸张、边距、段距/行距、列表缩进、表格/图片尺寸约束|题目/答案归属、来源页拆分、自动续页授权|
|分页策略|layout-plan+实际renderer→逐输出页映射及冲突报告|continuous/source-pages、显式有界压间距/缩字/续页|为了页数相等丢文字、把跨页未知对象冒充精确单页|

逻辑接口建议为 `derive_structure(text_version, source_manifest, annotations, parser_profile)`、`resolve_styles(template, reference_style_mapping)`、`plan_layout(structure_ref, rules_ref, effective_styles)`、`render_and_validate(plan, pagination_policy)`。这些是内部边界，不要求四个服务或四套存储；初期一个进程模块即可。HTTP沿用现有export/修订接口，仅加版本化可选structure/rules引用；旧请求适配器固定legacy行为，不默默改变旧模板输出。

结构派生可本地可重复运行；渲染器只收结构/计划，不读取任意书名关键词解析正文。新书通常新增JSON preset/profile，不新增生成器代码；不支持的新内容对象、原生表格/图片能力、输出后端才需有版本的代码扩展及全矩阵回归。

### 3.2 完整组选项布局

先认定归属，再决定布局。group_evidence可来自：已绑定hash的人工标注、具有可靠父子归属的提取结构，或经过固定边界测试的保守解析器（明确题干起止、组边界、全部成员覆盖、无歧义标号）。**相邻AB/CD、序号连续或字符宽度本身均不能证明归属。**缺失选项、重复标号、交错题目、答案夹入、两个未标边界的相邻题组，均降级普通列表并保留原文。

整个option_group只作一次决策：

1. `one-column` 总是所有选项全宽；`auto-uniform` 先基于**最终有效字体、补充字体、字号、缩进、格宽和段落属性**测量所有选项。
2. 仅当全组都满足两列上限，选择统一两列、按原成员顺序逐行（A B / C D）输出；任一长选项不满足则**全组单列**。禁止仅AB合成两列而CD另排单列。
3. 奇数成员最后一格留空但不造选项；非ABCD标签只在结构提供可靠组时支持，不在renderer硬编码字母数量。多选与单选布局可共用，答案正确性不在规则职责。
4. 实际Word渲染后若不符合容量/组布局，整体回退单列并记录决策；不能局部换行后不重验分页。测量使用相同字体链，Story估算仅作预筛，最终以实际LO结果为证据。
5. 题干—首选项可设置软keep；整题短且实际能放下才允许整体keep，不把长题和所有选项永远绑成大块。组可跨页时仅在选项成员边界拆分；单一超长选项允许段内正常分页，诊断注明。

### 3.3 优先级与冲突处理

从不可覆盖约束到可继承默认：

|层|规则|
|---|---|
|0 内容与来源约束|不丢、不补、不改正文；真实映射；显式格式选择；字体覆盖与正文完整检查。任何配置都不能关闭这些检查|
|1 显式导出策略|本次选中文字版本、范围、分页模式、压间距/缩字号/续页授权及下限；与类型硬约束冲突即报错，不以“用户配置”掩盖缺映射|
|2 明确对象语义及规则包|角色/标题level/组归属来自版本绑定结构；规则可选择布局和软keep；来源强分页优先于软标题跟随，冲突记报告。若声明不可拆硬对象放不下则返回冲突|
|3 显式样式覆盖|模板中角色覆盖 > 经明确角色映射的Word导入值 > 角色继承链 > 通用默认。font.size/纸张等每属性只有一个最终值|
|4 后端实现|只执行effective-style及layout-plan；不得再套一份独立默认或随意覆写段落/表格|

分组与排版规则相互独立：style的option_columns旧字段由兼容适配器转为legacy rule；新版样式不存该规则。具体字号/缩进由样式给出，规则只选择应用哪个角色及合法拆分位置，不能再硬编码一套11pt。内联粗斜体属于内容表达，覆盖样式默认但不代替角色层级；缺字run字体由字体解析链决定，导入参考字体不能覆盖其覆盖性结果。

应输出属性来源解释，例如“Option.left_indent=0.6cm：模板角色覆盖”“Heading2.keep_with_next：规则soft，被source-boundary释放”“正文11pt：模板，未启用缩字”。字段单位统一（字号/间距pt、纸张/边距mm、行距有明确multiple/exact/at_least），适配旧cm参数时显式换算，不隐含混算。行距下限须结合实际字形/公式/图片行盒检查，不能只比较字号。

### 3.4 拟议配置片段及分页行为

```json
{
  "rules": {
    "id": "general-flow", "version": "1.0.0",
    "options": {"layout": "auto-uniform", "require_complete_group": true, "max_columns": 2},
    "heading": {"keep_with_next_lines": 2, "strength": "soft"},
    "paragraph": {"widow_lines": 2, "orphan_lines": 2},
    "question": {"keep_whole": "only-if-fits", "split_at": "member-boundary"}
  },
  "style": {
    "id": "general-a4", "version": "1.0.0",
    "page": {"width_mm": 210, "height_mm": 297, "margins_mm": [18, 18, 18, 18]},
    "roles": {"body": {"size_pt": 11, "line": {"mode": "multiple", "value": 1.15}}, "heading.2": {"size_pt": 13, "space_before_pt": 6}}
  },
  "pagination": {
    "mode": "source-pages",
    "adaptation": {"reduce_spacing": false, "shrink_font": false, "minimum_body_pt": 10, "step_pt": 0.5},
    "allow_continuation": false,
    "fill_page": false
  }
}
```

示例分四种职责中的三类配置，结构引用由导出请求另给；不是新增可执行模板schema。实际首期规则只暴露后端能执行并验证的孤行能力；若只能提供Word布尔widow_control，不能接受“2/3行可精确配置”却不落实。不得接受任意代码模板。

连续模式按自然流动，不把physical_page当强制分页；来源页索引只追溯。来源模式将已有明确page_slices/片段按物理页组装，保留空页事实，不填补未识别页。“全部”是所选文字版本的全部已有内容。指定未登记页返回无记录；映射缺失拒绝按原件范围，仍允许连续全文。跨页未细分见2.3约束。

来源分页溢出顺序固定并记录：原设置渲染 → **仅若授权**有限缩减可压段距（不压标题至与正文难区分、不改行距下限） → **仅若授权**按指定步长缩字至角色下限 → 只有显式允许才续页。纸张、边距和字号不能偷偷变；不自动放大字号、拉段距去填满稀疏页。页尾留白不必消除，但过大留白须能解释为来源边界、keep规则或原内容稀疏。所有尝试记录来源页、对象、参数、实际页数、变动原因；无解返回具体冲突，不截断。

最终 source_output_mapping 改为来源页/对象slice→输出页+对象span；多对多，不要求“页码数量相等”就是成功。图表合并DOCX须正确复制关系部件、图片、编号与样式，现有仅复制body XML的来源组合并不能直接承诺支持新图片/表格（`source_pagination.generate_source_pages`）。先实现关系感知合并，或在单一DOCX中设置来源边界后实际渲染验证，不能把这项风险藏在结构扩展里。

## 4. 输出工具比较与推荐

官方资料核对日期2026-10-12。本轮只文档评估，不安装/运行Pandoc或Typst，不把潜在支持等同当前实测。

|维度|现有 python-docx → LO → PDF|Pandoc + reference.docx → LO → PDF|Typst PDF候选|
|---|---|---|---|
|样式复用|可生成/应用Word样式；当前有限导入，需统一优先级|参考Word样式与文档属性可复用；仍需语义→样式映射|set/show和模板函数；需单独映射样式，不能直接消费Word参考样式|
|结构表达|可编辑段落/列表/图片/表格，应用层要实现语义适配|通用AST覆盖常见文档，特殊题组仍需过滤/适配|原生标题/列表/表格/图及布局对象；试题语义仍由应用负责|
|分页控制|Word keep/断页/孤行等，最终以LO排版；现有验证与溢出机制可复用|reference样式可带分页属性，但复杂来源分页、整组选项仍需受控后处理及实际渲染|pagebreak、可拆块及标题sticky可表达控制；同样要实测并禁止clip截内容|
|中文字体|固定文件/补充链/嵌入及诊断已有；参考字体需落实到实际文件|可设置Word字体/参考样式；缺字追溯和嵌入仍需接现有检查|有字体优先列表及fallback；中文可选字体，但需同样固定字体版本并验证|
|可编辑Word|主输出能力|原生DOCX输出|官方导出格式中无原生DOCX；不能作为本需求Word主链替代|
|Word/PDF一致性|PDF由同一Word实际转换，当前最可控；仍受不同桌面Word环境影响|同样经LO可维持此原则；不用另起PDF引擎追求同版|与Word两套排版器，无法默认同页/同换行；只能明确独立PDF变体|
|维护成本/迁移|继续有应用层工作，但可复用发布、预览、字体及验证|新增二进制/AST/过滤器和版本锁定；有助通用内容，不能自动解决题组或来源映射|新增语言、字体测量与独立验证体系；PDF场景有价值，双链维护成本高|

官方依据：python-docx 的[样式使用](https://python-docx.readthedocs.io/en/stable/user/styles-using.html)及[分页属性](https://python-docx.readthedocs.io/en/latest/user/text.html#pagination-properties)说明样式继承和 keep_together/keep_with_next/page_break_before/widow_control；仓库固定1.1.2，在线文档展示1.2.0，本设计不顺手升级依赖。LibreOffice 的[转换过滤器](https://help.libreoffice.org/latest/en-US/text/shared/guide/convertfilters.html)说明实际文档转换入口，不能据此推论与所有Microsoft Word版本完全相同。

Pandoc 的[reference-doc](https://pandoc.org/MANUAL.html#option--reference-doc)说明参考文档的正文被忽略、样式和文档属性被使用；[过滤器](https://pandoc.org/filters.html)用于AST变换。因此reference.docx不是扫描件复刻工具，题组/来源关系不会凭参考样式自动产生。拟议AST适配只作为后端可替换边界，不把Pandoc AST升级为项目另一份正文权威。

Typst 的[字体选择](https://typst.app/docs/reference/text/text/#parameters-font)、[块拆分/标题跟随](https://typst.app/docs/reference/layout/block/)、[手动分页](https://typst.app/docs/reference/layout/pagebreak/)以及[导出概览](https://typst.app/docs/web-app/export-and-preview/)支持其作为PDF候选；使用这些能力能改善多少仍属本需求下待验证判断。

**推荐渐进保留现有链**：先消除重复猜结构、统一规则和有效样式，恢复可靠题组及缩进；统一结构接Renderer适配器后，才用固定合成样本对Pandoc的维护收益做限时对照。只有普通内容适配明显更省且证据合格，才替换部分通用Writer；不整体重写项目和修订系统。Typst留作后续明确选择的独立PDF输出研究，不在本次迁移主线启用，更不把Typst PDF作为Word预览。主风险在语义/规则混杂，换排版器不会自动修正错误归属。

## 5. 可独立验收的迁移阶段（未实施，均需后续授权）

每阶段提交可单独回滚；协议与开关均须显式版本化，不能对旧项目启动时批量重写。回滚包括恢复代码路由/默认规则指针，**不删除新导出或覆盖任何旧版本**。本文不是执行这些阶段的授权。

|阶段|修改范围、接口/数据变化|兼容/回滚|验收证据与旧逻辑处理|
|---|---|---|---|
|A 结构契约及只读适配|新增v2校验器和v1/manual/markdown适配器、正文coverage与依赖hash；内部derive入口，现有HTTP及输出不变|派生结构写新诊断artifact，旧资源字节不变；禁用派生开关即可回退|同版本重复派生一致；未知块完整保留；源文件/hash和原修订回执不变。保留现有解析器，不接新生成器|
|B 稳定身份与修订依赖|复用save_text_revision事务追加结构ref、对象沿革和失效索引；结构标注用单独绑定hash操作，新增可选接口/请求版本|旧客户端可继续Markdown编辑；旧locator/评论保持；新结构不支持时回退文字阅读，未知字段不传给旧严格API|只改指定片段，相邻不变；拆合ID和跨页无误配；保存失败无半发布、草稿保护；历史恢复新版本。淘汰以位置/文字hash冒充稳定身份的新增用法|
|C 规则和样式解析|规则包版本、角色映射、effective-style解释；旧v1–3模板经legacy adapter，新模板显式声明规则版本；导出请求可选rules_ref|默认旧模板走legacy；新路径错误切回legacy preset，旧模板不被改写|同组长短选项统一布局、缺分组普通列表；导入样式优先级及连续/来源模式一致。新路径替换邻接AB/CD配对与标题关键词猜测；旧路径暂留仅兼容|
|D 通用Writer与有限分页|Renderer消费v2/layout-plan，先段落/标题/列表，再原生图片/简单表格；关系感知DOCX组装；分页授权及冲突结构化，增加格式能力版本|缺能力明确保留/报冲突，不能静默切后端；旧历史导出不重做；关闭新Renderer路由回滚，新项目仍可查看/导出已有旧格式|实际Word/PDF全文/资产覆盖、逐页来源与溢出、keep释放原因、字体嵌入；新路径移除导出现场structure_ocr和二次Markdown解析，保留离线旧快照兼容|
|E 跨文档推广与清理|固定矩阵通过后，新导出默认新路径；按明确新模板版本迁移，不批改旧模板；评估可选Pandoc适配器，不默认引入Typst|开关恢复legacy新任务入口；新/旧快照都有版本reader；导出不可变|至少三类授权真实文档及两套不同试题样本通过“不改生成器”门槛，才停止为legacy增加特例。最终移除活跃导出中的旧邻接布局/重复猜结构；旧数据reader、历史原文件与旧接口适配保留|

新导出快照在现有字段上追加：structure_id/hash/schema、parser/profile版本、annotation_hash、rules_id/version/hash、effective-style/hash、字体链/实际文件hash、renderer版本与镜像/依赖标识、输入资产hash、逐页layout-plan/映射、所有适配授权/尝试结果。旧任务缺这些字段显示“历史记录未提供”，不补造。重复导出创建新tid；缓存只命中全部依赖，取消/失败不发布部分替代正文。

应保留：上传分析、引擎选择与配置、项目改名/回收/恢复、来源质量筛选、错误筛选、左右独立阅读、修订/历史恢复、评论JSON回执、导出选文字版本、不可变发布、原件下载、字体补充和真实Word预览。阶段回归覆盖既有相关测试：`test_standalone_http.py`、`test_review_r2.py`、`test_text_revisions.py`、`test_template_exports.py`、`test_document_fonts.py`、`test_document_pagination.py`、`test_startup_resource_preservation.py`及来源阅读/工作台浏览器脚本。只保留原测试数量没有意义，还要逐条核对来源与内容。

NAS、RAG、OpenClaw集成、重新OCR、付费模型、段落点击定位和疑点标亮不在此迁移范围。坐标字段保留不构成提前开发定位功能。

## 6. 跨文档固定验收设计

### 6.1 样本矩阵与真实缺口

以下为拟建立的固定样本清单，非本轮已新建或实测。每项登记sample_id、许可/使用边界、原件hash、选中文字版本hash、规则/样式版本、预期结构、来源映射、预期降级和私有/公开证据路径；后续内容变化增版本，不随测试随手改预期。

|ID/类别|固定内容与边界|合成验证重点|真实样本状态|
|---|---|---|---|
|A1 普通文章|多级标题、中文/拉丁混排、引用/列表、长段落，约8–12页|标题不凭关键词换层；正常分页/缩进/孤行|缺授权真实文章，须后续提供或选有明确许可的材料|
|A2 书籍章节|章/节/小节、跨页段落、印刷页码与物理页不等，约10页|跨页对象、章节树、连续与来源模式区别|除现有同册试题背景，缺另一真实书籍章节，不算跨书已测|
|Q1 单选/多选|整组短项、一个长项、全部长项、五项/奇数项、全角标号|全组统一1/2列；一组不影响另一组；文本/标号保留|已有肖1000授权样本；上一轮20/50/178证据仅代表这一本，需用新路径重验|
|Q2 混合题型|填空、判断、材料、分析、答案/解析混排、题号重启，约10–20页|可靠归属才语义化；答案不补全；跨页题不猜拆|缺不同来源试题册及含答案解析的授权真实样本|
|R1 图表报告|标题、嵌套列表、两张图、简单表、长单元格、合并单元格|图片hash与大小、单元格顺序、表头重复、复杂表降级|缺授权真实图表报告，不能把Word布局表格当报告实测|
|B1 密集/稀疏|近容量页、只有标题和短段页、超长一段/单元格|允许合理留白；溢出明确；不默认缩字续页|肖1000已有密集与章节页；不是其他类别真实替代|
|B2 不明确结构|正文里的A/B、重复A、缺C、两个题组交错、AB/CD相邻却不同归属、编号列表像题号|拒绝混组；普通列表保留；诊断不入正文|合成边界优先；真实问题页只读取证后授权纳入|
|B3 来源与版本|一页多片段、片段跨两页无slice/有slice、无映射、逆序、失败空页、历史修订|无复制/漏片段；范围“全部”语义；历史及评论稳定|已有来源阅读合成证据，需绑定新结构重跑；真实第145页空文字仅验证失败保留|
|B4 字体及包|⸺/📖、中西文、组合字符、补充链外字符、图片关系/编号冲突|精确编码和位置报告；字体嵌入；DOCX合并关系正确|此前两字符真实位置已知；其他字体边界是合成，不声称真实覆盖|

后续可使用公开许可文章/报告补缺，但必须记录具体许可和hash；没有真实样本时该类别标“未验证”，不得用合成通过替代跨书结论。公开仓库只存合成/脱敏文本与图，真实样本截图进入私有包；脱敏后的文本也不自动等于排版等价样本。

### 6.2 每项同时检查五个维度

1. **正文完整**：权威Markdown字节hash不变；raw spans覆盖、不重不漏；语法标记、分隔符和正文字符分开核对。DOCX对象/单元格遍历和实际PDF阅读顺序与结构coverage核对；保留有意义空白，不能只去所有空白就判完整；图片资产hash/数量、表格行列合并及文本、公式降级也进入清单。评论、质量和诊断不出现在正文。
2. **视觉层次**：真实Word转PDF后，标题层级、缩进、组布局、长选项、图表大小、页尾keep、过紧/重叠检查；固定代表页同文档前后截图，等待加载完成。人工评价“清楚/可接受/有阻碍”，附具体对象/页与原因，不引入产品审核状态。
3. **字体**：模板和实际字体文件hash、补充字符/位置、Word内嵌许可、PDF嵌入和字形，缺字明确失败。中文主字体选择与字号效果单独比较；不能以补字成功代替阅读效果合格。
4. **分页**：continuous与source-pages分别跑；来源模式还跑不适配、授权压距、授权缩字到下限、明确续页四种。稀疏页不要求填满；容量不足具体来源页/对象/页数/尝试，禁止自动改变授权。每来源组与最终输出页内容逐页核对，不能仅总页数一致。
5. **来源关系与编辑**：同页多对象完整保留、跨页未知slice明确冲突、物理/印刷/片段/输出页区分；编辑一个片段不改邻段，锚点失效如实表示；历史恢复/导出选版本正确；评论不因对象顺序变动重绑。范围缺映射或无内容不能静默退全文。

测试分层：合成结构golden与属性测试 → 旧项目只读适配/原文件hash → 新旧路径影子对比（差异不自动改正文）→ 合成异常写入/取消/重试/保存失败 → Worker实际Word/PDF及浏览器 → 授权真实样本只读效果核对。真实项目不做破坏性写入或重新OCR；模板/规则试验用新版本，不覆盖已发布版本。

后续证据需包含Linux/LO/字体/镜像/依赖版本与耗时，Word/PDF实际文件、逐页映射/冲突报告、effective-style解释、正文coverage、私有前后截图及授权来源清单。桌面Microsoft Word如果未测试应单列，不用LO通过冒充；面板关闭/编辑/历史/导出及窄屏属于既有工作台回归，不重设计界面。

### 6.3 核心“不改生成器”验收门槛

冻结Renderer和已支持内容类型的代码提交，再由配置人员新增A1/A2/Q2/R1中的普通样本：只能选择/新增声明式profile、规则包、样式、Word角色映射及语义标注，不能改Python/JS或添加书名判断。记录每次配置调整、耗时和结果。

成功：在已声明支持的类型内，正文/来源/字体全部硬门槛通过，视觉无阅读阻碍，组布局规则可解释，分页尊重授权；至少普通文章、两套不同试题、含图表报告的真实样本达到可接受效果。尚缺真实材料的类别不算通过。

失败：普通新书每次都需要修改正则或补题号例外、导出阶段重新猜归属、混组、截断/缺字、隐式缩字续页、无法解释的样式覆盖。若因确实新类型（如复杂公式、浮动版面）失败，记录能力边界和原文降级；只有新增对象/后端能力时才允许代码扩展，并要求矩阵全回归。不能降低原断言或修改样本正文来“通过”。

## 7. 少量需用户审核的取舍

|取舍|推荐|代价/替代|
|---|---|---|
|正文权威|继续Markdown artifact权威，结构派生+绑定hash的语义标注；图片/表格编辑以后经统一修订事务扩展|稳定、保留现有修订；复杂内容的可视编辑会晚于结构输出。若现在改JSON全文权威，迁移与双向编辑成本显著增加|
|默认排版|普通文档默认continuous；原件一页对应一页由用户显式选择，稀疏页允许留白；所有适配默认关闭|来源模式可能报冲突，但不悄悄牺牲字号。旧模板仍legacy行为，新版本才改默认|
|工具路线|先现有Word→LO主链；Pandoc仅后续对照验证，Typst保留独立PDF研究|保留Word/PDF同源和已有能力；短期不能获得Typst全部PDF排版特性|
|真实样本与最低字号|先补齐另一试题册、文章和图表报告授权；正文下限由模板/用户明确选择，建议中文正文默认10pt、标题保留独立层级|不是对所有文档承诺10pt可读；特殊用途需另定，未经授权不自动缩字|

本轮不等待这些取舍就实施。审核可按上表回复接受推荐或指定例外；下一阶段范围需另行确认。本文提交后停止，不部署、不推进段落定位。
