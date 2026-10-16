import json
import shutil
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from dotenv import load_dotenv

env_path = Path.home() / ".config" / "omnicast" / ".env"
load_dotenv(dotenv_path=env_path)

import yt_dlp
from core.database import SessionLocal
from models.db import GlobalMedia
from services.blobstore import BlobError, blob_client
from services.fetcher import AUDIO_FORMAT, _base_opts, _run_with_warp_retry
from services.storage import generate_search_aliases, is_valid_hash

AUDIO_EXTS = {".opus", ".m4a", ".mp3", ".webm", ".ogg"}
SHM_DIR = Path("/dev/shm")


def _load_existing_meta(blobs: dict) -> dict:
    meta_id = blobs.get("metadata")
    if not meta_id:
        return {}
    try:
        raw = blob_client.read_bytes(meta_id)
        return json.loads(raw.decode("utf-8"))
    except Exception as e:
        print(f"[!] Aviso: No se pudo leer el blob de metadata previa ({meta_id}): {e}")
        return {}


def replace_audio(v_hash: str, youtube_url: str) -> bool:
    if not is_valid_hash(v_hash):
        print(f"[-] Error: El hash '{v_hash}' no es un hash SHA3-256 válido (64 hex chars).")
        return False

    db = SessionLocal()
    try:
        row = db.query(GlobalMedia).filter(GlobalMedia.hash == v_hash).first()
        if not row:
            print(f"[-] Error: No existe el hash {v_hash} en la tabla global_media.")
            return False

        old_blobs = dict(row.blobs or {})
        prev_meta = _load_existing_meta(old_blobs)

        print("[*] Extrayendo información de YouTube...")
        extract_opts = {**_base_opts(), "format": AUDIO_FORMAT}

        def _extract():
            with yt_dlp.YoutubeDL(extract_opts) as ydl:
                return ydl.extract_info(youtube_url, download=False)

        try:
            info = _run_with_warp_retry(_extract)
        except Exception as e:
            print(f"[-] Error extrayendo información: {e}")
            return False

        if not info:
            print("[-] Error: No se pudo extraer información del enlace.")
            return False

        tmp_base = SHM_DIR if SHM_DIR.is_dir() else None
        workdir = Path(tempfile.mkdtemp(prefix="omnicast-px3-", dir=tmp_base))

        try:
            ydl_opts = {
                **_base_opts(),
                "format": AUDIO_FORMAT,
                "outtmpl": str(workdir / "media.%(ext)s"),
                "postprocessors": [
                    {
                        "key": "FFmpegExtractAudio",
                        "preferredcodec": "opus",
                    }
                ],
            }

            print("[*] Descargando y convirtiendo nuevo audio a .opus...")

            def _download():
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    ydl.download([youtube_url])

            _run_with_warp_retry(_download)

            new_audio = [
                f for f in workdir.glob("media.*") if f.suffix.lower() in AUDIO_EXTS
            ]
            if not new_audio:
                print("[-] Error: La descarga terminó pero no se generó archivo de audio.")
                return False

            audio_path = new_audio[0]

            kept_title = row.title or prev_meta.get("title") or info.get("title") or "Unknown"
            kept_uploader = (
                row.uploader
                or prev_meta.get("uploader")
                or info.get("uploader")
                or info.get("artist")
                or "Unknown"
            )
            extractor = (info.get("extractor_key") or info.get("extractor") or "youtube").lower()
            duration = int(info.get("duration") or row.duration or 0)
            upload_date = info.get("upload_date") or row.upload_date
            original_id = info.get("id") or row.original_id

            new_meta = {
                **prev_meta,
                "id": v_hash,
                "title": kept_title,
                "uploader": kept_uploader,
                "extractor": extractor,
                "original_id": original_id,
                "duration": duration,
                "upload_date": upload_date,
                "url": youtube_url,
                "downloaded_at": datetime.now(timezone.utc).isoformat(),
            }

            meta_path = workdir / "metadata.json"
            with open(meta_path, "w", encoding="utf-8") as f:
                json.dump(new_meta, f, indent=4, ensure_ascii=False)

            print("[*] Subiendo nuevo audio y metadata al blobstore...")
            new_media_id = None
            new_meta_id = None
            try:
                new_media_id = blob_client.upload_file(
                    audio_path, filename=f"{v_hash}{audio_path.suffix}"
                )
                new_meta_id = blob_client.upload_file(
                    meta_path, filename=f"{v_hash}.json"
                )
            except BlobError as e:
                if new_media_id is not None:
                    blob_client.delete(new_media_id)
                if new_meta_id is not None:
                    blob_client.delete(new_meta_id)
                print(f"[-] Error subiendo al blobstore: {e}")
                return False

        finally:
            shutil.rmtree(workdir, ignore_errors=True)

        updated_blobs = {
            **old_blobs,
            "media": new_media_id,
            "metadata": new_meta_id,
            "thumb": old_blobs.get("thumb"),
        }

        row.title = kept_title
        row.uploader = kept_uploader
        row.duration = duration
        row.upload_date = upload_date
        row.extractor = extractor
        row.original_id = original_id
        row.source_url = youtube_url
        row.blobs = updated_blobs
        if not row.aliases:
            row.aliases = generate_search_aliases(kept_title, kept_uploader, "")

        db.commit()
        print(f"[+] Base de datos actualizada para {v_hash} (título, autor y portada intactos).")

        old_media_id = old_blobs.get("media")
        if old_media_id and old_media_id != new_media_id:
            blob_client.delete(old_media_id)
            print(f"[i] Blob de audio anterior eliminado: {old_media_id}")

        old_meta_id = old_blobs.get("metadata")
        if old_meta_id and old_meta_id != new_meta_id:
            blob_client.delete(old_meta_id)
            print(f"[i] Blob de metadata anterior eliminado: {old_meta_id}")

        print("[+] ¡Reemplazo completado con éxito!")
        return True

    except Exception as e:
        db.rollback()
        print(f"[-] Error inesperado durante el reemplazo: {e}")
        return False
    finally:
        db.close()


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Uso: python px3.py <hash> <url_youtube>")
        sys.exit(1)

    hash_dir = sys.argv[1].strip()
    yt_url = sys.argv[2].strip()

    ok = replace_audio(hash_dir, yt_url)
    sys.exit(0 if ok else 1)