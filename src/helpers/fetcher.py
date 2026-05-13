import datetime
import json
from pathlib import Path
import yt_dlp
from src.helpers.utils import gen_hash, get_video_dir, get_metadata, get_video_file

def download_video(url: str) -> bool:
    try:
        with yt_dlp.YoutubeDL({"quiet": True, "no_warnings": True}) as ydl:
            info = ydl.extract_info(url, download=False)

        if not info:
            print("No se pudo extraer info del video")
            return False

        v_hash = gen_hash(info)
        target_dir = get_video_dir(v_hash)

        if target_dir.exists():
            meta = get_metadata(v_hash)
            if meta and get_video_file(v_hash):
                print(f"Ya existe: {meta.get('title', 'Video')}")
                return True

        target_dir.mkdir(parents=True, exist_ok=True)

        metadata = {
            "id": v_hash,
            "original_id": info.get("id"),
            "title": info.get("title", "Video Cabronsisimo"),
            "uploader": info.get("uploader"),
            "duration": info.get("duration", 0),
            "upload_date": info.get("upload_date"),
            "url": url,
            "downloaded_at": datetime.now().isoformat(),
        }

        with open(target_dir / "metadata.json", "w", encoding="utf-8") as f:
            json.dump(metadata, f, ensure_ascii=False, indent=4)

        dl_opts = {
            "quiet": True,
            "no_warnings": True,
            "writethumbnail": True,
            "writesubtitles": True,
            "writeautomaticsub": True,
            "format": "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best",
            "outtmpl": str(target_dir / "media.%(ext)s"),
            "retries": 3,
            "fragment_retries": 3,
        }

        with yt_dlp.YoutubeDL(dl_opts) as ydl_dl:
            ydl_dl.download([url])

        print(f"Descargado: {metadata['title'][:70]}...")
        return True

    except Exception as e:
        print(f"Error descargando {url}: {e}")
        return False