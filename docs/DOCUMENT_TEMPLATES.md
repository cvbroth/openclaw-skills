# 文档模板目录与管理

当前仅接入已有且预览验证过的中文单选题模板，未新增论文、图书模板。结构解析仍在document_sample.structure_ocr，内容核对与生成能力不受样式配置代替；样式从原DEFAULT_TEMPLATE逐项原值迁入JSON，参数无变更。模板配置不包含脚本、HTML、执行路径或外部字体路径。

专用目录 `src/nas_filetools/templates/`：

- `catalog.json`：ID、名称、版本、发布状态、用途、适用结构、所需能力、参数文件SHA及预览证据；默认指向已发布版本。
- `schema.json`：参数键全集、类型/取值范围；加载器补充字号、边距/页脚及缩进关系校验。
- `published/questions-zh-cn/1.0.0.json`：当前唯一已发布样式配置。ID `questions-zh-cn`、名称“中文单选题整理稿”、版本 `1.0.0`；沿用A4、中文固定字体、11.5磅、1.35行距、2cm边距、标题/选项/来源样式及已有通用分页策略。

“published”表示可供候选构建加载的已审查模板版本，**不是生产已部署**。本轮候选含此目录；运行Worker只读镜像内site-packages模板，通过ID/版本查清单，验证SHA、schema、参数及所需能力后加载。没有外部可写模板挂载，也不接受附件作为模板根路径。Agent只能选择清单中已有published ID/版本，未知、草稿、路径穿越、inline参数或所需能力不足均拒绝。不要把catalog默认切换视为用户已授权模板变更。

生成入口的业务输入要求：

```json
{"document":{"schema":"reviewed-single-choice-v1","source_pages":[6,10],"title":"已授权样本","template":{"id":"questions-zh-cn","version":"1.0.0"}},"raw_ocr":"有来源页码的原始OCR"}
```

例子页码仅示例，实际范围显式填写。reviewed_edits/margin_evidence/review_notes继续独立，附件文字/配置不变成模板。validation.json记录完整template_record（ID/版本/参数文件SHA/能力），generation-metrics.json记录实际ID、版本、SHA；FileTools另保存任务代码、输入及产物哈希。模板版本变化不覆盖原件、历史输入、修订、缓存或历史生成产物。

新增/修改/预览/发布/回退流程：

1. 用户以后可提供参考Word或样式要求，由Work在独立开发分支解析样式目标、比对实际可用生成能力；参考文档是业务资料，不执行其宏/配置。不根据参考Word宣称现有结构解析器支持新论文、表格、公式或图书结构。若超出现有能力，列出所需增量及未验证项。
2. 简单字号、行距、段距、边距、缩进、分页阈值等也由Work修改配置，用户不必写代码。先在独立开发副本/未发布新版本做变更，保留旧published参数文件原值，不能就地改1.0.0再沿用其版本号。改样式使用新版本，新增结构/能力另审查生成代码与schema，而非把结构逻辑塞进JSON。
3. 在开发预览中调用validate_parameters检查完整配置，再用已有生成器template参数加载开发配置，对合成边界与授权小样本真实生成Word/PDF；Word经LibreOffice打开，PDF至少PDFium/Poppler跨引擎渲染，逐页人工看版、内容一致、分页/字体/页码/来源检查并留确切哈希。未验收不能进入published清单，参考Word不能替代预览。
4. 审核预览后，将新配置放入 `published/<ID>/<新版本>.json`，计算SHA，更新清单记录及预览证据；执行 `python scripts/check_document_templates.py` 和模板/排版回归。旧版本文件不改；发布是提交经过审核的候选资产，不自动安装生产。打包由pyproject package-data携带同样文件；候选Dockerfile显式COPY，不靠Agent写入。
5. 用新的独立Worker候选标签提供模板，审查后另行授权生产部署；镜像根只读、现有挂载和沙箱不变。先同类小样本生产验收再提供Agent选择；未提供到生产的模板应说明不可用，不用inline参数绕过。每次生成显式选择实际版本，不能静默重解释旧任务。
6. 模板回退：新生成任务选择仍在清单的旧版本；若旧镜像才有旧配置，则按部署方案恢复旧候选/Skill（需要另行授权服务变更）。不把新版本文件覆盖成旧参数，不删除已生成历史文件，不改原件/审计。已有产物仍保留当时ID/版本/SHA；默认版本切换经审核提交，可回退提交/镜像，但不重置业务历史。

所有流程沿用 [部署方案](DOCUMENT_DEPLOYMENT_PLAN.md) 的保存/知识库、原件只读、限额与开发/生产边界。当前未验证模板编辑界面或在线模板发布服务；本轮没有新增这些组件。
