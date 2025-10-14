# YouTube Saver (Dear PyGui + yt-dlp)

A simple Windows desktop app to download YouTube videos or audio using yt-dlp, with a minimal UI built in Dear PyGui.

- URL input
- Output folder picker
- Type: Video (MP4), Audio (MP3), or Best (original)
- Quality presets: Best, 1080p, 720p, 480p, 360p, Audio only
- Progress bar and log

## Prerequisites

- Python 3.12+
- Optional but recommended: FFmpeg available on PATH for merging and MP3 conversion
  - Windows: Download a static build and add `bin/` to PATH.

## Install

```bash
python -m venv .venv
.venv\Scripts\pip install -U pip
.venv\Scripts\pip install -r requirements.txt
```

## Run

```bash
.venv\Scripts\python main.py
```

Paste a YouTube link, choose output folder/type/quality, then click Start.

## Notes

- Without FFmpeg, MP4 merges and MP3 conversion are limited. The app falls back gracefully and logs a note.
- yt-dlp supports many sites and options; this app uses sensible defaults.

## Dependencies

This project uses:
- [DearPyGui](https://github.com/hoffstadt/DearPyGui) - MIT License
- [yt-dlp](https://github.com/yt-dlp/yt-dlp) - Unlicense

## References

- yt-dlp README: `https://github.com/yt-dlp/yt-dlp#readme`
- yt-dlp on PyPI: `https://pypi.org/project/yt-dlp/`
- DearPyGui Documentation: `https://dearpygui.readthedocs.io/en/latest/`
