# main.py
# OmniCast — Personal offline media server
# Copyright (C) 2026-Present  DarThunder
# SPDX-License-Identifier: AGPL-3.0-or-later

import asyncio
from contextlib import asynccontextmanager
import shutil
import socket
import subprocess
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
import uvicorn

from core.configs import opts
from core.database import Base, engine, init_fts
from routers import auth, media, users

RED = "\033[91m"
GREEN = "\033[92m"
YELLOW = "\033[93m"
RESET = "\033[0m"


def check_warp_status() -> None:
    if not shutil.which("warp-cli"):
        print(
            f"{RED}[!] No tienes Warp, asi que si te aplican "
            f"soft ban ya te jodiste chigga{RESET}",
            flush=True,
        )
        return

    try:
        res = subprocess.run(
            ["warp-cli", "status"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        output = res.stdout.lower()

        if "status update: connected" in output or "connected" in output:
            print(
                f"{GREEN}[✓] Cloudflare WARP activo. Túnel listo para rotación.{RESET}",
                flush=True,
            )
        else:
            print(
                f"{YELLOW}[!] warp-cli está instalado pero DESCONECTADO. "
                f"Ejecuta 'warp-cli connect' para evitar bloqueos.{RESET}",
                flush=True,
            )
    except Exception as e:
        print(f"{RED}[!] Error consultando estado de WARP: {e}{RESET}", flush=True)

@asynccontextmanager
async def lifespan(app: FastAPI):
    Base.metadata.create_all(bind=engine)
    init_fts(engine)
    check_warp_status()
    yield

app = FastAPI(
    title="OmniCast",
    description="Personal offline media server",
    lifespan=lifespan,
)

@app.get("/health")
def live():
    return {"message": "Hello pim"}

@app.get("/debug/tasks")
async def debug_tasks():
    tasks = asyncio.all_tasks()
    return {"total": len(tasks), "tasks": [str(t) for t in tasks]}

app.include_router(auth.router)
app.include_router(media.router)
app.include_router(users.router)
app.mount("/", StaticFiles(directory="web", html=True), name="web")

class KeepaliveServer(uvicorn.Server):
    async def startup(self, sockets=None):
        await super().startup(sockets)
        for server in self.servers:
            for sock in server.sockets:
                sock.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
                keepidle_opt = getattr(
                    socket, "TCP_KEEPIDLE", getattr(socket, "TCP_KEEPALIVE", 4)
                )
                sock.setsockopt(socket.IPPROTO_TCP, keepidle_opt, 120)
                sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPINTVL, 30)
                sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPCNT, 5)

if __name__ == "__main__":
    port = opts.get("port")
    config = uvicorn.Config(
        app=app,
        host="0.0.0.0",
        port=port,
        reload=False,
        timeout_graceful_shutdown=5,
    )
    server = KeepaliveServer(config)
    asyncio.run(server.serve())