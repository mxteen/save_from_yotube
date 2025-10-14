import os
import sys
import threading
import queue
import shutil
from typing import Dict, Optional, Tuple
import time

# Third-party
import dearpygui.dearpygui as dpg
import yt_dlp
from yt_dlp.utils import DownloadError


# ----------------------------
# Global state and constants
# ----------------------------
APP_TITLE = "YouTube Saver (yt-dlp + Dear PyGui)"

ui_update_queue: "queue.Queue[Tuple[str, Dict]]" = queue.Queue()
download_thread: Optional[threading.Thread] = None
cancel_event = threading.Event()
last_pump_time = 0.0

# Item tags
TAG_MAIN_WINDOW = "main_window"
TAG_URL_INPUT = "url_input"
TAG_TYPE_COMBO = "type_combo"
TAG_QUALITY_COMBO = "quality_combo"
TAG_OUTPUT_TEXT = "output_text"
TAG_PICK_DIR_BTN = "pick_dir_btn"
TAG_START_BTN = "start_btn"
TAG_CANCEL_BTN = "cancel_btn"
TAG_PROGRESS_BAR = "progress_bar"
TAG_LOG_BOX = "log_box"
TAG_DIR_DIALOG = "dir_dialog"


def is_ffmpeg_available() -> bool:
	return shutil.which("ffmpeg") is not None


def platform_open_path(path: str) -> None:
	if not path or not os.path.exists(path):
		return
	if sys.platform.startswith("win"):
		os.startfile(path)  # type: ignore[attr-defined]
	elif sys.platform == "darwin":
		os.system(f'open "{path}"')
	else:
		os.system(f'xdg-open "{path}"')


def build_format_string(video_quality: str, force_mp4: bool, have_ffmpeg: bool) -> Tuple[str, Dict]:
	"""
	Returns (format_selector, extra_opts) suitable for yt-dlp based on requested quality.
	If ffmpeg is not available and merging would be required, fall back to single-file best.
	"""
	extra_opts: Dict = {}

	quality_heights = {
		"Best": None,
		"1080p": 1080,
		"720p": 720,
		"480p": 480,
		"360p": 360,
		"Audio only": None,
	}

	max_h = quality_heights.get(video_quality)

	# Audio-only special case
	if video_quality == "Audio only":
		return "bestaudio/best", extra_opts

	if force_mp4:
		# Prefer mp4 container for both video and audio
		if max_h is None:
			v_sel = "bestvideo[ext=mp4]"
		else:
			v_sel = f"bestvideo[ext=mp4][height<={max_h}]"
		a_sel = "bestaudio[ext=m4a]"
		fmt = f"{v_sel}+{a_sel}/best[ext=mp4]"

		if not have_ffmpeg:
			# Cannot merge without ffmpeg; fallback to single file
			if max_h is None:
				fmt = "best[ext=mp4]/best"
			else:
				fmt = f"best[ext=mp4][height<={max_h}]/best"
		else:
			extra_opts["merge_output_format"] = "mp4"
		return fmt, extra_opts

	# Generic best with optional height cap
	if max_h is None:
		return "bestvideo+bestaudio/best", extra_opts
	return (f"bestvideo[height<={max_h}]+bestaudio/best[height<={max_h}]", extra_opts)


def make_ydl_opts(url: str, out_dir: str, out_type: str, quality: str) -> Dict:
	have_ffmpeg = is_ffmpeg_available()

	ydl_opts: Dict = {
		"quiet": True,
		"no_warnings": True,
		"progress_hooks": [progress_hook],
		"outtmpl": os.path.join(out_dir, "%(title)s-%(id)s.%(ext)s"),
		"noprogress": True,
		"continuedl": True,
		"consoletitle": False,
		# SSL and timeout configurations to handle network issues
		"socket_timeout": 30,
		"retries": 3,
		"fragment_retries": 3,
		"http_chunk_size": 10485760,  # 10MB chunks
	}

	if out_type == "Video (MP4)":
		fmt, extra = build_format_string(quality, force_mp4=True, have_ffmpeg=have_ffmpeg)
		ydl_opts.update(extra)
		ydl_opts["format"] = fmt
		if not have_ffmpeg and "+" in fmt:
			ui_update_queue.put(("log", {"text": "FFmpeg not found; falling back to single-file MP4 if possible."}))

	elif out_type == "Audio (MP3)":
		ydl_opts["format"] = "bestaudio/best"
		if have_ffmpeg:
			ydl_opts["postprocessors"] = [
				{
					"key": "FFmpegExtractAudio",
					"preferredcodec": "mp3",
					"preferredquality": "0",
				}
			]
		else:
			ui_update_queue.put(("log", {"text": "FFmpeg not found; saving best audio without MP3 conversion."}))

	elif out_type == "Best (Original)":
		fmt, extra = build_format_string(quality, force_mp4=False, have_ffmpeg=have_ffmpeg)
		ydl_opts.update(extra)
		ydl_opts["format"] = fmt

	else:
		ydl_opts["format"] = "bestvideo+bestaudio/best"

	return ydl_opts


def progress_hook(d: Dict) -> None:
	if cancel_event.is_set():
		raise DownloadError("Cancelled by user")

	status = d.get("status")

	if status == "downloading":
		total = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
		downloaded = d.get("downloaded_bytes") or 0
		percent = 0.0
		if total and downloaded:
			percent = downloaded / total

		speed = d.get("speed")  # bytes/sec
		eta = d.get("eta")
		ui_update_queue.put(
			(
				"progress",
				{
					"percent": percent,
					"text": f"Downloading... {percent*100:.1f}%"
					+ (f" | {speed/1024/1024:.2f} MB/s" if speed else "")
					+ (f" | ETA: {eta}s" if eta else ""),
				},
			)
		)
	elif status == "finished":
		filename = d.get("filename") or ""
		ui_update_queue.put(("log", {"text": f"Downloaded to: {filename}"}))
		ui_update_queue.put(("progress", {"percent": 1.0, "text": "Download finished"}))


def downloader_worker(url: str, out_dir: str, out_type: str, quality: str) -> None:
	try:
		ydl_opts = make_ydl_opts(url, out_dir, out_type, quality)
		ui_update_queue.put(("log", {"text": f"Starting: {url}"}))
		with yt_dlp.YoutubeDL(ydl_opts) as ydl:
			ydl.download([url])
		ui_update_queue.put(("done", {"ok": True}))
	except DownloadError as e:
		ui_update_queue.put(("log", {"text": f"Cancelled: {e}"}))
		ui_update_queue.put(("done", {"ok": False}))
	except Exception as e:  # noqa: BLE001
		ui_update_queue.put(("log", {"text": f"Error: {e}"}))
		ui_update_queue.put(("done", {"ok": False}))


def on_pick_dir(_: int, data: Dict) -> None:
	# Dear PyGui file dialog returns a dict; for directories, use "file_path_name"
	path = data.get("file_path_name")
	if path:
		dpg.set_value(TAG_OUTPUT_TEXT, path)


def on_start_download() -> None:
	global download_thread
	url = dpg.get_value(TAG_URL_INPUT).strip()
	out_type = dpg.get_value(TAG_TYPE_COMBO)
	quality = dpg.get_value(TAG_QUALITY_COMBO)
	out_dir = dpg.get_value(TAG_OUTPUT_TEXT).strip()

	if not url:
		append_log("Please enter a URL.")
		return
	if not out_dir:
		append_log("Please choose an output folder.")
		return
	if not os.path.isdir(out_dir):
		append_log("Output folder does not exist.")
		return

	# Reset state
	cancel_event.clear()
	dpg.configure_item(TAG_START_BTN, enabled=False)
	dpg.configure_item(TAG_CANCEL_BTN, enabled=True)
	dpg.set_value(TAG_PROGRESS_BAR, 0.0)
	dpg.configure_item(TAG_PROGRESS_BAR, overlay="Waiting...")

	# Launch worker
	download_thread = threading.Thread(
		target=downloader_worker, args=(url, out_dir, out_type, quality), daemon=True
	)
	download_thread.start()


def on_cancel_download() -> None:
	cancel_event.set()
	append_log("Cancelling...")


def append_log(text: str) -> None:
	prev = dpg.get_value(TAG_LOG_BOX)
	new_val = (prev + "\n" if prev else "") + text
	dpg.set_value(TAG_LOG_BOX, new_val)


def ui_pump() -> None:
    """Apply UI updates from the background thread; throttled to ~150ms."""
    global last_pump_time
    now = time.perf_counter()
    if now - last_pump_time < 0.15:
        return
    last_pump_time = now

    try:
        while True:
            evt_type, payload = ui_update_queue.get_nowait()
            if evt_type == "log":
                append_log(payload.get("text", ""))
            elif evt_type == "progress":
                pct = max(0.0, min(1.0, float(payload.get("percent", 0.0))))
                txt = payload.get("text", f"{pct*100:.1f}%")
                dpg.set_value(TAG_PROGRESS_BAR, pct)
                dpg.configure_item(TAG_PROGRESS_BAR, overlay=txt)
            elif evt_type == "done":
                ok = payload.get("ok", False)
                if ok:
                    append_log("All tasks completed.")
                dpg.configure_item(TAG_START_BTN, enabled=True)
                dpg.configure_item(TAG_CANCEL_BTN, enabled=False)
    except queue.Empty:
        pass


def default_downloads_dir() -> str:
	# Try to default to user's Downloads directory
	home = os.path.expanduser("~")
	candidates = [
		os.path.join(home, "Downloads"),
		os.path.join(home, "downloads"),
		home,
	]
	for p in candidates:
		if os.path.isdir(p):
			return p
	return os.getcwd()


def build_ui() -> None:
	dpg.create_context()

	with dpg.window(tag=TAG_MAIN_WINDOW, label=APP_TITLE, width=720, height=520):
		dpg.add_text("YouTube URL")
		dpg.add_input_text(tag=TAG_URL_INPUT, hint="https://www.youtube.com/watch?v=...", width=690)

		dpg.add_spacer(height=6)
		dpg.add_text("Output Folder")
		with dpg.group(horizontal=True):
			dpg.add_input_text(tag=TAG_OUTPUT_TEXT, width=560, readonly=True, default_value=default_downloads_dir())
			dpg.add_button(label="Browse...", tag=TAG_PICK_DIR_BTN, callback=lambda: dpg.show_item(TAG_DIR_DIALOG))
			dpg.add_button(label="Open", callback=lambda: platform_open_path(dpg.get_value(TAG_OUTPUT_TEXT)))

		dpg.add_spacer(height=6)
		with dpg.group(horizontal=True):
			dpg.add_text("Type")
			dpg.add_combo(
				items=["Video (MP4)", "Audio (MP3)", "Best (Original)"],
				default_value="Video (MP4)",
				width=150,
				tag=TAG_TYPE_COMBO,
			)
			dpg.add_spacer(width=12)
			dpg.add_text("Quality")
			dpg.add_combo(
				items=["Best", "1080p", "720p", "480p", "360p", "Audio only"],
				default_value="Best",
				width=120,
				tag=TAG_QUALITY_COMBO,
			)

		dpg.add_spacer(height=6)
		with dpg.group(horizontal=True):
			dpg.add_button(label="Start", tag=TAG_START_BTN, callback=on_start_download)
			dpg.add_button(label="Cancel", tag=TAG_CANCEL_BTN, callback=on_cancel_download, enabled=False)

		dpg.add_spacer(height=6)
		dpg.add_progress_bar(tag=TAG_PROGRESS_BAR, default_value=0.0, overlay="Idle", width=690)

		dpg.add_spacer(height=6)
		dpg.add_text("Log")
		dpg.add_input_text(tag=TAG_LOG_BOX, multiline=True, readonly=True, width=690, height=250)

	# Directory dialog
	with dpg.file_dialog(
		directory_selector=True, show=False, callback=on_pick_dir, tag=TAG_DIR_DIALOG, min_size=(600, 400)
	):
		dpg.add_file_extension(".*")

	dpg.create_viewport(title=APP_TITLE, width=740, height=600)
	dpg.setup_dearpygui()
	dpg.show_viewport()
	dpg.set_primary_window(TAG_MAIN_WINDOW, True)

	# Main rendering loop with periodic UI updates
	while dpg.is_dearpygui_running():
		ui_pump()  # Process UI updates from background thread
		dpg.render_dearpygui_frame()

	dpg.destroy_context()


if __name__ == "__main__":
	build_ui()
