import os
import asyncio
import logging

import yt_dlp
import config


logging.basicConfig(
    format=config.logs_format,
    level=logging.INFO,
    filename=config.logs_filename
)

from yt_dlp.extractor.youtube import YoutubeIE

async def is_youtube_link(url: str) -> bool:
    # .suitable() checks if the URL matches the regex patterns
    # defined inside the library for YouTube.
    return YoutubeIE.suitable(url)

async def fetch_srt_for_video(url: str, lang_req: str = "en") -> str | None:
    """
    Download subtitles (uploaded, or fallback to automatic) for `url` in `lang_req`
    as .srt, store them in config.srt_cache_folder_name, and return the full path
    to the .srt file. Returns None if nothing could be obtained.

    The function is async and uses asyncio.to_thread to avoid blocking the event loop.
    """
    # Ensure cache folder exists
    cache_dir = config.srt_cache_folder_name
    os.makedirs(cache_dir, exist_ok=True)
    logging.info("Using SRT cache folder: %s", cache_dir)

    # 1. Get info about available subtitles (uploaded + auto)
    def _extract_info():
        with yt_dlp.YoutubeDL({
                "writeautomaticsub": True,
                "subtitleslangs": [lang_req],
                "skip_download": True}) as ydl:
            return ydl.extract_info(url, download=False)

    try:
        info = await asyncio.to_thread(_extract_info)
    except Exception as e:
        logging.error("Failed to extract video info for %s: %s", url, e)
        return None

    video_id = info.get("id")
    if not video_id:
        logging.error("No video ID found for URL %s", url)
        return None

    logging.info("Video id: %s", video_id)

    uploaded_subs = info.get("subtitles") or {}
    auto_subs = info.get("automatic_captions") or {}
    print (info)
    has_uploaded = lang_req in uploaded_subs
    has_auto = lang_req in auto_subs

    logging.info(
        "Subtitle availability for %s: uploaded=%s, automatic=%s",
        lang_req,
        has_uploaded,
        has_auto,
    )

    if not has_uploaded and not has_auto:
        logging.warning(
            "No subtitles (uploaded or auto) found for language '%s' in video %s",
            lang_req,
            video_id,
        )
        return None

    # Decide which type to download
    use_auto = not has_uploaded and has_auto
    logging.info(
        "Will use %s subtitles for language '%s'",
        "automatic" if use_auto else "uploaded",
        lang_req,
    )

    # 2. Prepare yt-dlp options for subtitle-only download in .srt
    srt_target_path = os.path.join(cache_dir, f"{video_id}.srt")

    ydl_opts = {
        "writesub": not use_auto,         # True if using uploaded subs
        "writeautomaticsub": use_auto,    # True if using auto subs
        "subtitleslangs": [lang_req],
        "subtitlesformat": "srt",         # ask yt-dlp to convert to srt if needed
        "skip_download": True,            # don't download video
        "outtmpl": os.path.join(cache_dir, f"{video_id}.%(ext)s"),
        "quiet": True,
        "no_warnings": False,
    }

    def _download_subs():
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ret_code = ydl.download([url])
            if ret_code != 0:
                raise Exception("Srt download failed")
            logging.info("SRT subtitle file saved as: %s", srt_target_path)

    try:
        logging.info("Starting subtitle download for %s", url)
        await asyncio.to_thread(_download_subs)
    except Exception as e:
        logging.error(
            "Error while executing subtitles for %s (lang=%s): %s",
            url,
            lang_req,
            e,
        )
        return None



    # 4. Cleanup: remove any non-.srt files for this video id in cache folder
    prefix = f"{video_id}."
    for fname in os.listdir(cache_dir):
        if not fname.startswith(prefix):
            continue
        if not fname.endswith(".srt"):
            temp_path = os.path.join(cache_dir, fname)
            try:
                os.remove(temp_path)
                logging.info("Removed temp file: %s", temp_path)
            except OSError as e:
                logging.warning("Failed to remove temp file %s: %s", temp_path, e)

    return srt_target_path


async def main():
    # url = "https://www.youtube.com/watch?v=1sTNgmmL06Y"
    url = "https://www.youtube.com/watch?v=mn9q8pwJxsI"
    path = await fetch_srt_for_video(url, "en-orig")
    print("Got SRT:", path)

asyncio.run(main())