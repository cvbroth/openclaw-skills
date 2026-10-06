# OCR 文档生成小样本开发

本分支从录音流程提交 `364d4d6431e63bd0244d4bce780b1b19458485b6` 增量开发，保留录音 Skill。仅处理用户授权的原 PDF 第6–10页及对应旧 OCR；不部署、不处理全册、不修改生产容器/配置/镜像标签。

## 实现与输入

- `src/nas_filetools/document_sample.py`：保守结构恢复、来源片段/疑点/修订审计、python-docx 模板、PyMuPDF Story 排版及实际文本/几何检查。不是新工具入口或自动办公平台。
- `scripts/document_sample_pipeline.py`：真实隔离 FileTools 核心任务、已有 OCR file_id 复用、单输入受限 Python、产物发布及 artifact_path 取回哈希检查。
- `scripts/render_document_sample.py`：LibreOffice 实际渲染 Word，核对导出 PDF 与 DOCX/另一 PDF 内容顺序、A4/字形/裁切，并生成逐页图片供人工看版。
- `tests/fixtures/document_sample/ocr.md`：合成材料，覆盖章节题号重置、正文数字、扫描断句、①②③④、跨源页、选项缺失及截断。用户原册/旧 OCR/核对截图/产物只留 gitignored runtime，不上传 GitHub。

正式脚本仅使用 `Path(os.environ["FILETOOLS_INPUT"])`。已有 OCR 产物从真实回执取得 file_id，调用 `filetools_register({file_id})` 或 `files/select(file_id)`，再用返回 attachment_id。脚本不读取另一任务缓存、Gateway 普通路径或原 PDF。此前 FileNotFoundError 是输入路径硬编码问题，没有大小/内存限制的证据。

多来源核对先在已授权能力范围内独立读取资料；整理成一个业务 JSON 输入包，再登记为本次输入。包包含 `raw_ocr`、`margin_evidence`、`reviewed_edits`、`review_notes`。修订必须精确绑定 page/line/original，提供 replacement 列表、verified:true、reason/reference。可拆分误并的选项或恢复核实过的漏行；原文在每个片段和审计记录中保留。生成器验证绑定关系，**不验证提供者的图像判断**。位置证据和重复边界证据逐项保存；未知结构原文保留并列疑点，不能补造缺选项。

## 模板与独立环境

复用固定 Python3.12.10、python-docx1.1.2、PyMuPDF1.25.5，未增加依赖。`DEFAULT_TEMPLATE` 集中配置字体、字号、行距、段距、A4/2厘米边距、缩进、页脚及分页阈值；调用可覆盖已知键，未知参数拒绝。没有按题号或原页码写分页例外。Word/PDF 共用有序段落内容，分页分别实现：

- Word 使用真实 keep_together/keep_with_next/widow_control 属性。短题只在本题内有限绑定，到 Source 即结束；长题干可拆，原生孤行控制保留至少两行开头。短题干跟随后继段，短选项不拆，末选项与来源绑定；长选项保留可拆属性。短题分类使用固定字体的 Story 高度作为保守估计，并非提前得到 Word 的实际高度；最终须以真实 Word 渲染核验。
- PDF 使用 Story.place 得到的实测高度，短题（不超过可用页高30%）剩余空间不足时整体移页；长题逐语义块流动，新题起始保留至少两行所需空间。短题干与有界首段保留在一起，短选项完整放置；长末选项按实测两行尾部拆分呈现流，与 Source 作为有界尾单元，语义文本仍为同一个原选项。标题预留后续内容空间。没有声称支持 CSS break-inside/widows/orphans 等未实测参数，也没有拼原始PDF对象。

部分为 Heading 1、章节/导论为 Heading 2、题型为 Heading 3，学科名使用独立 Subject 副标题；全部黑色，首部减少间距。正文来源仅为“原PDF：第…页”，OCR行号/修订依据/完整片段映射仍在原审计文件。Word 页脚为 PAGE 域，PDF 使用成熟 Page 文本接口添加“文档第 N 页”，与来源区分。没有一题一页或按原PDF机械分页。

通用验证模块 `document_layout_checks.py` 将实际渲染文字映射到各段和页面，核验短题、两行开头、短选项、来源、标题、黑色文字和文档页码。`compare_document_sample.py` 精确比较上版题干/选项/顺序，仅允许标题样式、来源展示及页脚的明确变化；同时要求原OCR、structured.json、issues.md字节一致。所有用户审计和逐题位置证据仅留 runtime。

PyMuPDF Story 支持 HTML/CSS、Archive 字体资源及自动分页；使用其成熟排版实现，不拼原始 PDF 对象。参见 [官方 Story 文档](https://pymupdf.readthedocs.io/en/latest/story-class.html) 和 [字体文档](https://pymupdf.readthedocs.io/en/latest/font.html)。

已有测试镜像没有 LibreOffice 和可用于 Word 的中文系统字体。本轮单独构建 `deploy/Dockerfile.document-test`，仅安装开发渲染器/fontconfig，并将固定 PyMuPDF 自带 Droid Sans Fallback 字体放入该开发镜像。PDF 显式嵌入相同字体并预检全部字形；Word 指定字体但不嵌入，用户电脑未安装该字体时可能替换，尚未验证用户端 Microsoft Word。LibreOffice 的 Debian 包版本随镜像构建仓库解析，不宣称完全可复现；实测版本记录在本轮报告中。生产是否提供相同字体/渲染器未核查，不自动安装。

构建前核对本机 Docker daemon 与镜像；示例为本轮独立标签，不能拿生产标签代替：

```bash
docker build --pull=false -t filetools-document-test:20261006-364d4d6 -f deploy/Dockerfile.document-test .
```

本服务器既有下载代理只监听宿主机回环地址，普通构建无法连接。实际依赖准备使用了 `docker build --network host --build-arg http_proxy --build-arg https_proxy`；只用于开发镜像获取 Debian 官方依赖，不记录代理值、不绑定端口、不调用生产服务。构建网络与处理隔离不同，勿将此参数用于样本处理。初次直连 HTTP 构建过慢主动取消，传代理但未使用宿主网络的构建失败；不记为环境准备通过。

样本生成使用已有录音开发镜像，单独将固定字体开发副本只读挂到模板字体路径；渲染使用新增文档测试镜像。处理阶段使用 `--network none --read-only --cap-drop ALL --security-opt no-new-privileges --cpus 2 --memory 4g --user 1000:1000`，仓库只读挂载到 `/opt/nas-filetools-check`，仅 runtime/document-sample 挂载为 `/sample` 可写；`/tmp` 独立 tmpfs8g（容量检测所需，内存上限仍4GiB）。无端口/生产目录/docker socket挂载。设置 `PYTHONPATH=/opt/nas-filetools-check/src`，工作目录为只读源码根。镜像 Python 入口执行：

```text
scripts/document_sample_pipeline.py --root /sample --stage extract
scripts/document_sample_pipeline.py --root /sample --stage generate
scripts/render_document_sample.py --delivery /sample/delivery --output /sample/rendered
scripts/document_sample_pipeline.py --root /sample --stage report
# 后续分页报告使用 --report-name DOCUMENT_PAGINATION_REPORT.md（开发CLI参数，不是工具参数）
```

extract 只接受预先合法制作的5页 PDF 副本，其引擎页码仍为1–5。`source-map.json` 和单独 mapped-ocr.md 记录与原页6–10的映射；不篡改引擎 sources。重新 OCR 原稿另存，生成阶段优先读取用户提供的旧 OCR 输入包。不能因 `/root` 不可读就提升权限或扫描缓存；本轮用户自行提供工作区旧样本。

## 验证与交付边界

固定PyMuPDF出现预览前缀漏显，逐页独立进程亦未完全消除；深层原因未定位。当前栅格验证使用独立Poppler pdftoppm引擎，保留MuPDF异常与交叉渲染证据，不从文字/trace完整推断视觉通过。分页改进轮只为独立开发验证镜像补充poppler-utils（实测22.12.0-2+deb12u3），生成依赖/沙箱限额不变。缺少该程序时明确失败，不伪造预览。

正文恢复先逐题对照原页，再运行 DOCX/PDF 内容顺序和几何校验，最后实际渲染并人工看逐页图片。存在/退出0/非空不能证明正确。Word 导出的 PDF 在固定 PyMuPDF 下曾返回空 dict blocks；独立渲染验证使用 [get_texttrace 官方绘制轨迹接口](https://pymupdf.readthedocs.io/en/latest/functions.html#Page.get_texttrace) 并要求非空，逐字检查缺字和矩形，避免空几何检查误报通过。

validation.json 是生成器自动检查；rendered/render-checks.json 是独立 Word/PDF 渲染检查，两者均不代替人工原页核对。

FileTools 发布后由 status 获取 job_id/artifact_id/file_id，通过 files/artifact_path 返回真实 Gateway 开发路径、bytes/SHA，再取回核对。delivery 目录为这些真实发布产物的哈希核对副本。普通 preview 路径不冒充发布附件；本轮没有真实 OpenClaw/QQ message 成功回执，不声称送达 QQ。没有调用永久 files/save 或知识库导入。

初版结果见 [样本验证报告](DOCUMENT_SAMPLE_REPORT.md)；后续分页、模板与 Skill 改进见 [分页改进报告](DOCUMENT_PAGINATION_REPORT.md)。后续轮次只运行 generate、render、compare、report，不重新执行 extract；继续沿用已核对输入。全册和生产部署均等待用户另行确认。

分页改进轮的验证镜像从现有 `filetools-document-test:20261006-364d4d6` 派生为 `filetools-document-validation:20261006-pagination`，仅安装poppler-utils；后续重建开发Dockerfile亦包含此渲染依赖。上述旧镜像构建及OCR段落是初版记录，不代表本轮重建或重新OCR。

## 跨阅读器差异后的验收修订

前述单Poppler检查不足以完成跨阅读器视觉验收；出现差异时保留确切哈希、系统、版本和倍率，不能以提取/trace正常归为预览异常。当前生成器在全部Story/页脚后原生subset_fonts并完整去重压缩保存，不增加生成运行依赖，分页策略不变。

新增 scripts/check_pdf_readers.py：独立PDFium/Poppler/MuPDF实际逐页栅格（PDFium scale=1.7）、字体流诊断、逐字像素遗漏候选与有序搜索文字比较；缺依赖明确失败。JSON明确人工看版仍必需，像素阈值不能证明所有平台兼容。运行示例：`scripts/check_pdf_readers.py --pdf /sample/delivery/sample.pdf --output /sample/compat-after/readers-513`。用户资料的输出只能留忽略目录。

独立验证构建入口 deploy/Dockerfile.document-compat，从前轮验证镜像派生，默认pypdfium2=5.13.0、fontTools=4.55.3；PDFIUM_PACKAGE_VERSION构建参数仅用于另测版本。本轮实际先建4.30.0开发标签，再分别派生5.14.0和5.13.0标签；生成仍用固定PyMuPDF1.25.5/python-docx1.1.2，不依赖PDFium、Poppler、fontTools或LibreOffice。完整开发检查报告见 [阅读器兼容性报告](DOCUMENT_READER_COMPAT_REPORT.md)。本轮Linux同PDFium版本/倍率未复现用户Windows问题；根因和Windows新版验收仍未闭环，不宣称彻底修复。
