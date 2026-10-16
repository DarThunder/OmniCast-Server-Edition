import json
import logging
import re
import shutil
import subprocess
import tempfile
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

import httpx

from core.configs import ARIA2_RPC_URL, ARIA2_SECRET, PROWLARR_API_KEY, PROWLARR_URL
from core.database import redis_client
from services import media_repo
from services.blobstore import BlobError, blob_client
from services.fetcher import (
    DISK_TMP_DIR,
    LOCK_TTL,
    WORKDIR_PREFIX,
    FetchError,
    _discard_blobs,
    _fmt_eta,
    _fmt_speed,
    set_task,
)
from services.storage import make_hash

log = logging.getLogger("omnicast.torrent_fetcher")

VIDEO_EXTS = {".mp4", ".mkv", ".webm", ".avi", ".mov", ".m4v"}
_BTIH_RE = re.compile(r"xt=urn:btih:([a-zA-Z0-9]+)", re.IGNORECASE)
ARIA2_BASE_DIR = Path("/var/lib/aria2/downloads")

CAT_MOVIES = 2000
CAT_TV = 5000

def _resolve_prowlarr_uri(uri: str) -> str:
    if uri.startswith("magnet:"):
        return uri
    try:
        with httpx.Client(follow_redirects=False, timeout=15.0) as client:
            resp = client.get(uri)
            if resp.status_code in (301, 302, 303, 307, 308):
                loc = resp.headers.get("location", "")
                if loc.startswith("magnet:"):
                    return loc
    except Exception:
        pass
    return uri

def search_prowlarr(query: str, category: str = "all", limit: int = 25) -> list[dict]:
    if not PROWLARR_API_KEY:
        raise RuntimeError("Falta PROWLARR_API_KEY en .env")

    cats = []
    if category == "movie":
        cats = [CAT_MOVIES]
    elif category == "tv":
        cats = [CAT_TV]
    else:
        cats = [CAT_MOVIES, CAT_TV]

    params = [("query", query), ("type", "search")]
    for c in cats:
        params.append(("categories", c))

    with httpx.Client(
        base_url=PROWLARR_URL,
        headers={"X-Api-Key": PROWLARR_API_KEY},
        timeout=25.0,
    ) as client:
        resp = client.get("/api/v1/search", params=params)
        resp.raise_for_status()
        items = resp.json()

    results = []
    for it in items:
        seeders = it.get("seeders") or 0
        uri = it.get("magnetUrl") or it.get("downloadUrl")
        if seeders < 1 or not uri:
            continue

        info_hash = (it.get("infoHash") or "").lower()
        if not info_hash and uri.startswith("magnet:"):
            m = _BTIH_RE.search(uri)
            if m:
                info_hash = m.group(1).lower()

        results.append({
            "title": it.get("title") or "Sin título",
            "indexer": it.get("indexer") or "Torrent",
            "size_bytes": it.get("size") or 0,
            "seeders": seeders,
            "leechers": it.get("leechers") or 0,
            "uri": uri,
            "info_hash": info_hash,
        })

    results.sort(key=lambda x: x["seeders"], reverse=True)
    return results[:limit]

def _aria2_rpc(method: str, params: list | None = None):
    payload = {
        "jsonrpc": "2.0",
        "id": uuid.uuid4().hex,
        "method": f"aria2.{method}",
        "params": [f"token:{ARIA2_SECRET}", *(params or [])],
    }
    with httpx.Client(timeout=10.0) as client:
        resp = client.post(ARIA2_RPC_URL, json=payload)
        resp.raise_for_status()
        data = resp.json()
        if "error" in data:
            raise FetchError(f"Aria2 error: {data['error'].get('message')}")
        return data.get("result")

def _cleanup_aria2(gid: str) -> None:
    try:
        _aria2_rpc("forceRemove", [gid])
    except Exception:
        pass
    try:
        _aria2_rpc("removeDownloadResult", [gid])
    except Exception:
        pass

def _find_largest_video(workdir: Path) -> Path | None:
    candidates = [
        p for p in workdir.rglob("*")
        if p.is_file() and p.suffix.lower() in VIDEO_EXTS
    ]
    if not candidates:
        return None
    return max(candidates, key=lambda p: p.stat().st_size)

def _remux_to_mp4(src: Path, dst: Path) -> None:
    cmd = [
        "ffmpeg", "-y", "-v", "error",
        "-i", str(src),
        "-map", "0:v:0",
        "-map", "0:a:0?",
        "-c:v", "copy",
        "-c:a", "aac", "-b:a", "192k",
        "-movflags", "+faststart",
        str(dst),
    ]
    subprocess.run(cmd, check=True)

def _extract_frame_thumb(video_path: Path, thumb_path: Path) -> bool:
    for seek_sec in ("60", "5", "0"):
        cmd = [
            "ffmpeg", "-y", "-v", "error",
            "-ss", seek_sec,
            "-i", str(video_path),
            "-frames:v", "1",
            "-vf", "scale='min(1280,iw)':-1",
            "-quality", "80",
            str(thumb_path),
        ]
        res = subprocess.run(cmd)
        if res.returncode == 0 and thumb_path.exists() and thumb_path.stat().st_size > 0:
            return True
    return False

def _probe_duration(video_path: Path) -> int:
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

def download_torrent(uri: str, title: str, indexer: str = "Torrent", task_id: str | None = None) -> bool:
    workdir = ARIA2_BASE_DIR / f"task-{task_id or uuid.uuid4().hex}"
    workdir.mkdir(parents=True, exist_ok=True)

    gid = None
    lock_key = None

    try:
        set_task(task_id, status="starting", percent="0%", speed="0KiB/s", eta="Unknown")
        gid = _aria2_rpc("addUri", [[_resolve_prowlarr_uri(uri)], {"dir": str(workdir), "seed-time": "0"}])

        while True:
            st = _aria2_rpc(
                "tellStatus",
                [gid, ["gid", "status", "totalLength", "completedLength", "downloadSpeed", "infoHash", "followedBy", "errorMessage"]],
            )
            status = st.get("status")

            if st.get("followedBy"):
                _cleanup_aria2(gid)
                gid = st["followedBy"][0]
                continue

            info_hash = (st.get("infoHash") or "").lower()
            if info_hash and not lock_key:
                media_hash = make_hash("bittorrent", info_hash, "video")
                if media_repo.get_blobs(media_hash):
                    log.info("El torrent ya existe en Holder: %s", media_hash)
                    set_task(task_id, status="completed", percent="100%")
                    return True
                lock_key = f"lock:media:{media_hash}"
                if not redis_client.set(lock_key, task_id or "1", nx=True, ex=LOCK_TTL):
                    lock_key = None
                    raise FetchError("Este torrent ya se está descargando")

            if status == "complete":
                break
            if status in ("error", "removed"):
                raise FetchError(st.get("errorMessage") or "Fallo en la descarga de aria2")

            total = int(st.get("totalLength") or 0)
            done = int(st.get("completedLength") or 0)
            speed = int(st.get("downloadSpeed") or 0)
            percent = f"{min(done / total * 100, 100):.1f}%" if total > 0 else "0%"
            eta = ((total - done) // speed) if (speed > 0 and total > done) else None

            set_task(
                task_id,
                status="downloading",
                percent=percent,
                speed=_fmt_speed(speed),
                eta=_fmt_eta(eta),
            )
            time.sleep(1.5)

        info_hash = (st.get("infoHash") or uuid.uuid4().hex).lower()
        media_hash = make_hash("bittorrent", info_hash, "video")

        raw_video = _find_largest_video(workdir)
        if not raw_video:
            raise FetchError("El torrent terminó pero no contiene ningún archivo de video válido")

        set_task(task_id, status="processing", percent="100%")
        final_video = workdir / "media.mp4"
        if raw_video.suffix.lower() == ".mp4":
            raw_video.rename(final_video)
        else:
            _remux_to_mp4(raw_video, final_video)
            raw_video.unlink(missing_ok=True)

        thumb_path = workdir / "media.webp"
        has_thumb = _extract_frame_thumb(final_video, thumb_path)
        duration = _probe_duration(final_video)

        metadata = {
            "id": media_hash,
            "original_id": info_hash,
            "extractor": "bittorrent",
            "title": title,
            "uploader": indexer,
            "duration": duration,
            "upload_date": datetime.now(timezone.utc).strftime("%Y%m%d"),
            "url": uri,
            "downloaded_at": datetime.now(timezone.utc).isoformat(),
        }
        meta_path = workdir / "metadata.json"
        meta_path.write_text(json.dumps(metadata, ensure_ascii=False, indent=4), encoding="utf-8")

        set_task(task_id, status="uploading", percent="100%")
        uploaded: dict[str, int | None] = {}
        try:
            uploaded["media"] = blob_client.upload_file(final_video, filename=f"{media_hash}.mp4")
            uploaded["metadata"] = blob_client.upload_file(meta_path, filename=f"{media_hash}.json")
            uploaded["thumb"] = (
                blob_client.upload_file(thumb_path, filename=f"{media_hash}.webp")
                if has_thumb else None
            )
        except BlobError as e:
            _discard_blobs(uploaded)
            raise FetchError("Error guardando el torrent en Holder") from e

        if not media_repo.register_media(media_hash, "video", metadata, uploaded):
            _discard_blobs(uploaded)
            raise FetchError("No se pudo registrar el video en SQLite")

        set_task(task_id, status="completed", percent="100%")
        log.info("Torrent completado y subido a Holder: %s", title)
        return True

    except FetchError as e:
        log.warning("Torrent rechazado (%s): %s", title, e)
        set_task(task_id, status="error", percent="-1%", detail=str(e))
        return False
    except Exception:
        log.exception("Error inesperado descargando torrent %s", title)
        set_task(task_id, status="error", percent="-1%", detail="Error interno procesando torrent")
        return False
    finally:
        if gid:
            _cleanup_aria2(gid)
        if lock_key:
            redis_client.delete(lock_key)
        shutil.rmtree(workdir, ignore_errors=True)