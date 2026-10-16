import json
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from dotenv import load_dotenv

env_path = Path.home() / ".config" / "omnicast" / ".env"
load_dotenv(dotenv_path=env_path)

from core.database import SessionLocal
from models.db import GlobalMedia
from services.blobstore import BlobError, blob_client
from services.storage import generate_search_aliases, is_valid_hash

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


def _probe_duration(path: Path):
    try:
        out = subprocess.run(
            [
                "ffprobe", "-v", "error",
                "-show_entries", "format=duration",
                "-of", "default=noprint_wrappers=1:nokey=1",
                str(path),
            ],
            capture_output=True, text=True, timeout=30, check=True,
        ).stdout.strip()
        return int(round(float(out)))
    except Exception:
        return None


def replace_audio_local(v_hash: str, opus_path: Path) -> bool:
    if not is_valid_hash(v_hash):
        print(f"[-] Error: El hash '{v_hash}' no es un hash SHA3-256 válido (64 hex chars).")
        return False

    if not opus_path.is_file():
        print(f"[-] Error: No existe el archivo '{opus_path}'.")
        return False
    if opus_path.suffix.lower() != ".opus":
        print(f"[-] Error: Se esperaba un archivo .opus, recibido '{opus_path.suffix}'.")
        return False

    db = SessionLocal()
    new_media_id = None
    new_meta_id = None
    try:
        row = db.query(GlobalMedia).filter(GlobalMedia.hash == v_hash).first()
        if not row:
            print(f"[-] Error: No existe el hash {v_hash} en la tabla global_media.")
            return False

        old_blobs = dict(row.blobs or {})
        prev_meta = _load_existing_meta(old_blobs)

        duration = _probe_duration(opus_path) or row.duration or prev_meta.get("duration") or 0

        new_meta = {
            **prev_meta,
            "id": v_hash,
            "title": row.title or prev_meta.get("title") or "Unknown",
            "uploader": row.uploader or prev_meta.get("uploader") or "Unknown",
            "duration": int(duration),
            "replaced_at": datetime.now(timezone.utc).isoformat(),
        }

        tmp_base = SHM_DIR if SHM_DIR.is_dir() else None
        workdir = Path(tempfile.mkdtemp(prefix="omnicast-px3-", dir=tmp_base))
        try:
            meta_path = workdir / "metadata.json"
            with open(meta_path, "w", encoding="utf-8") as f:
                json.dump(new_meta, f, indent=4, ensure_ascii=False)

            print("[*] Subiendo nuevo audio y metadata al blobstore...")
            try:
                new_media_id = blob_client.upload_file(
                    opus_path, filename=f"{v_hash}.opus"
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

        row.duration = int(duration)
        row.blobs = {
            **old_blobs,
            "media": new_media_id,
            "metadata": new_meta_id,
            "thumb": old_blobs.get("thumb"),
        }
        if not row.aliases:
            row.aliases = generate_search_aliases(
                row.title or "Unknown", row.uploader or "Unknown", ""
            )

        db.commit()
        print(f"[+] Base de datos actualizada para {v_hash} (título, autor, portada y URL de origen intactos).")

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
        for bid in (new_media_id, new_meta_id):
            if bid is not None:
                try:
                    blob_client.delete(bid)
                except Exception:
                    pass
        print(f"[-] Error inesperado durante el reemplazo: {e}")
        return False
    finally:
        db.close()


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Uso: python px3_local.py <hash> <ruta_al_archivo.opus>")
        sys.exit(1)

    hash_dir = sys.argv[1].strip()
    local_opus = Path(sys.argv[2].strip()).expanduser().resolve()

    ok = replace_audio_local(hash_dir, local_opus)
    sys.exit(0 if ok else 1)