import argparse
import json
import os
import shutil
import sqlite3
import sys
import tempfile
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from sqlalchemy import create_engine, event, insert

from ..src.core import configs
from ..src.core.database import Base
from ..src.models import db as m
from ..src.services.storage import find_media_file, make_hash

HOST_EXTRACTORS = {
    "youtube.com": "youtube",
    "youtu.be": "youtube",
    "soundcloud.com": "soundcloud",
}

@dataclass
class Item:
    media_type: str
    old_hash: str
    new_hash: str
    old_dir: Path
    new_dir: Path
    meta: dict
    extractor: str

def read_json(path: Path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def write_json_atomic(path: Path, data: dict) -> None:
    tmp = path.with_name(path.name + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=4)
    os.replace(tmp, path)


def infer_extractor(meta: dict):
    if meta.get("extractor"):
        return str(meta["extractor"]).lower()
    host = (urlparse(meta.get("url") or "").hostname or "").lower()
    for domain, extractor in HOST_EXTRACTORS.items():
        if host == domain or host.endswith("." + domain):
            return extractor
    return None


def to_naive_utc(value, assume_local: bool):
    if value in (None, ""):
        return None
    try:
        dt = value if isinstance(value, datetime) else datetime.fromisoformat(str(value))
    except ValueError:
        return None
    if dt.tzinfo is None and assume_local:
        dt = dt.astimezone()
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt


def utc_now_naive() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)

def registered_hashes(db_path: Path) -> set:
    if not db_path.exists():
        return set()
    con = sqlite3.connect(f"{db_path.as_uri()}?mode=ro", uri=True)
    try:
        return {row[0] for row in con.execute("SELECT hash FROM global_media")}
    except sqlite3.OperationalError:
        return set()
    finally:
        con.close()


def scan(registered: set):
    items: list[Item] = []
    problems: list[tuple[Path, str]] = []
    by_old: dict[str, dict[str, str]] = defaultdict(dict)
    winners: dict[tuple[str, str], Item] = {}

    for media_type, base in (
        ("video", Path(configs.opts["videos_path"])),
        ("music", Path(configs.opts["music_path"])),
    ):
        if not base.is_dir():
            continue
        for d in sorted(base.iterdir(), key=lambda p: (p.name not in registered, p.name)):
            if not d.is_dir():
                continue
            if d.name.endswith(".tmp"):
                problems.append((d, "descarga incompleta (.tmp); se deja intacta"))
                continue
            meta = read_json(d / "metadata.json")
            if not isinstance(meta, dict):
                problems.append((d, "metadata.json ausente o ilegible"))
                continue
            if find_media_file(d) is None:
                problems.append((d, "no tiene archivo de media (descarga incompleta)"))
                continue
            extractor = infer_extractor(meta)
            media_id = meta.get("original_id")
            if not extractor or not media_id:
                problems.append((d, "no se pudo deducir extractor/id"))
                continue

            new_hash = make_hash(extractor, media_id, media_type)
            new_dir = base / new_hash
            if new_dir.exists() and new_dir != d:
                problems.append((d, "el directorio de destino ya existe"))
                continue

            item = Item(media_type, d.name, new_hash, d, new_dir, meta, extractor)
            winner = winners.get((media_type, new_hash))
            if winner is not None:
                problems.append((d, f"duplicado de {winner.old_dir.name}; se deja intacto"))
                by_old[d.name][media_type] = new_hash
                continue
            winners[(media_type, new_hash)] = item
            items.append(item)
            by_old[d.name][media_type] = new_hash

    return items, problems, by_old

def already_migrated(db_path: Path) -> bool:
    if not db_path.exists():
        return False
    con = sqlite3.connect(f"{db_path.as_uri()}?mode=ro", uri=True)
    try:
        row = con.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name='favorites'"
        ).fetchone()
    finally:
        con.close()
    return bool(row and row[0] and "uq_favorites_user_media" in row[0])


def build_new_db(new_path: Path, items, by_old, old_path: Path) -> dict:
    if new_path.exists():
        new_path.unlink()

    old = None
    if old_path.exists():
        old = sqlite3.connect(f"{old_path.as_uri()}?mode=ro", uri=True)
        old.row_factory = sqlite3.Row

    def rows(table: str) -> list[dict]:
        if old is None:
            return []
        try:
            return [dict(r) for r in old.execute(f"SELECT * FROM {table}").fetchall()]
        except sqlite3.OperationalError:
            return []

    def resolve(old_hash):
        candidates = by_old.get(old_hash) or {}
        return candidates.get("video") or candidates.get("music")

    engine = create_engine(f"sqlite:///{new_path}")

    @event.listens_for(engine, "connect")
    def _fk_on(dbapi_conn, _):
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA foreign_keys=ON")
        cur.close()

    print("BASE PX9:", id(Base))
    print("BASE USER:", id(m.User.metadata))
    print("TABLAS:", list(Base.metadata.tables.keys()))
    Base.metadata.create_all(engine)
    stats: dict[str, int] = defaultdict(int)

    def put(conn, model, data):
        if data:
            conn.execute(insert(model.__table__), data)

    try:
        with engine.begin() as conn:
            users = rows("users")
            user_ids = {u["id"] for u in users}
            put(conn, m.User, [
                {"id": u["id"], "username": u["username"],
                 "hashed_password": u["hashed_password"], "bio": u.get("bio")}
                for u in users
            ])
            stats["usuarios"] = len(users)

            old_media = {r["hash"]: r for r in rows("global_media")}
            media_rows = []
            for it in items:
                old_row = old_media.get(it.old_hash)
                added = None
                if old_row and old_row.get("media_type") == it.media_type:
                    added = to_naive_utc(old_row.get("added_at"), True)
                added = (
                    added
                    or to_naive_utc(it.meta.get("downloaded_at"), True)
                    or utc_now_naive()
                )
                media_rows.append({
                    "hash": it.new_hash,
                    "title": it.meta.get("title") or (old_row or {}).get("title"),
                    "uploader": it.meta.get("uploader") or (old_row or {}).get("uploader"),
                    "media_type": it.media_type,
                    "added_at": added,
                })
            put(conn, m.GlobalMedia, media_rows)
            stats["media"] = len(media_rows)
            stats["filas_global_media_sin_archivos"] = sum(
                1 for h in old_media if h not in by_old
            )

            kept: dict[tuple, int] = {}
            pl_map: dict[int, int] = {}
            pl_rows = []
            for p in sorted(rows("playlists"), key=lambda r: r["id"]):
                if p["user_id"] not in user_ids or not p.get("name"):
                    stats["playlists_descartadas"] += 1
                    continue
                key = (p["user_id"], p["name"])
                if key in kept:
                    pl_map[p["id"]] = kept[key]
                    stats["playlists_fusionadas"] += 1
                    continue
                kept[key] = p["id"]
                pl_map[p["id"]] = p["id"]
                pl_rows.append({"id": p["id"], "user_id": p["user_id"], "name": p["name"]})
            put(conn, m.Playlist, pl_rows)
            stats["playlists"] = len(pl_rows)

            fav_rows, seen = [], set()
            for f in rows("favorites"):
                new_h = resolve(f["media_hash"])
                if f["user_id"] not in user_ids or new_h is None:
                    stats["favoritos_descartados"] += 1
                    continue
                if (f["user_id"], new_h) in seen:
                    stats["favoritos_duplicados"] += 1
                    continue
                seen.add((f["user_id"], new_h))
                fav_rows.append({"user_id": f["user_id"], "media_hash": new_h})
            put(conn, m.Favorite, fav_rows)
            stats["favoritos"] = len(fav_rows)

            per_playlist: dict[int, list[str]] = {}
            seen = set()
            old_items = sorted(
                rows("playlist_items"),
                key=lambda r: (r["playlist_id"], r.get("position") or 0, r["id"]),
            )
            for it in old_items:
                pid = pl_map.get(it["playlist_id"])
                new_h = resolve(it["media_hash"])
                if pid is None or new_h is None:
                    stats["items_playlist_descartados"] += 1
                    continue
                if (pid, new_h) in seen:
                    stats["items_playlist_duplicados"] += 1
                    continue
                seen.add((pid, new_h))
                per_playlist.setdefault(pid, []).append(new_h)
            item_rows = [
                {"playlist_id": pid, "media_hash": h, "position": pos}
                for pid, hashes in per_playlist.items()
                for pos, h in enumerate(hashes)
            ]
            put(conn, m.PlaylistItem, item_rows)
            stats["items_playlist"] = len(item_rows)

            best: dict[tuple, dict] = {}
            for h in rows("playback_history"):
                new_h = resolve(h["media_hash"])
                if h["user_id"] not in user_ids or new_h is None:
                    stats["historial_descartado"] += 1
                    continue
                updated = to_naive_utc(h.get("updated_at"), False) or utc_now_naive()
                key = (h["user_id"], new_h)
                if key in best and best[key]["updated_at"] >= updated:
                    stats["historial_duplicado"] += 1
                    continue
                if key in best:
                    stats["historial_duplicado"] += 1
                best[key] = {
                    "user_id": h["user_id"], "media_hash": new_h,
                    "position_ms": h.get("position_ms") or 0, "updated_at": updated,
                }
            put(conn, m.PlaybackHistory, list(best.values()))
            stats["historial"] = len(best)

            logs = rows("audit_logs")
            put(conn, m.AuditLog, [
                {"id": a["id"],
                 "user_id": a["user_id"] if a.get("user_id") in user_ids else None,
                 "action": a.get("action"), "details": a.get("details"),
                 "timestamp": to_naive_utc(a.get("timestamp"), True) or utc_now_naive()}
                for a in logs
            ])
            stats["auditoria"] = len(logs)

            tasks = [t for t in rows("download_tasks") if t.get("user_id") in user_ids]
            put(conn, m.DownloadTask, [
                {"id": t["id"], "user_id": t["user_id"], "url": t.get("url"),
                 "media_type": t.get("media_type"), "status": t.get("status"),
                 "created_at": to_naive_utc(t.get("created_at"), True) or utc_now_naive()}
                for t in tasks
            ])
            stats["tareas"] = len(tasks)
    finally:
        engine.dispose()
        if old is not None:
            old.close()
    return dict(stats)

def backup_db(db_path: Path) -> Path:
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup_path = db_path.with_name(f"{db_path.name}.bak-{stamp}")
    src = sqlite3.connect(db_path)
    dst = sqlite3.connect(backup_path)
    try:
        src.backup(dst)
    finally:
        dst.close()
        src.close()
    return backup_path


def rename_dirs(items) -> None:
    done: list[tuple[Item, bytes | None]] = []
    try:
        for it in items:
            original = None
            meta_path = it.old_dir / "metadata.json"
            if meta_path.exists():
                original = meta_path.read_bytes()
            if it.old_dir != it.new_dir:
                it.old_dir.rename(it.new_dir)
            done.append((it, original))
            meta = dict(it.meta)
            meta["id"] = it.new_hash
            meta["extractor"] = it.extractor
            write_json_atomic(it.new_dir / "metadata.json", meta)
    except Exception:
        for it, original in reversed(done):
            if it.new_dir.exists() and it.old_dir != it.new_dir:
                it.new_dir.rename(it.old_dir)
            if original is not None:
                (it.old_dir / "metadata.json").write_bytes(original)
        raise


def print_report(items, problems, stats) -> None:
    videos = sum(1 for i in items if i.media_type == "video")
    print(f"\nMedia a migrar: {videos} videos, {len(items) - videos} canciones")
    if problems:
        print(f"\nDirectorios que NO se migran ({len(problems)}) — revísalos a mano:")
        for path, reason in problems:
            print(f"  - {path}: {reason}")
    print("\nBase de datos nueva:")
    for key, value in sorted(stats.items()):
        print(f"  {key}: {value}")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Migra los hashes de los archivos multimedia de OmniCast"
    )
    parser.add_argument("--apply", action="store_true", help="aplicar los cambios")
    args = parser.parse_args()

    db_path = Path(configs.DB_PATH)
    if already_migrated(db_path):
        print("La base de datos ya tiene el esquema nuevo: no hay nada que migrar.")
        return 0

    items, problems, by_old = scan(registered_hashes(db_path))

    if args.apply:
        new_db = db_path.with_name(db_path.name + ".new")
        scratch = None
    else:
        scratch = Path(tempfile.mkdtemp(prefix="omnicast-migrate-"))
        new_db = scratch / "preview.db"

    try:
        stats = build_new_db(new_db, items, by_old, db_path)
        print_report(items, problems, stats)

        if not args.apply:
            print("\nSimulación: no se cambió nada. Para aplicar: python migrate_hashes.py --apply")
            return 0

        backup = backup_db(db_path) if db_path.exists() else None
        rename_dirs(items)

        for suffix in ("-wal", "-shm"):
            Path(str(db_path) + suffix).unlink(missing_ok=True)
        os.replace(new_db, db_path)

        map_path = db_path.with_name("hash_migration_map.json")
        with open(map_path, "w", encoding="utf-8") as f:
            json.dump(
                [{"type": i.media_type, "old": i.old_hash, "new": i.new_hash} for i in items],
                f, indent=2,
            )
        print(f"\nMigración aplicada. Mapa de hashes: {map_path}")
        if backup:
            print(f"Respaldo de la BD anterior: {backup}")
        return 0
    finally:
        if scratch is not None:
            shutil.rmtree(scratch, ignore_errors=True)
        elif new_db.exists():
            new_db.unlink()


if __name__ == "__main__":
    sys.exit(main())