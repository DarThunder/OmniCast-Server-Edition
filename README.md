# OmniCast: Server Edition

> The thing that actually does the work.

OmniCast Server is the backend core of the OmniCast ecosystem: a self-hosted, personal media server for archiving, organizing, and streaming video. Built on FastAPI and SQLAlchemy, it turns your own storage into an authenticated, multi-user streaming hub.

Once content is archived, playback works without internet. Your hardware, your media, your rules.

> Copyright (C) 2026-Present DarThunder
> Licensed under the [GNU AGPL-3.0-or-later](LICENSE)

---

## Legal Notice

**Please read this before using the software.**

**Neutral tool.** OmniCast Server is general-purpose software. It does not include, bundle, or supply any copyrighted media, and this project does not operate any public instance. Any content stored by an instance is selected and acquired by that instance's operator and users.

**User responsibility.** You are solely responsible for what you download, store, and stream, and for making sure you have the right to do so under the laws of your jurisdiction and the terms of service of any third-party platform. Downloading content from some platforms may violate their terms or applicable copyright law. The authors do not encourage or authorize any such use. Use OmniCast only with content you own, that is in the public domain, that is licensed to allow it, or for which you have permission.

**Personal use.** OmniCast is designed for private, personal use and small groups of trusted users. It is not intended to operate as a public distribution service.

**No affiliation.** OmniCast is an independent project and is not affiliated with, sponsored by, or endorsed by YouTube, Google, Cloudflare, or any other third party. All trademarks belong to their respective owners and are used for identification only.

**Third-party components.** OmniCast relies on external components such as yt-dlp and FFmpeg, which are governed by their own licenses and are not controlled by this project.

**Operators and privacy.** If you run an instance for other people, you are the operator and are responsible for informing them about the data it stores (account identifiers, favorites, playlists, playback history, profile images, and an audit log of user actions) and for complying with applicable data-protection law.

**Takedown requests.** The authors do not host or control third-party instances. Rights holders should send requests concerning specific content to the operator of the instance concerned. For matters related to this repository's source code, contact: `<xdarthunder@gmail.com>`.

**No warranty; limitation of liability.** This software is provided "AS IS", without warranty of any kind. To the maximum extent permitted by law, the authors and contributors are not liable for any claim, damages, data loss, account or IP restrictions, or other liability arising from its use (see sections 15 and 16 of the AGPL-3.0).

_This notice is informational and is not legal advice. If you have doubts about your situation, consult a qualified lawyer._

---

## What it does

- **Background ingestion:** Imports media from yt-dlp-compatible sources in background tasks, with real-time progress (percentage, speed, ETA) tracked in Redis.
- **Discovery:** Paginated external search (`/discover`) with Redis caching, so repeated queries don't hit the source again.
- **Local full-text search:** SQLite FTS5 with `bm25` ranking over your own catalog (`/search`).
- **Smooth streaming:** HTTP byte-range requests (RFC 7233) for instant seeking and low memory overhead. Content is proxied from a separate blob storage service (the _holder_).
- **Deduplication:** Media is identified by a deterministic content hash, so the same item is not stored twice in the global catalog.
- **Multi-user, delegated auth:** JWT bearer tokens validated against an **OSIRIS** identity server (JWKS). Users are provisioned automatically on first login.
- **User features:** Favorites, playlists (custom ordering, custom covers), profile bio and picture (converted to WebP), and per-item playback progress.
- **Audit log:** Relevant user actions are recorded in the database.

---

## Architecture

```
Client ──► OmniCast Server (FastAPI :8081)
             ├── OSIRIS (JWKS)     → authentication (JWT)
             ├── SQLite (+FTS5)    → catalog, users, playlists, history, audit log
             ├── Redis             → discovery cache, download task progress
             └── Holder            → video and thumbnail blobs
```

---

## Requirements

- Python 3.12+
- FFmpeg (required by `yt-dlp` for processing)
- Redis
- A running **OSIRIS** server (JWT issuer with a JWKS endpoint)
- A running **holder** blob service at `http://127.0.0.1:8080`

```bash
nix develop
```

---

## Configuration

The server reads its configuration from `~/.config/omnicast/.env`:

```env
OSIRIS_ISSUER=https://your-osiris-server
REDIS_PASSWORD=a_strong_password
```

| Variable         | Required | Description                              |
| ---------------- | -------- | ---------------------------------------- |
| `OSIRIS_ISSUER`  | Yes      | Expected issuer (`iss`) of incoming JWTs |
| `REDIS_PASSWORD` | Yes      | Password for the Redis instance          |

Fixed values (see `core/configs.py`):

| Setting        | Value                                         |
| -------------- | --------------------------------------------- |
| Port           | `8081`                                        |
| JWT audience   | `omnicast`                                    |
| JWKS URL       | `http://127.0.0.1:8090/.well-known/jwks.json` |
| Holder URL     | `http://127.0.0.1:8080`                       |
| Database       | `~/.config/omnicast/omnicast.db`              |
| Profile images | `~/omnicast/profiles/`                        |

Place a `default.webp` in `~/omnicast/profiles/` to serve as the fallback profile picture.

> **Never commit your `.env` file** or share your credentials.

---

## Running the server

```bash
python main.py
```

Interactive API docs are available at `http://localhost:8081/docs`.

> The server binds to all interfaces by default. If you expose it beyond your local network, put it behind a reverse proxy with HTTPS and/or a firewall. Pairing it with a private mesh network such as Tailscale avoids exposing raw ports to the public internet.

---

## API overview

### Public routes

| Method | Endpoint            | Description                             |
| ------ | ------------------- | --------------------------------------- |
| `GET`  | `/health`           | Server heartbeat check                  |
| `GET`  | `/thumbnail/{hash}` | Media thumbnail (WebP, cacheable)       |
| `GET`  | `/search?q=...`     | Full-text search over the local catalog |

### Authenticated routes (`Authorization: Bearer <token>`)

**Media**

| Method | Endpoint                          | Description                                 |
| ------ | --------------------------------- | ------------------------------------------- |
| `GET`  | `/discover?q=...&page=1&limit=20` | Search external sources (paginated, cached) |
| `GET`  | `/feed?skip=0&limit=50`           | Paginated feed of archived media            |
| `POST` | `/videos?url=...`                 | Queue a background download task            |
| `GET`  | `/videos/progress/{task_id}`      | Poll download progress, speed, and ETA      |
| `GET`  | `/video/{hash}`                   | Stream a video with byte-range support      |

**User (`/users/me`)**

| Method                     | Endpoint                       | Description                               |
| -------------------------- | ------------------------------ | ----------------------------------------- |
| `GET` / `PATCH`            | `/profile`                     | Read or update profile (bio)              |
| `GET` / `POST`             | `/pfp`                         | Read or upload profile picture (max 5 MB) |
| `GET`                      | `/favorites`                   | List favorites                            |
| `POST` / `DELETE`          | `/favorites/{hash}`            | Add or remove a favorite                  |
| `GET` / `POST`             | `/playlists`                   | List or create playlists                  |
| `GET` / `PATCH` / `DELETE` | `/playlists/{id}`              | Read, update, or delete a playlist        |
| `POST` / `DELETE`          | `/playlists/{id}/items/{hash}` | Add or remove an item                     |
| `GET` / `POST` / `DELETE`  | `/playlists/{id}/cover`        | Read, upload, or delete a custom cover    |
| `GET` / `PATCH`            | `/history/{hash}`              | Read or save playback position (ms)       |

---

## Data and storage

- **Database** (`~/.config/omnicast/omnicast.db`): global catalog, users, favorites, playlists, playback history, and audit log.
- **Blobs** (videos, thumbnails): stored and served by the holder service, referenced by the catalog.
- **Profiles** (`~/omnicast/profiles/<user>/`): profile pictures and playlist covers, stored as WebP.

### Privacy

OmniCast stores locally: the OSIRIS subject identifier, username, bio, favorites, playlists, images, playback progress, and an audit log (searches, downloads, profile and playlist changes, with their details, such as the URLs submitted for download). Operators serving other people must inform them of this and comply with applicable data-protection law (for example GDPR or LFPDPPP).

---

## License

This program is free software: you can redistribute it and/or modify it under the terms of the **GNU Affero General Public License** as published by the Free Software Foundation, either version 3 of the License, or (at your option) any later version.

This program is distributed in the hope that it will be useful, but **WITHOUT ANY WARRANTY**; without even the implied warranty of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the GNU AGPL for more details. You should have received a copy of the license in the [`LICENSE`](LICENSE) file; if not, see <https://www.gnu.org/licenses/agpl-3.0.html>.

**Network use (AGPL §13):** if you modify OmniCast and let other people interact with your modified version over a network, you must offer them the corresponding source code of that version under the same license.

---

## Contributing

Pull requests are welcome. By contributing, you agree that your contribution is licensed under **AGPL-3.0-or-later** and you confirm you have the right to submit it. Contributions must not include copyrighted material without permission, credentials, or personal data.

## Security

If you find a vulnerability, please report it privately to `xdarthunder@gmail.com` instead of opening a public issue.

---

© 2026-Present DarThunder. All rights reserved except as granted by the AGPL-3.0-or-later.
