import hashlib
import json
from src.helpers import configs
from pathlib import Path

def gen_hash(info_video: dict):
    return hashlib.sha3_512(
        json.dumps(
            {k: v for k, v in {
                "id": info_video.get("id"),
                "duration": info_video.get("duration"),
                "upload_date": info_video.get("upload_date"),
                "timestamp": info_video.get("timestamp"),
                "channel_id": info_video.get("channel_id"),
                "channel_url": info_video.get("channel_url"),
                "uploader_id": info_video.get("uploader_id"),
                "webpage_url": info_video.get("webpage_url"),
                "extractor_key": info_video.get("extractor_key"),
                "is_live": info_video.get("is_live", False),
                "was_live": info_video.get("was_live", False),
                "availability": info_video.get("availability"),
                "live_status": info_video.get("live_status")
            }.items() if v is not None},
            sort_keys=True, 
            ensure_ascii=False
        ).encode('utf-8')
    ).hexdigest()[:64]

def get_video_dir(v_hash: str) -> Path:
    return Path(configs.opts["path"]) / v_hash

def get_video_file(v_hash: str):
    dir_path = get_video_dir(v_hash)
    if not dir_path.exists(): return None
    for file in dir_path.glob("media.*"):
        if file.suffix not in ['.webp', '.jpg', '.png', '.json']:
            return file
    return None

def get_thumbnail_file(v_hash: str):
    dir_path = get_video_dir(v_hash)
    if not dir_path.exists(): return None
    for file in dir_path.glob("media.*"):
        if file.suffix in ['.webp', '.jpg', '.png']:
            return file
    return None

def get_metadata(v_hash: str):
    meta_path = get_video_dir(v_hash) / "metadata.json"
    if meta_path.exists():
        with open(meta_path, "r", encoding="utf-8") as f:
            return json.load(f)
    return None

def get_all_videos():
    store_path = Path(configs.opts["path"])
    videos = []
    if store_path.exists():
        for d in store_path.iterdir():
            if d.is_dir():
                meta = get_metadata(d.name)
                if meta:
                    videos.append(meta)
    return videos