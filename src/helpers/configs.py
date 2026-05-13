# OmniCast — Personal offline media server
# Copyright (C) 2026-Present  DarThunder
# SPDX-License-Identifier: AGPL-3.0-or-later

from pathlib import Path

opts = {
    "path": str(Path.home() / "omnicast" / "store"),
    "port": 8080,
}