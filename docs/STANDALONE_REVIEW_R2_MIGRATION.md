# 原图评价与预览迁移（开发版 R2）

兼容 `filetools-project-v1` 和旧反馈 schema。`project.json.source_evaluations` 是独立于正文产物的原图评价集合；`review/source-assessments.json` 是同源导出镜像。每条记录关联源 artifact_id/SHA/version、原件定位、实际提交图片 SHA/尺寸、模型、任务、尝试、时间、依据、未知说明和证据位置。历史任务缺逐次结束时间时沿用任务完成时间，仅为任务时间证据，不能解释为精确模型评价时间；缺时间保持未知。

迁移首次启动前，逐项目备份 `diagnostics/migrations/source-quality-v1/project-before.json`，本轮另有忽略目录 runtime/standalone-http-r2/before 的迁移前快照。迁移幂等，不覆盖模型原始结果、Markdown、DOCX、PDF或旧反馈。项目继续使用原 ID，不按原件 SHA 跨项目合并。已有项目标明历史验证，新的 HTTP 上传才标记用户项目。

绑定要求：有效质量等级，确定的源页定位，保存的实际传图 SHA/宽高与源预览文件逐字节/尺寸一致。没有证明、图片缺失或结构异常的评价保留到 `legacy_quality_records`，不猜位置，不纳入原图等级统计。旧导出只有页级质量且多次请求关联不唯一时，保留未绑定记录，不给每次请求套用最终评价。旧 Markdown 页字段和原生质量产物保留作历史证据，但界面不再用它们筛选产物。

同一项目内按“源定位＋图像SHA”合并重复原图展示，保留全部 task_ids；各次评价独立、不覆盖。默认选择记录列表最后一条，工具栏明确显示选定模型/任务时间，可在评价详情切换；选择保存在本机、按项目隔离。没有评价是 unknown，不是 poor、undetermined 或 good。undetermined 仅表示模型明确无法判断。新提示口径为原图可辨读性，模型自评仍未经校准；本轮未重新调用模型评价历史图像。

反馈增加可选 `object_type=artifact|source_page`；旧回执缺字段按 artifact 处理，不擅自迁成原图评论。原图评论必须指向登记的源页；产物评论关联产物 SHA。新增 output_page 定位含页号和 render_key，明确不是 PDF 原件物理页。旧定位保存到 legacy_pages，旧文档级评论仍可读取。导入继续校验项目版本、对象、产物哈希、定位与反馈修订，拒绝冲突/过期；空评论代表明确清除，历史回执不删。

预览独立记录 `artifact.preview_render`，不改变正文产物的成功/失败状态。新生成 DOCX/PDF 发布后追加串行预览任务；已有产物由明确操作补生成。缓存键为产物 SHA、格式、渲染器版本与120dpi参数；renderer算法变化须提升 schema，不能沿用旧键冒充新预览。重启把未完成预览标为 INTERRUPTED，人工重试；验证缓存存在且 SHA 一致才复用。没有字体或 LibreOffice 时真实失败，不用独立生成 PDF 充当 DOCX。原件PDF只能显示明确处理页的既有预览，通用预览入口拒绝隐式渲染全原件。

开发数据回退：先停止且确认独立开发队列空闲，保留 R2 project/feedback/previews 副本，再恢复对应 project-before.json 与旧版本评审代码；不要恢复整个 store 覆盖新增任务或反馈。旧代码不理解 output_page/source_page对象的新反馈，回退前必须单独导出保存新反馈。本轮不涉及生产数据库、模板或服务回滚。
