# OmniCast: Server Edition

> The thing that actually does the work.

OmniCast Server is the backend core of the OmniCast ecosystem — a self-hosted, personal offline media server designed to archive, manage, and stream audio and video content. Built on FastAPI and SQLAlchemy, it turns local storage into an authenticated, multi-user media streaming hub.

Works without internet once content is archived. Your hardware, your media, your rules.

---

## What it does

- **Dual-Media Ingestion:** Imports media sources using yt-dlp-compatible extractors in background tasks with real-time download and extraction progress tracking.

- **Audio Extraction & Metadata Enrichment:** Extracts audio to Opus and resolves clean track titles, artist details, and album covers via Spotify catalog integration.

- **Smooth Streaming:** Supports HTTP byte-range requests (RFC 7233) for both video and audio streaming, enabling instant seeking and low memory overhead.

- **Deduplication Engine:** Identifies incoming media through deterministic SHA3-512 hashing derived from media source attributes.

- **Multi-User & Security:** Built-in JWT bearer token authentication, bcrypt password hashing, and isolated user profiles for favorites and custom playlists.

- **Local Persistence:** Retains global media catalogs and user data using SQLite.

---

## Requirements

- Python 3.11+

- FFmpeg (required by `yt-dlp` for audio extraction and transcoding)

- Dependencies:

```bash
pip install fastapi uvicorn yt-dlp aiofiles sqlalchemy pyjwt passlib[bcrypt] pillow requests python-dotenv

```

---

## Configuration

The server expects a configuration file located at `~/.config/omnicast/.env`:

```env
OMNICAST_SECRET=your_super_secret_jwt_key
SPOTIPY_CLIENT_ID=your_spotify_client_id          # Optional: for music metadata matching
SPOTIPY_CLIENT_SECRET=your_spotify_client_secret  # Optional: for music metadata matching

```

Media files and database storage default to `~/omnicast/store/`.

---

## Running the server

```bash
python run.py

```

By default, the server listens on port `8081`. When paired with private mesh overlays like Tailscale or local networks, it serves clients securely without exposing raw ports to the public internet.

---

## API Overview

### Authentication & Public Routes

| Method | Endpoint  | Description            |
| ------ | --------- | ---------------------- |
| `GET`  | `/health` | Server heartbeat check |

|
| `POST` | `/register` | Register a new user account

|
| `POST` | `/token` | OAuth2 password flow login (returns JWT)

|
| `GET` | `/thumbnail/{hash}` | Retrieve public media thumbnail

|

### Authenticated Media Routes (`Bearer <token>`)

| Method | Endpoint | Description                                        |
| ------ | -------- | -------------------------------------------------- | ----- | ----------------------- |
| `GET`  | `/feed`  | Paginated feed of archived media (`?media_type=all | video | music&skip=0&limit=50`) |

|
| `GET` | `/feed/library` | Filter library media by media type

|
| `POST` | `/videos` | Queue a background video download task (`?url=...`)

|
| `POST` | `/music` | Queue a background music extraction task (`?url=...`)

|
| `GET` | `/videos/progress/{task_id}` | Poll download progress, speed, percentage, and ETA

|
| `GET` | `/video/{hash}` | Stream video file with partial range support

|
| `GET` | `/music/{hash}` | Stream audio file with partial range support

|
| `GET` | `/music/{hash}/download` | Download standalone audio file with sanitized track title

|
| `GET` | `/users/me/favorites` | List current user's favorite items

|
| `POST` | `/users/me/favorites/{hash}` | Add a media item to current user's favorites

|
| `GET` | `/users/me/playlists/{name}` | Fetch playlist contents

|
| `POST` | `/users/me/playlists/{name}/{hash}` | Add a media item to an existing or new playlist

|

---

## Storage Layout

Media and database assets are structured on the local filesystem:

```
~/omnicast/
├── store/
│   ├── omnicast.db            ← SQLite database (users, playlists, catalog)
│   ├── videos/
│   │   └── <sha3_512_hash>/
│   │       ├── media.mp4
│   │       ├── media.webp     ← video thumbnail
│   │       └── metadata.json
│   └── music/
│       └── <sha3_512_hash>/
│           ├── media.opus
│           ├── media.webp     ← album artwork
│           └── metadata.json

```

---

## Legal Notice

OmniCast Server utilizes `yt-dlp` as an external fetching component. You are solely responsible for ensuring that any content you archive complies with the terms of service of the source platform, applicable copyright laws, and any relevant regulations in your jurisdiction.

OmniCast does not host, index, distribute, or provide access to any proprietary third-party content. It is an open-source, personal archival tool intended strictly for lawful, private use. The developers make no warranties regarding the legality of any specific use. Use at your own risk.

---

## License

[AGPL-3.0-or-later](LICENSE)
