# OmniCast — Personal offline media server
# Copyright (C) 2026-Present  DarThunder
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Valida de punta a punta OmniCast -> holder contra un servidor EN MARCHA.

Uso:
    export OMNICAST_PASSWORD=...        # o se pide por teclado; nunca por argumento
    python scripts/validate_flow.py --user darth
    python scripts/validate_flow.py --user darth --url http://127.0.0.1:8000

Opciones útiles:
    --register                     crea el usuario si no existe
    --video HASH --music HASH      probar items concretos (por defecto, los más nuevos del feed)
    --aborts N                     streams cortados a media reproducción (por defecto 40)
    --download-video URL           además pide una descarga real y la valida (tarda)
    --download-music URL

Solo lee, salvo: crea y borra una playlist temporal "smoke-xxxxxx", y las
descargas que pidas explícitamente (esas se quedan: no hay endpoint para borrarlas).
Sale con código 1 si algo falla.
"""
import argparse
import getpass
import os
import re
import secrets
import sys
import time

import httpx

DEFAULT_URL = os.getenv("OMNICAST_URL", "http://127.0.0.1:8082")

class Report:
    def __init__(self):
        self.ok_n = self.fail_n = self.skip_n = 0

    def ok(self, msg):
        self.ok_n += 1
        print(f"  OK    {msg}")

    def fail(self, msg):
        self.fail_n += 1
        print(f"  FAIL  {msg}")

    def skip(self, msg):
        self.skip_n += 1
        print(f"  SKIP  {msg}")

R = Report()

def check(cond, msg, detail=""):
    if cond:
        R.ok(msg)
    else:
        R.fail(msg + (f"  [{detail}]" if detail else ""))
    return bool(cond)

def section(title):
    print(f"\n== {title}")

def parse_cr(value):
    m = re.fullmatch(r"bytes (\d+)-(\d+)/(\d+)", value or "")
    return tuple(int(x) for x in m.groups()) if m else None

def read_prefix(client, path, n, **kw):
    with client.stream("GET", path, **kw) as r:
        buf = bytearray()
        for chunk in r.iter_bytes(65536):
            buf += chunk
            if len(buf) >= n:
                break
        return r.status_code, r.headers, bytes(buf[:n])

def login(client, user, password, register):
    section("Auth")
    r = client.post("/token", data={"username": user, "password": password})
    if r.status_code == 401 and register:
        rr = client.post("/register", json={"username": user, "password": password})
        print(f"  ...   register -> {rr.status_code}")
        r = client.post("/token", data={"username": user, "password": password})
    if not check(r.status_code == 200, "login (/token)", f"{r.status_code} {r.text[:120]}"):
        return None
    body = r.json()
    check(body.get("token_type") == "bearer" and body.get("access_token") and body.get("refresh_token"),
          "login devuelve access y refresh token")

    anon = httpx.Client(base_url=str(client.base_url), timeout=15)
    try:
        r = anon.get("/feed")
        check(r.status_code == 401, "sin token -> 401", str(r.status_code))
        r = anon.get("/feed", headers={"Authorization": "Bearer basura"})
        detail = r.json().get("detail") if r.headers.get("content-type", "").startswith("application/json") else None
        check(r.status_code == 401 and isinstance(detail, dict) and detail.get("error") == "token_expired"
              and detail.get("nonce"), "token inválido -> 401 token_expired con nonce", f"{r.status_code} {r.text[:120]}")
    finally:
        anon.close()

    client.headers["Authorization"] = f"Bearer {body['access_token']}"
    r = client.get("/feed", params={"limit": 1})
    check(r.status_code == 200, "token válido -> /feed 200", str(r.status_code))
    print("  ...   el refresh con firma Ed25519 NO se prueba aquí")
    return body
def newest(client, media_type):
    r = client.get("/feed", params={"media_type": media_type, "limit": 1})
    if r.status_code != 200:
        R.fail(f"/feed?media_type={media_type} -> {r.status_code}")
        return None
    items = r.json().get("feed", [])
    return items[0] if items else None

def check_feed(client):
    section("Feed y biblioteca")
    r = client.get("/feed", params={"limit": 5})
    body = r.json() if r.status_code == 200 else {}
    check(r.status_code == 200 and isinstance(body.get("feed"), list) and "next_skip" in body,
          "/feed con forma {feed, next_skip}", f"{r.status_code}")
    feed = body.get("feed", [])
    if feed:
        keys = {"id", "title", "duration", "downloaded_at"}
        check(keys <= set(feed[0]), "items del feed con id, title, duration, downloaded_at",
              f"faltan {keys - set(feed[0])}")
        if feed[0].get("downloaded_at"):
            check(re.search(r"(Z|[+-]\d\d:\d\d)$", feed[0]["downloaded_at"]) is not None,
                  "downloaded_at lleva zona horaria", feed[0]["downloaded_at"])
    else:
        R.skip("el feed está vacío: descarga o migra algo primero")
    r = client.get("/feed/library", params={"media_type": "music"})
    check(r.status_code == 200 and isinstance(r.json().get("library"), list), "/feed/library")

def check_stream(client, kind, h, label):
    route = f"/{kind}/{h}"
    t0 = time.monotonic()
    r = client.get(route, headers={"Range": "bytes=0-4095"})
    cr = parse_cr(r.headers.get("content-range"))
    if not check(r.status_code == 206 and cr, f"{label}: Range 0-4095 -> 206 con Content-Range",
                 f"{r.status_code} {r.headers.get('content-range')}"):
        return None
    total = cr[2]
    head = r.content
    check(cr[0] == 0 and len(head) == cr[1] - cr[0] + 1 == min(4096, total)
          and int(r.headers.get("content-length", -1)) == len(head),
          f"{label}: Content-Length y cuerpo coinciden con el rango", f"{len(head)} bytes, {cr}")
    check(r.headers.get("accept-ranges") == "bytes", f"{label}: Accept-Ranges: bytes")
    print(f"  ...   {label}: {total / 1024 / 1024:.1f} MiB, primer byte en {time.monotonic() - t0:.2f}s")

    ctype = r.headers.get("content-type", "")
    if kind == "music":
        check(head[:4] == b"OggS", f"{label}: el audio empieza con OggS (no está corrupto)", repr(head[:8]))
    elif ctype == "video/mp4":
        check(head[4:8] == b"ftyp", f"{label}: el mp4 tiene 'ftyp' en el arranque", repr(head[:12]))
    else:
        R.skip(f"{label}: tipo {ctype or '?'}, sin chequeo de cabecera")

    if total > 2048:
        r = client.get(route, headers={"Range": "bytes=-1024"})
        cr2 = parse_cr(r.headers.get("content-range"))
        check(r.status_code == 206 and cr2 and cr2[1] == total - 1 and len(r.content) == 1024,
              f"{label}: Range de sufijo (últimos 1024)", f"{r.status_code} {r.headers.get('content-range')}")

        mid = total // 2
        a = client.get(route, headers={"Range": f"bytes={mid}-{mid + 1023}"})
        b = client.get(route, headers={"Range": f"bytes={mid}-{mid + 1023}"})
        check(a.status_code == 206 and a.content == b.content and len(a.content) == 1024,
              f"{label}: seek a la mitad es estable y del tamaño pedido")

    status, hdrs, prefix = read_prefix(client, route, 4096)
    check(status == 200 and prefix == head and int(hdrs.get("content-length", -1)) == total,
          f"{label}: GET completo (200) coincide con el rango inicial y con el tamaño total",
          f"{status} {hdrs.get('content-length')} vs {total}")

    r = client.get(route, headers={"Range": f"bytes={total + 1000}-"})
    check(r.status_code == 416 and (r.headers.get("content-range") or "").endswith(f"/{total}"),
          f"{label}: Range fuera de rango -> 416 con Content-Range", f"{r.status_code} {r.headers.get('content-range')}")
    return total

def check_wrong_route(client, video, music):
    if video:
        r = client.get(f"/music/{video['id']}", headers={"Range": "bytes=0-9"})
        check(r.status_code == 404, "un video por /music -> 404", str(r.status_code))
    if music:
        r = client.get(f"/video/{music['id']}", headers={"Range": "bytes=0-9"})
        check(r.status_code == 404, "una canción por /video -> 404", str(r.status_code))
    r = client.get("/video/no-es-un-hash")
    check(r.status_code == 404, "hash inválido -> 404", str(r.status_code))

def check_aborts(client, kind, h, total, n):
    if total is None or total < 1024 * 1024:
        R.skip("cortes: se necesita un archivo de al menos 1 MiB")
        return
    route = f"/{kind}/{h}"
    t0 = time.monotonic()
    for _ in range(n):
        with client.stream("GET", route, headers={"Range": "bytes=0-"}) as r:
            next(r.iter_bytes(65536))
    t1 = time.monotonic()
    r = client.get(route, headers={"Range": "bytes=0-9"})
    dt = time.monotonic() - t1
    check(r.status_code == 206 and len(r.content) == 10 and dt < 5,
          f"{n} streams cortados a media reproducción y el servidor sigue sirviendo",
          f"{r.status_code}, {dt:.1f}s")
    print(f"  ...   {n} cortes en {t1 - t0:.1f}s, siguiente petición en {dt:.2f}s")

def check_thumbnail(client, h, label):
    r = client.get(f"/thumbnail/{h}")
    if r.status_code == 404:
        R.skip(f"{label}: sin portada (404)")
        return
    check(r.status_code == 200 and r.headers.get("content-type", "").startswith("image/") and len(r.content) > 0
          and int(r.headers.get("content-length", -1)) == len(r.content),
          f"{label}: /thumbnail 200 con imagen completa", f"{r.status_code} {r.headers.get('content-type')}")

def check_download_music(client, h):
    status, hdrs, prefix = read_prefix(client, f"/music/{h}/download", 4)
    cd = hdrs.get("content-disposition", "")
    check(status == 200 and cd.startswith("attachment") and "filename*=UTF-8''" in cd and ".opus" in cd
          and prefix == b"OggS", "música: /download con Content-Disposition y audio válido",
          f"{status} {cd[:80]}")

def check_search(client, item, label):
    word = next((w for w in re.findall(r"\w+", item.get("title") or "") if len(w) >= 3), None)
    if not word:
        R.skip(f"{label}: el título no tiene una palabra buscable")
        return
    r = client.get("/search", params={"q": word})
    body = r.json() if r.status_code == 200 else []
    check(r.status_code == 200 and any(x.get("id") == item["id"] for x in body),
          f"{label}: /search '{word}' lo encuentra", f"{r.status_code} {len(body)} resultados")
    if body:
        check("blobs" not in body[0], f"{label}: /search no expone ids internos de blobs")

def check_playlists(client, video, music):
    section("Playlists y favoritos")
    items = [x for x in (video, music) if x]
    if not items:
        R.skip("playlists: no hay items")
        return
    name = f"smoke-{secrets.token_hex(3)}"
    r = client.post("/users/me/playlists", json={"name": name, "description": "validate_flow"})
    if not check(r.status_code == 200 and r.json().get("id"), "crear playlist temporal", f"{r.status_code} {r.text[:100]}"):
        return
    pid = r.json()["id"]
    try:
        for it in items:
            r = client.post(f"/users/me/playlists/{pid}/items/{it['id']}")
            check(r.status_code == 200, f"añadir {it['id'][:10]}…", f"{r.status_code} {r.text[:100]}")

        r = client.get(f"/users/me/playlists/{pid}")
        d = r.json() if r.status_code == 200 else {}
        check([i.get("id") for i in d.get("items", [])] == [i["id"] for i in items]
              and d.get("item_count") == len(items), "detalle: items en orden y con conteo correcto",
              f"{r.status_code} {[i.get('id', '')[:6] for i in d.get('items', [])]}")
        check(d.get("cover_url") == f"/thumbnail/{items[0]['id']}", "portada = la del primer item", str(d.get("cover_url")))
        if d.get("cover_url"):
            rc = client.get(d["cover_url"])
            check(rc.status_code in (200, 404), "la portada resuelta responde", str(rc.status_code))

        if video and music:
            r = client.get(f"/users/me/playlists/{pid}", params={"media_type": "music"})
            check([i.get("id") for i in r.json().get("items", [])] == [music["id"]], "detalle con filtro media_type=music")
            r = client.delete(f"/users/me/playlists/{pid}/items/{music['id']}")
            check(r.status_code == 200, "quitar un item")
            r = client.get(f"/users/me/playlists/{pid}")
            check(r.json().get("item_count") == 1, "tras quitar queda 1 item")

        r = client.get("/users/me/playlists")
        check(any(p.get("id") == pid for p in r.json().get("playlists", [])), "aparece en el listado")
    finally:
        r = client.delete(f"/users/me/playlists/{pid}")
        check(r.status_code == 200, "borrar playlist temporal (limpieza)", f"{r.status_code}")
        r = client.get(f"/users/me/playlists/{pid}")
        check(r.status_code == 404, "ya no existe tras borrarla", str(r.status_code))

    r = client.get("/users/me/favorites")
    check(r.status_code == 200 and isinstance(r.json().get("favorites"), list)
          and all("id" in f for f in r.json()["favorites"]), "/users/me/favorites responde (solo lectura)",
          f"{r.status_code} {r.text[:100]}")

def find_in_feed(client, media_type, source_url):
    skip = 0
    for _ in range(6):
        r = client.get("/feed", params={"media_type": media_type, "limit": 50, "skip": skip})
        body = r.json()
        for it in body.get("feed", []):
            if it.get("url") == source_url:
                return it
        if body.get("next_skip") is None:
            return None
        skip = body["next_skip"]
    return None

def check_download(client, media_type, url, timeout):
    section(f"Descarga real ({media_type})")
    route = "/videos" if media_type == "video" else "/music"
    r = client.post(route, params={"url": url})
    if not check(r.status_code == 200 and r.json().get("task_id"), f"POST {route}", f"{r.status_code} {r.text[:100]}"):
        return None
    task = r.json()["task_id"]
    last, deadline = None, time.monotonic() + timeout
    while time.monotonic() < deadline:
        pr = client.get(f"/videos/progress/{task}")
        if pr.status_code != 200:
            R.fail(f"progreso -> {pr.status_code}")
            return None
        st = pr.json()
        line = f"{st.get('status')} {st.get('percent')}"
        if line != last:
            print(f"  ...   {line}")
            last = line
        if st.get("status") == "completed":
            break
        if st.get("status") == "error":
            R.fail(f"la descarga terminó en error: {st.get('detail')}")
            return None
        time.sleep(2)
    else:
        R.fail(f"la descarga no terminó en {timeout}s")
        return None
    R.ok("descarga completada (pasó por downloading -> uploading -> completed)")

    item = find_in_feed(client, media_type, url)
    if not check(item is not None, "el item aparece en el feed (metadata con la URL original)"):
        return None
    total = check_stream(client, media_type, item["id"], f"descargado ({media_type})")
    check_thumbnail(client, item["id"], f"descargado ({media_type})")
    return item

def main():
    ap = argparse.ArgumentParser(description="Valida el flujo OmniCast + holder contra un servidor en marcha")
    ap.add_argument("--url", default=DEFAULT_URL, help=f"servidor OmniCast (default {DEFAULT_URL})")
    ap.add_argument("--user", default=os.getenv("OMNICAST_USER"), required=not os.getenv("OMNICAST_USER"))
    ap.add_argument("--register", action="store_true", help="crear el usuario si no existe")
    ap.add_argument("--video", help="hash de un video a probar")
    ap.add_argument("--music", help="hash de una canción a probar")
    ap.add_argument("--aborts", type=int, default=40)
    ap.add_argument("--download-video", metavar="URL")
    ap.add_argument("--download-music", metavar="URL")
    ap.add_argument("--timeout", type=int, default=600, help="segundos máximos por descarga")
    args = ap.parse_args()

    password = os.getenv("OMNICAST_PASSWORD") or getpass.getpass(f"Contraseña de {args.user}: ")
    client = httpx.Client(
        base_url=args.url,
        timeout=httpx.Timeout(30, read=120),
        headers={"Accept-Encoding": "identity"},
    )
    try:
        if login(client, args.user, password, args.register) is None:
            print("\nSin sesión no se puede seguir.")
            return 1

        check_feed(client)
        video = {"id": args.video, "title": ""} if args.video else newest(client, "video")
        music = {"id": args.music, "title": ""} if args.music else newest(client, "music")

        section("Reproducción")
        video_total = music_total = None
        if video:
            video_total = check_stream(client, "video", video["id"], "video")
            check_thumbnail(client, video["id"], "video")
        else:
            R.skip("no hay videos descargados")
        if music:
            music_total = check_stream(client, "music", music["id"], "música")
            check_download_music(client, music["id"])
        else:
            R.skip("no hay música descargada")
        check_wrong_route(client, video, music)

        section("Búsqueda")
        for label, it in (("video", video), ("música", music)):
            if it and it.get("title"):
                check_search(client, it, label)

        section("Conexiones cortadas")
        if video:
            check_aborts(client, "video", video["id"], video_total, args.aborts)
        elif music:
            check_aborts(client, "music", music["id"], music_total, args.aborts)
        else:
            R.skip("cortes: no hay nada que reproducir")

        check_playlists(client, video, music)

        if args.download_video:
            check_download(client, "video", args.download_video, args.timeout)
        if args.download_music:
            check_download(client, "music", args.download_music, args.timeout)
    except httpx.ConnectError:
        print(f"\nNo pude conectar con {args.url}. ¿Está corriendo el servidor?")
        return 1
    except httpx.HTTPError as e:
        R.fail(f"error de red inesperado: {e!r}")
    finally:
        client.close()

    print(f"\n{R.ok_n} OK, {R.fail_n} FAIL, {R.skip_n} SKIP")
    return 1 if R.fail_n else 0


if __name__ == "__main__":
    sys.exit(main())