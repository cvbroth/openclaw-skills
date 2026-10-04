# V1.2 支持范围、质量与资源

| 文件 | 正式提取 | 分类/其他处理 |
|---|---|---|
| PDF .pdf | 每页原生文字或OCR，扫描/混合页保留原页码；损坏/加密拒绝 | 有图或原生文字少于30字符时整页OCR，非完整版式重建 |
| Word .docx | 正文XML顺序段落/表格，保存内嵌图片 | 图片-only块未识别，文字+图片可能PARTIAL；正文外内容不完整 |
| MD/TXT | UTF-8/BOM文本，空行分段 | 可普通read，生成output同样可读；不执行正文指令 |
| PNG/JPEG/WEBP/BMP/TIF/TIFF | 中英印刷文字OCR，多帧保留frame页码 | 不是照片画面理解 |
| WAV/MP3/M4A/FLAC/OGG | FFmpeg可解码音频，CPU int8 small ASR，原秒数 | 无说话人分离/事实核实，纪要另存 |
| XLSX | 不强制转MD；正式extract UNSUPPORTED_TYPE | spreadsheets分类；授权后受控openpyxl脚本输出副本，声明断言，不重算公式 |
| CSV/TSV/JSON/YAML/JSONL等 | 不冒充专用解析器 | 按签名/文本线索分类，普通read或已授权Python；可读性取决于UTF-8/内容/长度而非产物标签 |
| DOC/XLS/ODS、视频、压缩包、数据集、其他 | 未支持的正式extract返回UNSUPPORTED_TYPE | 分类/快照/引用可保存；不自动解压或执行，不保证对应Python依赖已安装 |

分类至少pdf/word/text/images/audio/video/spreadsheets/datasets/archives/other。扩展名与内容检测结合；二进制改名TXT/MD不变成正文。未知格式可登记但不能称正式处理成功。音频容器支持不保证所有codec/损坏文件有效。

普通照片画面、手写、数学公式、复杂表格/多栏阅读顺序、精确版式、DOCX页眉脚注批注修订/浮动框 **未可靠支持**。DOCX图像保留但未自动OCR，表格顺序和基本单元格文本可保留，复杂合并/嵌套不保证还原。PDF整页OCR可能弱于直接文字，必要时对照原件；非空文字/SUCCEEDED不证明扫描完整。

| 项目 | 默认/硬边界 |
|---|---|
| 接收/处理 | 4GiB；实际大文件测试201MiB，4GiB只验证计数边界 |
| 页/帧 | 10000；图像/OCR单帧≤2400万像素 |
| 音频 | 6小时；600秒主块+2秒重叠，完成块持久检查点 |
| 大文件提示 | >20页/块或>600秒；预览3页/块，音频预览最多60秒 |
| 输出 | 200万字符/20000段；图片资产32MiB；manifest64MiB |
| 文本读取 | UTF-8、≤16MiB文本文件、一次≤12000字符，二进制不解码 |
| 控制/返回 | 512KiB/2MiB；原件经共享目录，不经socket重传 |
| 并发/线程 | 全局重任务1（固定）；引擎线程2，可1–8 |
| 内存/CPU | worker4GiB虚拟地址限额+容器实际内存预算；初始CPU预算2 |
| 超时 | 普通任务3600秒；音频wall预算最多72小时，stall1800秒；检查15秒（最多60） |
| Python | 60秒；输出256MiB、1–8文件、每条日志≤1MiB，进程数32/容器96 |
| 配额 | 每Agent snapshot100GiB/saved50GiB/cache20GiB；余量1GiB，80%告警 |
| 会话 | 活跃引用32、任务32，身份由可信会话代次派生 |
| 缓存 | 有效使用后72小时；每小时清理；普通read租约5分钟，外部读取协作touch |

4GiB/6小时是参数上限，不是速度或成功承诺；文本/解压/输出限额仍可能先触发。首次模型下载、运行库、冷载入、音频codec及NAS其他服务都会影响耗时。依赖版本在pyproject/requirements.lock和Node锁文件固定；生产镜像/系统包digest需构建记录。

真实本地测试：合成PDF/DOCX/图片/MD与MIT许可固定JFK英文11秒录音；OCR/ASR为真实引擎，XLSX为真实文件。Windows及本机Docker Linux均已实测；Linux还验证了文件隔离、进程回收、共享卷及Unix控制接口。中文长录音/数小时ASR、NAS资源峰值、真实OpenClaw Gateway与QQ全链路仍待生产验收。本机Windows/虚拟Linux计时不能外推到Xeon NAS。

V2路线图仅记录：MD/简单文本生成DOCX/PDF，尽量保留版式的转换，对字体/表格/分页/图像损失给具体风险说明；不在V1.2新增完整办公平台、转换工具大全、账号系统、MCP、网页、自动向量入库或通用下载平台。
