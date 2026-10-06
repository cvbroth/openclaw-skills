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

复用固定 Python3.12.10、python-docx1.1.2、PyMuPDF1.25.5，未增加 Python 依赖。Word 与 PDF 共用一份有序段落模型。A4竖版、四边2厘米、正文11.5磅、1.35行距、6磅段后距；真正标题样式、题干独立段落、选项缩进。题号与题干开头用不换行空格相连，长题自然跨页，原页码仅是来源标记，没有手工分页。该模板针对本轮单选题样本；不是通用 OCR/多栏/公式重建。

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
```

extract 只接受预先合法制作的5页 PDF 副本，其引擎页码仍为1–5。`source-map.json` 和单独 mapped-ocr.md 记录与原页6–10的映射；不篡改引擎 sources。重新 OCR 原稿另存，生成阶段优先读取用户提供的旧 OCR 输入包。不能因 `/root` 不可读就提升权限或扫描缓存；本轮用户自行提供工作区旧样本。

## 验证与交付边界

正文恢复先逐题对照原页，再运行 DOCX/PDF 内容顺序和几何校验，最后实际渲染并人工看逐页图片。存在/退出0/非空不能证明正确。Word 导出的 PDF 在固定 PyMuPDF 下曾返回空 dict blocks；独立渲染验证使用 [get_texttrace 官方绘制轨迹接口](https://pymupdf.readthedocs.io/en/latest/functions.html#Page.get_texttrace) 并要求非空，逐字检查缺字和矩形，避免空几何检查误报通过。

validation.json 是生成器自动检查；rendered/render-checks.json 是独立 Word/PDF 渲染检查，两者均不代替人工原页核对。

FileTools 发布后由 status 获取 job_id/artifact_id/file_id，通过 files/artifact_path 返回真实 Gateway 开发路径、bytes/SHA，再取回核对。delivery 目录为这些真实发布产物的哈希核对副本。普通 preview 路径不冒充发布附件；本轮没有真实 OpenClaw/QQ message 成功回执，不声称送达 QQ。没有调用永久 files/save 或知识库导入。

本轮结果、已核实的漏行与未验证项见 [样本验证报告](DOCUMENT_SAMPLE_REPORT.md)。全册和生产部署均等待用户另行确认。
