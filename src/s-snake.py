# ingest_opus.py
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

MEDIA_TYPE = "music"

def probe(audio_path: Path) -> dict:
    cmd = [
        "ffprobe", "-v", "error",
        "-show_entries", "format=duration:format_tags=title,artist",
        "-of", "json",
        str(audio_path),
    ]
    try:
        res = subprocess.run(cmd, capture_output=True, text=True, check=True)
        fmt = json.loads(res.stdout).get("format", {})
        tags = {k.lower(): v for k, v in (fmt.get("tags") or {}).items()}
        return {
            "duration": int(float(fmt.get("duration") or 0)),
            "title": tags.get("title"),
            "artist": tags.get("artist"),
        }
    except Exception:
        return {"duration": 0, "title": None, "artist": None}


def make_thumb(image_path: Path, thumb_path: Path) -> bool:
    cmd = [
        "ffmpeg", "-y", "-v", "error",
        "-i", str(image_path),
        "-frames:v", "1",
        "-vf", "scale='min(1280,iw)':-1",
        "-quality", "80",
        str(thumb_path),
    ]
    return (
        subprocess.run(cmd).returncode == 0
        and thumb_path.exists()
        and thumb_path.stat().st_size > 0
    )


def ingest_local_opus(
    audio_path: Path,
    title: str | None = None,
    uploader: str | None = None,
    cover_path: Path | None = None,
) -> str:
    if not audio_path.is_file():
        raise FileNotFoundError(f"No existe el archivo: {audio_path}")
    if audio_path.suffix.lower() != ".opus":
        raise ValueError(f"Se esperaba un .opus, recibido '{audio_path.suffix}'")
    if cover_path is not None and not cover_path.is_file():
        raise FileNotFoundError(f"No existe la portada: {cover_path}")

    raw_id = hashlib.sha256(f"{audio_path.name}:{audio_path.stat().st_size}".encode()).hexdigest()[:24]
    media_hash = make_hash("local_import", raw_id, MEDIA_TYPE)

    if media_repo.get_blobs(media_hash):
        print(f"[*] El audio ya está registrado en OmniCast con hash: {media_hash}")
        return media_hash

    info = probe(audio_path)
    title = title or info["title"] or audio_path.stem
    uploader = uploader or info["artist"] or "Local"

    with tempfile.TemporaryDirectory(prefix="omnicast-ingest-") as tmp:
        workdir = Path(tmp)

        thumb_path = workdir / "thumb.webp"
        has_thumb = bool(cover_path) and make_thumb(cover_path, thumb_path)
        if cover_path and not has_thumb:
            print("[!] Aviso: no se pudo generar la miniatura; se ingesta sin portada.")

        metadata = {
            "id": media_hash,
            "original_id": raw_id,
            "extractor": "local_import",
            "title": title,
            "uploader": uploader,
            "duration": info["duration"],
            "upload_date": datetime.now(timezone.utc).strftime("%Y%m%d"),
            "url": f"file://{audio_path.name}",
            "downloaded_at": datetime.now(timezone.utc).isoformat(),
        }
        meta_path = workdir / "metadata.json"
        meta_path.write_text(json.dumps(metadata, ensure_ascii=False, indent=4), encoding="utf-8")

        print(f"[*] Subiendo {audio_path.name} a Holder (FastCDC + BLAKE3)...")
        uploaded = {
            "media": blob_client.upload_file(audio_path, filename=f"{media_hash}.opus"),
            "metadata": blob_client.upload_file(meta_path, filename=f"{media_hash}.json"),
            "thumb": blob_client.upload_file(thumb_path, filename=f"{media_hash}.webp") if has_thumb else None,
        }

        if not media_repo.register_media(media_hash, MEDIA_TYPE, metadata, uploaded):
            for bid in uploaded.values():
                if bid is not None:
                    try:
                        blob_client.delete(bid)
                    except Exception:
                        pass
            raise RuntimeError("Error registrando el medio en SQLite")

        print(f"[+] ¡Ingesta completada! Hash en OmniCast: {media_hash}")
        return media_hash


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Uso: python ingest_opus.py <ruta_al_opus> [titulo] [uploader] [ruta_portada]")
        sys.exit(1)

    path = Path(sys.argv[1]).expanduser()
    title = sys.argv[2] if len(sys.argv) > 2 else None
    uploader = sys.argv[3] if len(sys.argv) > 3 else None
    cover = Path(sys.argv[4]).expanduser() if len(sys.argv) > 4 else None
    ingest_local_opus(path, title, uploader, cover)