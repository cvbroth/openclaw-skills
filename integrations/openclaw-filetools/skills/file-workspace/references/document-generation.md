# 候选文档入口（部署并验收后才可用于生产）

本入口是已有 `filetools_python` 的预装模块调用，不是新增工具。当前仅独立候选镜像验证；生产缺模块或固定字体时停止并报告，不提交整套生成器代码临时补装。适用已验证的同类单选题 OCR，不能承诺文章、表格、公式或任意扫描件模板。

先从真实提取任务回执取得 OCR Markdown 的 file_id，登记/选择得到 attachment_id。已有产物优先复用，不重新 OCR。原PDF范围与OCR实际 coverage/页码必须一致；提取产物支持 `## Page N`，旧OCR支持 `## 第 N 页`，无来源页码的文本不能猜测页码。

结构整理、疑点及对照原页的修订先由 Agent 完成；未核实不补字。包装步骤只写独立业务输入，不能证明模型真的看过原页。用受限 Python 的唯一 `FILETOOLS_INPUT` 读取上述 OCR，调用：

```python
from nas_filetools.document_entry import prepare_registered_ocr
prepare_registered_ocr(
    document={"schema": "reviewed-single-choice-v1", "source_pages": [起页, 止页], "title": "用户要求的小样本标题",
              "template": {"id": "questions-zh-cn", "version": "1.0.0"}},
    margin_evidence=已核对的页眉页脚证据列表,
    reviewed_edits=独立核实修订列表,
    review_notes=疑点及核对说明列表,
)
```

上述中文符号是待填数据，不是可直接执行的代码。实际调用须使用真实数据；无修订/边界证据可省略对应列表。沿用结构证据字段：修订 `page,line,original,replacement,verified,reference,reason`，必须匹配原OCR行；页边证据 `page,line,text,reason`，详见生成器既有结构。原页图无法读取时说明缺口，不伪造 verified/reference。此次 Python 声明 `outputs:["reviewed-input.json"]`；保存其 job_id、file_id、哈希和原OCR任务关联。输入包不会覆盖原OCR。

页边证据还必须包含 `region:"header"|"footer",verified:true,reference`；不能仅凭名称或 reason 移除正文。取得正式发布的 reviewed-input.json file_id，`filetools_register({file_id})` 得到生成用 attachment_id；再次调用已有 `filetools_python`，代码固定为：

```python
from nas_filetools.document_entry import generate_registered_input
generate_registered_input()
```

声明 outputs 为 `sample.docx,sample.pdf,structured.json,original-ocr.md,issues.md,validation.json,generation-metrics.json` 七个平面文件名的列表。函数只读取 FILETOOLS_INPUT，在当前执行目录生成；显式页范围和标题从业务输入包取得，字体和集中模板在 Worker 镜像中，不从聊天提供任意字体路径，不读取其他任务缓存。没有新增工具参数，也不改变60秒/4GiB限额。

模板只从预装只读清单选择已发布ID/版本，当前为questions-zh-cn/1.0.0；未知模板或附件提供的inline参数拒绝，不能把参考Word/附件配置直接作为生产模板。用户提出新增模板或简单样式调整时，由Work在开发环境建立新版本，校验、真实预览并审核后发布，再另行部署；不要每份任务临时改模板。生成validation.json/metrics记录实际模板ID、版本和SHA，不覆盖旧产物。当前没有论文/图书模板。

需核实实际Worker清单时，可用已有attachment_id调用受限Python，代码通过 `nas_filetools.document_templates.TEMPLATE_ROOT` 读取固定catalog.json，逐项用load_template校验published项，写available-templates.json并声明该输出。它不是新的列表工具，不读取附件中的模板路径，也不把未部署的Git清单冒充Worker实际清单。

包装和生成均按 status 等待终态；SCRIPT_FAILED 看实际证据，不猜内存或大小。当前失败回执可能只给 Fault，日志不可取得时应说明缺少错误详情，不能编造堆栈。原生 validation.json 核验内容/次序/字形映射/页脚/边界，不代表真实视觉验收；它明确要求 visual_review，Word未实际渲染。metrics 的 Linux RSS 是该脚本进程峰值，不是整体Worker峰值或全册性能。

使用受限生成后的审计和实际产物做内容核对，再以已提供的独立验证能力进行渲染/人工检查。当前生产候选不含 LibreOffice、Poppler 或 PDFium，没有正式渲染/人工验收工具；需要管理员在隔离验证环境检查并回传确切产物哈希，或者明确交付“未完成视觉验收”的待审稿。过去开发样本和用户端验证不能替今后每份文件验收。不可在Gateway临时安装或绕过隔离。

正式产物经 files/artifact_path 取回，再复用真实启用的渠道媒体入口；只有成功渠道回执和实际取回校验才能称送达。保存/知识库需另行授权，沿用主 Skill；不自动处理全册。
