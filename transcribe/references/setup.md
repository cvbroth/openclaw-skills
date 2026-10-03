# 环境安装（一次就行）

```bash
# 系统依赖：ffmpeg（音频解码用，m4a/mp3 需要它）
sudo apt update && sudo apt install -y ffmpeg

# Python 依赖（清华镜像快一些）
pip3 install pymupdf rapidocr_onnxruntime faster-whisper \
  -i https://pypi.tuna.tsinghua.edu.cn/simple
```

- RapidOCR 模型：第一次运行时自动下载（几十 MB）
- faster-whisper 模型：第一次运行时自动下载（small 约 460MB，medium 约 1.5GB）
- 全部 CPU 运行，不需要 GPU
- 验证安装：`python3 bin/ocr_pdf.py --help` 和 `python3 bin/transcribe_audio.py --help` 能打出帮助即成功
