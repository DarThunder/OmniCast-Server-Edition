import os
import sys
import time
import uuid
from pathlib import Path
from dotenv import load_dotenv
import httpx

ENV_PATH = Path.home() / ".config" / "omnicast" / ".env"
load_dotenv(dotenv_path=ENV_PATH)

PROWLARR_URL = os.getenv("PROWLARR_URL", "http://127.0.0.1:9696")
PROWLARR_API_KEY = os.getenv("PROWLARR_API_KEY", "")

ARIA2_RPC_URL = os.getenv("ARIA2_RPC_URL", "http://127.0.0.1:6800/jsonrpc")
ARIA2_SECRET = os.getenv("ARIA2_SECRET", "")

DOWNLOAD_DIR = Path("/var/lib/aria2/downloads")

MAX_SIZE_BYTES = 10 * 1024**3

def fmt_size(b: int) -> str:
    if not b:
        return "0 B"
    return f"{b / (1024**3):.2f} GB" if b >= 1024**3 else f"{b / (1024**2):.1f} MB"

def fmt_speed(bps: int) -> str:
    if not bps:
        return "0 KB/s"
    mb = bps / (1024**2)
    return f"{mb:.2f} MB/s" if mb >= 1 else f"{bps / 1024:.0f} KB/s"

def resolve_uri(uri: str) -> str:
    if uri.startswith("magnet:"):
        return uri
    try:
        with httpx.Client(follow_redirects=False, timeout=15.0) as client:
            resp = client.get(uri)
            if resp.status_code in (301, 302, 303, 307, 308):
                loc = resp.headers.get("location", "")
                if loc.startswith("magnet:"):
                    return loc
    except Exception as e:
        print(f"[!] Aviso resolviendo redirect: {e}")
    return uri

def aria2_rpc(method: str, params: list | None = None):
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
            raise RuntimeError(f"Error de Aria2: {data['error']}")
        return data.get("result")

def main():
    query = " ".join(sys.argv[1:]) if len(sys.argv) > 1 else "Paul Blart Mall Cop"
    print(f"[*] Buscando '{query}' en Prowlarr (máx 10 GB)...\n")

    with httpx.Client(
        base_url=PROWLARR_URL,
        headers={"X-Api-Key": PROWLARR_API_KEY},
        timeout=25.0,
    ) as client:
        resp = client.get(
            "/api/v1/search",
            params=[("query", query), ("type", "search"), ("categories", 2000)],
        )
        resp.raise_for_status()
        items = resp.json()

    valid = [
        it for it in items
        if (it.get("seeders") or 0) > 0
        and (it.get("magnetUrl") or it.get("downloadUrl"))
        and (it.get("size") or 0) <= MAX_SIZE_BYTES
    ]
    valid.sort(key=lambda x: x.get("seeders", 0), reverse=True)

    if not valid:
        print("[-] No se encontraron resultados ligeros con seeders.")
        return

    top = valid[:8]
    for i, it in enumerate(top, 1):
        print(
            f"  [{i}] [{it.get('indexer')}] {it.get('title')}\n"
            f"      Seeds: {it.get('seeders')} | Peso: {fmt_size(it.get('size', 0))}\n"
        )

    choice = input(f"Elige un número (1-{len(top)}) [Enter = 1]: ").strip()
    idx = (int(choice) - 1) if choice.isdigit() else 0
    selected = top[idx]

    raw_uri = selected.get("magnetUrl") or selected.get("downloadUrl")
    final_uri = resolve_uri(raw_uri)
    print(f"\n[*] URI resuelta: {final_uri[:80]}...")

    gid = aria2_rpc("addUri", [[final_uri], {"dir": str(DOWNLOAD_DIR), "seed-time": "0"}])
    print(f"[+] Enviado a aria2 con GID: {gid}. Monitoreando descarga (Ctrl+C para cancelar)...\n")

    try:
        while True:
            st = aria2_rpc(
                "tellStatus",
                [gid, ["gid", "status", "totalLength", "completedLength", "downloadSpeed", "connections", "followedBy", "files", "errorMessage"]],
            )
            if st.get("followedBy"):
                new_gid = st["followedBy"][0]
                print(f"\n[*] Metadatos listos. Pasando al GID del video real: {new_gid}")
                gid = new_gid
                continue

            status = st.get("status")
            total = int(st.get("totalLength") or 0)
            done = int(st.get("completedLength") or 0)
            speed = int(st.get("downloadSpeed") or 0)
            peers = st.get("connections", "0")
            pct = (done / total * 100) if total > 0 else 0.0

            sys.stdout.write(
                f"\r[{status.upper()}] {pct:5.1f}% | "
                f"{fmt_size(done)} / {fmt_size(total)} | "
                f"Vel: {fmt_speed(speed)} | Peers: {peers}   "
            )
            sys.stdout.flush()

            if status == "complete":
                print("\n\n[+] ¡Descarga completada!")
                for f in st.get("files", []):
                    print(f"    Archivo: {f.get('path')}")
                break
            if status in ("error", "removed"):
                print(f"\n\n[-] Falló la descarga: {st.get('errorMessage')}")
                break

            time.sleep(1.0)
    except KeyboardInterrupt:
        print("\n[!] Cancelando descarga en aria2...")
        aria2_rpc("forceRemove", [gid])


if __name__ == "__main__":
    main()