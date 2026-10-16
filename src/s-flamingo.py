# ingest_existing.py
import hashlib
import json
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from services import media_repo
from services.blobstore import blob_client
from services.storage import make_hash


def extract_thumb(video_path: Path, thumb_path: Path) -> bool:
    for sec in ("60", "5", "0"):
        cmd = [
            "ffmpeg", "-y", "-v", "error",
            "-ss", sec, "-i", str(video_path),
            "-frames:v", "1",
            "-vf", "scale='min(1280,iw)':-1",
            "-quality", "80",
            str(thumb_path),
        ]
        if subprocess.run(cmd).returncode == 0 and thumb_path.exists() and thumb_path.stat().st_size > 0:
            return True
    return False


def probe_duration(video_path: Path) -> int:
    cmd = [
        "ffprobe", "-v", "error",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        str(video_path),
    ]
    try:
        res = subprocess.run(cmd, capture_output=True, text=True, check=True)
        return int(float(res.stdout.strip()))
    except Exception:
        return 0


def ingest_local_video(video_path: Path, title: str, uploader: str = "Local") -> str:
    if not video_path.exists():
        raise FileNotFoundError(f"No existe el archivo: {video_path}")

    raw_id = hashlib.sha256(f"{video_path.name}:{video_path.stat().st_size}".encode()).hexdigest()[:24]
    media_hash = make_hash("local_import", raw_id, "video")

    if media_repo.get_blobs(media_hash):
        print(f"[*] El video ya está registrado en OmniCast con hash: {media_hash}")
        return media_hash

    with tempfile.TemporaryDirectory(prefix="omnicast-ingest-") as tmp:
        workdir = Path(tmp)
        thumb_path = workdir / "thumb.webp"
        has_thumb = extract_thumb(video_path, thumb_path)
        duration = probe_duration(video_path)

        metadata = {
            "id": media_hash,
            "original_id": raw_id,
            "extractor": "local_import",
            "title": title,
            "uploader": uploader,
            "duration": duration,
            "upload_date": datetime.now(timezone.utc).strftime("%Y%m%d"),
            "url": f"file://{video_path.name}",
            "downloaded_at": datetime.now(timezone.utc).isoformat(),
        }
        meta_path = workdir / "metadata.json"
        meta_path.write_text(json.dumps(metadata, ensure_ascii=False, indent=4), encoding="utf-8")

        print(f"[*] Subiendo {video_path.name} a Holder (FastCDC + BLAKE3)...")
        uploaded = {
            "media": blob_client.upload_file(video_path, filename=f"{media_hash}.mp4"),
            "metadata": blob_client.upload_file(meta_path, filename=f"{media_hash}.json"),
            "thumb": blob_client.upload_file(thumb_path, filename=f"{media_hash}.webp") if has_thumb else None,
        }

        if not media_repo.register_media(media_hash, "video", metadata, uploaded):
            raise RuntimeError("Error registrando el medio en SQLite")

        print(f"[+] ¡Ingesta completada! Hash en OmniCast: {media_hash}")
        return media_hash


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Uso: python ingest_existing.py <ruta_al_mp4> <titulo>")
        sys.exit(1)

    path = Path(sys.argv[1])
    title = sys.argv[2]
    ingest_local_video(path, title)