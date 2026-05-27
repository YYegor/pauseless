import os
import re
import asyncio
import logging
from typing import Tuple

import yt_dlp
import config

logging.basicConfig(
    format=config.logs_format,
    level=logging.INFO,
    filename=config.logs_filename
)

from yt_dlp.extractor.youtube import YoutubeIE


async def is_youtube_link(url: str) -> bool:
    return YoutubeIE.suitable(url)


def convert_vtt_to_srt(vtt_path: str, srt_path: str):
    """
    Pure Python VTT to SRT converter.
    Removes the need for ffmpeg!
    """
    with open(vtt_path, 'r', encoding='utf-8') as f:
        content = f.read()

    # 1. Remove WEBVTT header and any global metadata
    content = re.sub(r'^WEBVTT.*?\n', '', content, flags=re.MULTILINE)
    content = re.sub(r'^Kind:.*?\n', '', content, flags=re.MULTILINE)
    content = re.sub(r'^Language:.*?\n', '', content, flags=re.MULTILINE)

    lines = content.split('\n')
    srt_lines = []
    sub_idx = 1

    for line in lines:
        if '-->' in line:
            # SRT requires a subtitle sequence number
            if srt_lines and srt_lines[-1] != "":
                srt_lines.append("")
            srt_lines.append(str(sub_idx))
            sub_idx += 1

            # Extract and fix timestamps
            # VTT: 00:05.000 --> 00:07.000 align:start
            # SRT: 00:00:05,000 --> 00:00:07,000
            timestamps = line.split('-->')
            start_ts = timestamps[0].strip().split(' ')[0]
            end_ts = timestamps[1].strip().split(' ')[0]

            def format_ts(ts):
                ts = ts.replace('.', ',')  # SRT uses commas for milliseconds
                if ts.count(':') == 1:  # If missing hours (MM:SS,mmm), add them
                    ts = '00:' + ts
                return ts

            srt_lines.append(f"{format_ts(start_ts)} --> {format_ts(end_ts)}")
        else:
            # Clean up YouTube's inline tags in auto-subs (e.g., <c>, </c>, <00:00:01.000>)
            clean_line = re.sub(r'<[^>]+>', '', line)

            # Prevent multiple blank lines in a row
            if clean_line.strip() == "" and (not srt_lines or srt_lines[-1] == ""):
                continue

            srt_lines.append(clean_line)

    # Write the formatted SRT file
    with open(srt_path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(srt_lines).strip() + '\n')


async def fetch_srt_for_video(url: str, lang_req: str = "en") -> Tuple[str | None, str | None]:
    """
    Download VTT subtitles matching `lang_req` prefix and convert to SRT in Python.
    """
    cache_dir = config.srt_cache_folder_name
    os.makedirs(cache_dir, exist_ok=True)

    def _extract_info():
        with yt_dlp.YoutubeDL({
            "writeautomaticsub": True,
            "skip_download": True}) as ydl:
            return ydl.extract_info(url, download=False)

    try:
        info = await asyncio.to_thread(_extract_info)
    except Exception as e:
        logging.error("Failed to extract video info for %s: %s", url, e)
        return None, None

    video_id = info.get("id")
    title = info.get("title", "Unknown show")

    if not video_id:
        return None, None

    # Define final intended SRT path
    final_srt_path = os.path.join(cache_dir, f"{video_id}.{lang_req}.srt")
    if os.path.exists(final_srt_path):
        logging.info("Returning cached SRT: %s", final_srt_path)
        return final_srt_path, title

    # Search for requested language
    lang_req_lower = lang_req.lower()
    uploaded_subs = info.get("subtitles") or {}
    auto_subs = info.get("automatic_captions") or {}

    target_uploaded_lang = next((k for k in uploaded_subs if k.lower().startswith(lang_req_lower)), None)
    target_auto_lang = next((k for k in auto_subs if k.lower().startswith(lang_req_lower)), None)

    if not target_uploaded_lang and not target_auto_lang:
        logging.warning("No subtitles found for prefix '%s' in video %s", lang_req, video_id)
        return None, None

    use_auto = target_uploaded_lang is None
    chosen_lang = target_auto_lang if use_auto else target_uploaded_lang

    # yt-dlp Options: Request strictly native formats (VTT), no post-processors required
    ydl_opts = {
        "writesub": not use_auto,
        "writeautomaticsub": use_auto,
        "subtitleslangs": [chosen_lang],
        "subtitlesformat": "vtt/best",  # Natively get VTT
        "skip_download": True,
        "outtmpl": os.path.join(cache_dir, f"{video_id}.%(ext)s"),
        "quiet": False,
        "no_warnings": True,
    }

    def _download_subs():
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ret_code = ydl.download([url])
            if ret_code != 0:
                raise Exception("Subtitle download failed")

    try:
        logging.info("Downloading native subtitles for %s", url)
        await asyncio.to_thread(_download_subs)
    except Exception as e:
        logging.error("Error downloading subtitles: %s", e)
        return None, None

    # Find the downloaded file
    prefix = f"{video_id}."
    downloaded_vtt = None

    for fname in os.listdir(cache_dir):
        if not fname.startswith(prefix):
            continue
        if fname.endswith((".vtt", ".srv3", ".json3")):
            downloaded_vtt = os.path.join(cache_dir, fname)
            break

    if downloaded_vtt:
        try:
            # Convert the native file to our perfect SRT file using our custom Python function
            convert_vtt_to_srt(downloaded_vtt, final_srt_path)
            logging.info("Converted %s to pure SRT: %s", downloaded_vtt, final_srt_path)
        except Exception as e:
            logging.error("Failed to convert VTT to SRT: %s", e)
            return None, None

        # Clean up all the leftover yt-dlp temp files (including the original .vtt)
        for fname in os.listdir(cache_dir):
            if fname.startswith(prefix) and fname != f"{video_id}.{lang_req}.srt":
                try:
                    os.remove(os.path.join(cache_dir, fname))
                except OSError:
                    pass

        return final_srt_path, title

    logging.error("Download succeeded, but no subtitle file was found in cache.")
    return None, None


async def main():
    url = "https://www.youtube.com/watch?v=7N68NjL9cMA"
    path, title = await fetch_srt_for_video(url, "en")
    print(f"Got SRT: {path}")


if __name__ == '__main__':
    asyncio.run(main())