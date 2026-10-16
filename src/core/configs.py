# OmniCast — Personal offline media server
# Copyright (C) 2026-Present  DarThunder
# SPDX-License-Identifier: AGPL-3.0-or-later

import os
from pathlib import Path
from dotenv import load_dotenv

CONFIG_DIR = Path.home() / ".config" / "omnicast"
ENV_PATH = CONFIG_DIR / ".env"
load_dotenv(dotenv_path=ENV_PATH)

BASE_STORE = Path.home() / "omnicast" / "store"

opts = {
    "path": str(BASE_STORE),
    "videos_path": str(BASE_STORE / "videos"),
    "music_path": str(BASE_STORE / "music"),
    "profiles_path": str(Path.home() / "omnicast" / "profiles"),
    "port": 8081,
}

PROWLARR_URL = "http://127.0.0.1:9696"
ARIA2_RPC_URL = "http://127.0.0.1:6800/jsonrpc"
HOLDER_URL = "http://127.0.0.1:8080"
DB_PATH = Path(opts["path"]) / "omnicast.db"
DATABASE_URL = f"sqlite:///{DB_PATH}"

SECRET_KEY = os.getenv("OMNICAST_SECRET")
if not SECRET_KEY:
    raise RuntimeError(f"Falta OMNICAST_SECRET en {ENV_PATH}")

REDIS_PASSWD = os.getenv("REDIS_PASSWORD")
if not REDIS_PASSWD:
    raise RuntimeError(f"Falta REDIS_PASSWORD en {ENV_PATH}")

PROWLARR_API_KEY = os.getenv("PROWLARR_API_KEY", "")
if not PROWLARR_API_KEY:
    raise RuntimeError(f"Falta PROWLARR_API_KEY en {ENV_PATH}")

ARIA2_SECRET = os.getenv("ARIA2_SECRET", "")
if not ARIA2_SECRET:
    raise RuntimeError(f"Falta ARIA2_SECRET en {ENV_PATH}")

SPOTIPY_CLIENT_ID = os.getenv("SPOTIPY_CLIENT_ID")
SPOTIPY_CLIENT_SECRET = os.getenv("SPOTIPY_CLIENT_SECRET")