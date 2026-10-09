# R8 工作台、Word样式导入与原件分页

基于R7增量，不接生产、OpenClaw或识别后端。原件、旧Markdown、修订、评论、模板和既有产物均不覆盖。

## 工作台

每次进入默认收起完整工具、评论和技术详情；两侧文件、页码输入、总数、翻页、缩放保留。位置分别标为原件物理页、输出页、文字片段。展开、专注和左右滚动沿用R6/R7，无自动比例同步。原图评价为布局内最高180px的滚动面板，不盖正文。

右侧“按原件页定位”只读当前产物登记的source_page/source_pages，物理原件定位也可直接使用。单候选通过R7导航保护；多个候选须选择，没有映射、没有结果或被评论/错误筛选排除时明确提示，旧内容不冒称新页。原图质量只过滤原件页，“定位右侧对应内容”主动查关联。未保存修订仍须保存/放弃/取消。

## 模板与Word导入

仍使用同一catalog/published/drafts。JSON载入不是保存，未保存不能预览或发布。保存返回实际ID/版本，选择器同步；不可覆盖旧版本。响应式分组、厘米/磅/倍数单位、错误字段提示。复杂参数和原始JSON折叠。

新增兼容schema_version=3，在v2字段上增加word_styles，可选import_source。word_styles包含section与paragraphs：纸宽高、四边距、页眉页脚距离（cm）；Normal、Title、Heading 1–3、Option、Footer的字号（pt）、加粗/斜体、段前后（pt）、左右/首行缩进（cm）、line_mode与line_value。multiple为倍数，exact为固定磅数，at_least为最小磅数。固定行距明显小于已知字号拒绝。Normal应用于语义正文样式，显式Option优先；字体本版统一选择已安装服务器字体。全部接受设置实际应用到DOCX，PDF由该DOCX导出。schema1/2及包内published 1.0.0保持。

导入仅无宏DOCX/DOTX，20MiB、2000条目、展开64MiB、单项16MiB及压缩比保护；拒绝越界/加密路径、宏/ActiveX、DTD/实体。解析OOXML与样式继承，不执行内容、不访问外部关系。多节不同须选节；中西字体及主题字体原始记录保留，但本版必须显式选择统一服务器字体，不承诺原样还原或嵌入。实际正文缺字在生成时检测。

分栏、表格样式、浮动图、编号样式、页眉页脚内容、装订线、对称边距、任意直接格式等不完整支持，提取报告明确列出。PDF参考样张不能导入样式。原导入文件与report.json留在私有模板库imports/UUID；草稿关联import_id、原SHA、选定节与字体确认。生成项目复制导入来源及报告到templates/import-UUID，保存配置快照。外部链接不会在服务端解析或执行；用户下载原样本后的客户端行为不在本轮验证范围。

接口：POST /api/template-imports?filename=sample.docx（二进制流）；POST /api/template-imports/:UUID/select（section_index、font_family）；GET其/report。随后沿用/api/templates保存、预览和发布。私有模板原件不进入Git。

## 保留原件分页

POST /api/projects/:id/format新增pagination：mode=continuous或source-pages、font_fit（默认false）、minimum_font_pt（8–16，默认9）、allow_continuation（默认false）。项目详情可选择，任务记录独立快照；修订后保存排版沿用项目选择。不是修改公共模板。

source-pages只接受完整、哈希一致的逐段映射稿，各片段source_page须在已登记原件范围，来源顺序不得倒退。同一来源页多个片段聚为一组；不补未选择的原件页。已选空白片段保留一空输出页，缺映射稿拒绝。正文不新增项目大标题、来源说明或评价；用户原文自身内容不擅删。

每组由现有python-docx生成，实际LibreOffice渲染。最多尝试原样、段前后降到0、用户明确开启的字号下限三档，不无限搜索。字体下限不高于正文字号，页码不随正文缩小。仍溢出则任务失败并指出来源页和实际输出页数，留下pagination-report.json；显式允许续页才继续。实际文件内容不裁切/删减。

有限段落/表格合并到一份DOCX，保留各组适配后的直接格式；PDF统一从此DOCX导出。最终逐页正文与单组实际渲染逐页比对（仅忽略布局空白及生成的页码），不是只比较总页数。检查文字及几何，来源输出映射写入结构与分页报告，并登记在Word/PDF实际预览页上。映射验证失败不发布成功产物。真实看版仍必需，自动结果不能证明任何模板/阅读器全通过。

连续模式也统一由DOCX导出PDF，保留原内容结构、短题/长题规则；不会调用OCR。沿用总生成60秒及现有资源，不承诺1000页排版或任意源页都能适配。每组多次Office启动有成本，适合显式小批次；超时保留文字稿/诊断，无静默扩限。

## 使用、迁移与回退

选择已发布模板→项目选择已有文字稿与分页模式→仅重新排版→分别检查任务、Word/PDF真实预览和分页报告。没有明确对应关系时保持左右独立定位。在线编辑仍R7接口；离线只读，只含已缓存原件页，不能离线生成缺页。

旧项目不搬文件、不改ID/正文/评论。新增样式元数据只关联新模板、新任务和新产物。开发回退：无活动任务时使用旧提交启动独立开发服务，保留store；v3模板需要R8读取，回退后选择旧v1/v2版本，不能覆盖或删除新结果。生产不在本轮操作范围。

行距解释依据[python-docx官方说明](https://python-docx.readthedocs.io/en/develop/dev/analysis/features/text/paragraph-format.html)：auto的line单位为240分之一行，exact/atLeast为twip。实现不混换固定磅数与倍数。
