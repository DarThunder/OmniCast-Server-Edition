import json
import sqlite3
import sys
from pathlib import Path
from core.database import Base, SessionLocal, engine, init_fts
from models.db import GlobalMedia
from services.blobstore import blob_client
from services.storage import generate_search_aliases

HOLDER_DB_PATH = Path("/home/darthunder/Workshop/Github/Holder/holder.db")

if not HOLDER_DB_PATH.exists():
    print(f"[-] No encontré la base de datos de holder en: {HOLDER_DB_PATH}")
    print("Ajusta HOLDER_DB_PATH al inicio del script.")
    sys.exit(1)

Base.metadata.create_all(bind=engine)
init_fts(engine)

print("[*] Leyendo archivos registrados en holder...")
h_conn = sqlite3.connect(HOLDER_DB_PATH)
h_cur = h_conn.cursor()

rows = h_cur.execute("SELECT id, filename FROM files;").fetchall()
h_conn.close()

media_groups = {}

for file_id, filename in rows:
    p = Path(filename)
    m_hash = p.stem
    ext = p.suffix.lower()
    
    if len(m_hash) != 64:
        continue
        
    entry = media_groups.setdefault(m_hash, {"thumb": None})
    if ext == ".json":
        entry["metadata"] = file_id
    elif ext in (".mp4", ".opus", ".webm", ".m4a"):
        entry["media"] = file_id
        entry["ext"] = ext
    elif ext in (".webp", ".jpg", ".png"):
        entry["thumb"] = file_id

print(f"[*] Se encontraron {len(media_groups)} contenidos en holder. Reconstruyendo SQLite...")

db = SessionLocal()
recovered = 0

try:
    for m_hash, blobs in media_groups.items():
        if "metadata" not in blobs or "media" not in blobs:
            continue
            
        try:
            raw_meta = blob_client.read_bytes(blobs["metadata"])
            meta = json.loads(raw_meta.decode("utf-8"))
        except Exception as e:
            print(f"[!] No se pudo leer metadata de {m_hash}: {e}")
            continue

        ext = blobs.get("ext", "")
        media_type = "video" if ext == ".mp4" else "music"
        title = meta.get("title") or "Sin título"
        uploader = meta.get("uploader") or ""

        blob_dict = {
            "media": blobs["media"],
            "metadata": blobs["metadata"],
            "thumb": blobs["thumb"],
        }

        row = db.query(GlobalMedia).filter(GlobalMedia.hash == m_hash).first()
        if not row:
            db.add(GlobalMedia(
                hash=m_hash,
                media_type=media_type,
                title=title,
                uploader=uploader,
                duration=int(meta.get("duration") or 0),
                upload_date=meta.get("upload_date"),
                extractor=meta.get("extractor"),
                original_id=meta.get("original_id"),
                source_url=meta.get("url"),
                blobs=blob_dict,
                aliases=generate_search_aliases(title, uploader, ""),
            ))
            recovered += 1

    db.commit()
    print(f"[+] ¡ÉXITO! Se restauraron {recovered} elementos en omnicast.db.")

except Exception as e:
    db.rollback()
    print(f"[-] Error durante la recuperación: {e}")
finally:
    db.close()