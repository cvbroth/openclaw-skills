#!/usr/bin/env python3
"""音频转文字。

用法:
    python3 transcribe_audio.py 会议录音.m4a
    python3 transcribe_audio.py 会议录音.m4a -o result.txt --model base
"""
import argparse


def main():
    ap = argparse.ArgumentParser(description="音频转文字")
    ap.add_argument("input", help="音频路径（mp3/m4a/wav）")
    ap.add_argument("-o", "--output", default=None, help="输出 txt 路径")
    ap.add_argument("--model", default="small",
                    choices=["tiny", "base", "small", "medium"],
                    help="模型越大越准越慢，默认 small")
    ap.add_argument("--language", default="zh", help="语言，默认中文 zh")
    args = ap.parse_args()

    from faster_whisper import WhisperModel
    model = WhisperModel(args.model, device="cpu", compute_type="int8")
    segments, info = model.transcribe(args.input, language=args.language)
    print(f"检测语言: {info.language}，时长: {info.duration:.0f}s", flush=True)

    lines = []
    for seg in segments:
        ts = f"{int(seg.start // 60):02d}:{int(seg.start % 60):02d}"
        lines.append(f"[{ts}] {seg.text.strip()}")

    out_path = args.output or args.input.rsplit(".", 1)[0] + ".txt"
    with open(out_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    print(f"完成，共 {len(lines)} 段，结果在 {out_path}")


if __name__ == "__main__":
    main()
