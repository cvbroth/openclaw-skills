# 第6–10页文档样本验证报告

> 本文记录初版提交时点；后续模板及分页改进见 [分页改进报告](DOCUMENT_PAGINATION_REPORT.md)，不以本文历史页数/验收结论代替后续结果。

2026-10-06，服务器独立开发分支 `feat/filetools-document-sample-20261006`，继承录音更新 `364d4d6431e63bd0244d4bce780b1b19458485b6`。沿用 FileTools V1.2.1 和受限 Python；没有新增工具协议、重做架构或部署生产。

## 输入与核对结果

只读用户指定原 PDF，并用成熟 PyMuPDF 制作第6–10页副本。原件 size/mtime 保持不变。指定 `/root` OCR 无读取权限，未提升权限读取；随后用户把对应旧 OCR 放入 `runtime/document-sample/original-ocr-p6-p10.md`。旧稿 SHA-256 为 `9ca6e82cd2749b68ab3dffbd09735c235a7cccff5b59a1802a67eaf233a39f70`，原稿和交付原稿副本一致。

另对5页开发副本运行真实固定 RapidOCR，任务 `fd4b74a62fd6471d8da98b0855040cd1` SUCCEEDED。结果保存在 excerpt-raw-ocr.md 和独立来源映射中；没有覆盖旧稿。两种 OCR 均漏掉下面两段，证明 SUCCEEDED 不是还原完整性保证。

| 原页 / 题号 | 原 OCR 问题 | 本轮处理及证据 |
|---|---|---|
| 第6页 / 第4题，OCR行33 | 题干在“写出几本较大的著”后跳行 | 对照原页260dpi局部，确认原 PDF 完整；漏掉的是下一行。仅在独立整理稿补录，保留原文/修订/图像参考 |
| 第10页 / 第32题，OCR行271 | 题号与引用开头整行缺失，被接到第31题末尾 | 对照原页260dpi局部恢复题号和开头；原稿不改 |
| 第8页 / 第16题，OCR行124 | C、D选项误并成一行 | 原页位置确认后拆为独立选项，两个来源片段仍指向同一原行 |
| 第9–10页 / 第27题 | 题干跨页，漏字和相似字 | 保持同题和双页来源，修订依据原页局部，记录跨行漏字 |
| 第6–10页 / 页边文字 | 页眉、侧边“马原·单选”、页脚混入正文 | 原页位置证据对应19个原片段，全部保留在处理记录 |

逐页查看原页，核对32题题干、128个A–D选项和顺序；对显见 OCR 错字、标题序号、选项标记及漏行作28条独立修订。章节/题干/①②③④/选项结构恢复，扫描换行仅在同块合并。第27题保留原9、10页双来源。生成器未发现剩余结构疑点，不等于全部字词绝对准确；issues.md 保留已核实缺陷及修订，仍请用户复核，不能推广为全册正确。

## 文档与真实发布

最终正文202段（原失败整册文件8788段不作为本轮测试输入），无按原页强制分页。固定 Droid Sans Fallback 字体、A4/2厘米边距/11.5磅正文/1.35行距/6磅段后距、真实标题样式、统一选项缩进。Word/PDF 共用结构模型，正文和顺序相等；PDF8页。生成器实际检查字体字形、提取内容和页面几何。

实际 FileTools 核心以单个登记输入运行 Landlock 受限 Python；输入路径来自 FILETOOLS_INPUT。真实已发布 OCR file_id 再登记的读取证明任务 `ebb146e072b640249366909f0267eebd`，读到的哈希与 OCR 回执一致。最终生成任务 `a20ce4ece9ee44088c59a992f00dad6c` 为 SUCCEEDED，通过 status → files/artifact_path 取得以下产物，逐份核对取回字节数及 SHA-256。不是普通预览路径，也没有 QQ 送达回执。

| 产物 | 字节数 | SHA-256 |
|---|---:|---|
| sample.docx | 46717 | `2f08d854bd90f53b542be0c4205d9d3fda1143be139b6b28cae894a5c87cdb0a` |
| sample.pdf | 3911255 | `433109cea93621257c916033799e44ead51c7c1c4ab8aca05f56dbfa78ddea51` |
| issues.md | 15991 | `0b4e0b054da7ac2bfe3b27b5510fdfc73584a3d33490f7ef784a4cebfa89bfcc` |
| original-ocr.md | 17672 | `9ca6e82cd2749b68ab3dffbd09735c235a7cccff5b59a1802a67eaf233a39f70` |

完整 job/artifact/file_id 回执及另外两份 structured.json、validation.json 的字节/hash 在本机 runtime/document-sample/pipeline-receipt.json；文档和处理记录在 delivery。用户样本不推送 GitHub，没有调用永久 files/save 或知识库导入。

## 渲染验收

LibreOffice 7.4.7.2 40(Build:2) 实际打开并导出 Word 为10页 PDF；PyMuPDF 排版 PDF 为8页。两者重新提取的全文和顺序与 DOCX 模型一致，A4、绘制轨迹及每个字形的边界检查通过。Word 导出使用嵌入的 DroidSansFallback；PyMuPDF PDF 的中文使用 Droid Sans Fallback Regular，部分数学符号使用内置 NotoSansMath-Regular。

人工查看全部18页的联系表，并放大检查标题、①②③④、选项、漏行恢复及末页等代表页；未见中文缺字、裁切、空白页或异常大空白。题目/选项可自然跨页，末页剩余空白是内容结束，未做一题一页或原页强制分页；部分来源标记位于续页开头。

初次检查发现 LibreOffice PDF 的 get_text("dict") 返回空 blocks，虽 plain text 非空；因此没有把空循环算几何通过，改用实际 get_texttrace 逐字绘制轨迹检查后重跑成功。缓存目录指定独立tmpfs，Java警告不影响本次纯文字渲染（未启用Java）。生成器 validation.json 的 word_render:not-checked-by-this-function 保留其准确函数边界；独立渲染结果在 rendered/render-checks.json，未改写已发布产物。

专用开发镜像 `filetools-document-test:20261006-364d4d6` ID：`sha256:edb3ca0710298ff4fe36a613dfdd2ee295f750c90cf60ebe602d6d319b85adbe`。字体文件SHA：`ee38813ea00c3e32add4268fff7fff9e39417b4913cb13be2415164a47807cc2`。依赖准备经历直连下载主动取消/代理回环不可达失败，最终仅构建阶段使用既有宿主回环代理成功；样本生成与渲染均离线。

## 真实、合成/模拟、未验证

- **真实**：Linux固定 Python/依赖、原页图像核对、5页实际 OCR、原稿哈希保持、python-docx/PyMuPDF生成与文本/几何检查、Landlock脚本、核心正式发布/取回哈希；本轮核心回归99通过/15跳过，边界强化后新增8项测试复测通过，Ruff通过。
- **合成/模拟**：新增结构测试材料是合成题目；默认核心套件包含注入替身与边界测试，不能称99项真实OCR或生产验收。长题跨页用合成重复题干验证，没有处理全册。
- **未验证**：真实 OpenClaw SDK/Gateway/Worker/QQ通道、本轮QQ客户端下载、用户端 Microsoft Word 字体替换、全册/复杂表格/公式/全部字词准确率、CI及生产兼容性。ASR模型未调整或测试。

本轮只在开发镜像准备 LibreOffice 和字体。正式处理容器2CPU/4GiB、离线、只读根、cap-drop/no-new-privileges，仓库只读，仅开发样本目录和tmpfs可写。不进入/重启生产容器，不改Gateway/Worker/Samba、NAS权限或生产配置，不覆盖生产镜像标签。原PDF只制作授权的5页副本，不扫描其他资料。后续全册或部署等待用户确认。
