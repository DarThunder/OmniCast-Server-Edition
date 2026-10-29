# OmniCast - Personal Offline Video Server
# Copyright (C) 2026-Present  DarThunder
# SPDX-License-Identifier: AGPL-3.0-or-later.

import os
from pathlib import Path
from dotenv import load_dotenv

CONFIG_DIR = Path.home() / ".config" / "omnicast"
ENV_PATH = CONFIG_DIR / ".env"
load_dotenv(dotenv_path=ENV_PATH)

PROFILES_PATH = str(Path.home() / "omnicast" / "profiles")
PORT = 8081

OSIRIS_JWKS_URL = "http://127.0.0.1:8090/.well-known/jwks.json"
HOLDER_URL = "http://127.0.0.1:8080"
DATABASE_URL = f"sqlite:///{CONFIG_DIR / "omnicast.db"}"

OSIRIS_AUDIENCE = "omnicast"
OSIRIS_ISSUER = os.getenv("OSIRIS_ISSUER")
if not OSIRIS_ISSUER:
    raise RuntimeError(f"Falta OSIRIS_ISSUER en {ENV_PATH}")

REDIS_PASSWD = os.getenv("REDIS_PASSWORD")
if not REDIS_PASSWD:
    raise RuntimeError(f"Falta REDIS_PASSWORD en {ENV_PATH}")