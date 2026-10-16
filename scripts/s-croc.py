# OmniCast — Personal offline media server
# Copyright (C) 2026-Present  DarThunder
# SPDX-License-Identifier: AGPL-3.0-or-later
"""
Uso, desde la raíz del proyecto:
    python -m scripts.s-croc # simulación
    python -m scripts.s-croc --apply # migra de verdad
    python -m scripts.s-croc --apply --verify # además relee cada media del holder y compara blake3
    python -m scripts.s-croc --apply --type video
"""
import argparse
import json
import logging
import sys
from pathlib import Path

import blake3

from core.configs import opts
from core.database import Base, engine, init_fts
from services import media_repo
from services.blobstore import BlobError, blob_client
from services.storage import IMAGE_EXTS, find_media_file, is_valid_hash

log = logging.getLogger("omnicast.migrate")

SOURCES = {"video": "videos_path", "music": "music_path"}


def _file_blake3(path: Path) -> str:
    h = blake3.blake3()
    with open(path, "rb") as f:
        while block := f.read(1024 * 1024):
            h.update(block)
    return h.hexdigest()


def _blob_blake3(file_id: int) -> str:
    h = blake3.blake3()
    resp = blob_client.open(file_id)
    try:
        for block in resp.iter_bytes(1024 * 1024):
            h.update(block)
    finally:
        resp.close()
    return h.hexdigest()


def _find_thumb(item_dir: Path) -> Path | None:
    for p in sorted(item_dir.iterdir()):
        if p.is_file() and p.stem == "media" and p.suffix.lower() in IMAGE_EXTS:
            return p
    return None


def migrate_dir(item_dir: Path, media_type: str, apply: bool, verify: bool) -> str:
    media_hash = item_dir.name
    if not is_valid_hash(media_hash):
        return "omitido: el nombre no es un hash"
    if media_repo.get_blobs(media_hash):
        return "ya migrado"

    media_file = find_media_file(item_dir)
    meta_path = item_dir / "metadata.json"
    if media_file is None:
        return "incompleto: sin archivo de media"
    try:
        with open(meta_path, "r", encoding="utf-8") as f:
            meta = json.load(f)
    except (OSError, ValueError) as e:
        return f"incompleto: metadata.json ilegible ({e})"

    to_upload = {"media": media_file, "metadata": meta_path}
    thumb = _find_thumb(item_dir)
    if thumb:
        to_upload["thumb"] = thumb

    if not apply:
        return f"migraría ({', '.join(to_upload)})"

    uploaded: dict[str, int] = {}
    try:
        for role, path in to_upload.items():
            uploaded[role] = blob_client.upload_file(path, filename=f"{media_hash}{path.suffix}")
        if verify and _blob_blake3(uploaded["media"]) != _file_blake3(media_file):
            raise BlobError("la verificación blake3 del media no coincide")
        uploaded.setdefault("thumb", None)
        if not media_repo.register_media(media_hash, media_type, meta, uploaded):
            raise BlobError("no se pudo registrar en la base de datos")
    except Exception as e:
        for file_id in uploaded.values():
            if file_id is not None:
                blob_client.delete(file_id)
        return f"ERROR: {e}"
    return "migrado" + (" y verificado" if verify else "")


def main(argv=None) -> int:
    Base.metadata.create_all(bind=engine)
    init_fts(engine)
    parser = argparse.ArgumentParser(description="Migra la biblioteca en disco al blob storage")
    parser.add_argument("--apply", action="store_true", help="migrar de verdad (por defecto solo simula)")
    parser.add_argument("--verify", action="store_true", help="relee cada media del holder y compara blake3")
    parser.add_argument("--type", choices=sorted(SOURCES), help="solo video o solo music")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(message)s")
    counts: dict[str, int] = {}
    errors = 0

    for media_type, setting in SOURCES.items():
        if args.type and args.type != media_type:
            continue
        base = Path(opts[setting])
        if not base.is_dir():
            print(f"[{media_type}] {base} no existe, se omite")
            continue
        for item_dir in sorted(p for p in base.iterdir() if p.is_dir() and not p.name.endswith(".tmp")):
            status = migrate_dir(item_dir, media_type, args.apply, args.verify)
            key = status.split(":")[0].split(" (")[0]
            counts[key] = counts.get(key, 0) + 1
            if status.startswith("ERROR"):
                errors += 1
            print(f"[{media_type}] {item_dir.name[:12]}…  {status}")

    print("\nResumen:", ", ".join(f"{k}={v}" for k, v in sorted(counts.items())) or "nada que hacer")
    if not args.apply:
        print("Fue una simulación; usa --apply para migrar.")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())