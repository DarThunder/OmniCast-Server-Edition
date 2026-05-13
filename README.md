# OmniCast: Server Edition

> The thing that actually does the work.

OmniCast Server is the backend half of the OmniCast ecosystem — a self-hosted, zero-configuration media server designed to run on whatever hardware you have lying around. A laptop, a NUC, a Raspberry Pi, a machine on a UPS. If it runs Python, it runs OmniCast.

**Works without internet once content is downloaded. Your hardware, your content, your rules.**

---

## What it does

- Announces itself on your local network via mDNS/Zeroconf — the Android client finds it automatically, no IP addresses required
- Downloads videos from any yt-dlp-supported source and stores them locally
- Serves video with HTTP range requests for smooth seeking
- Deduplicates content using SHA3-512 hashing — the same video downloaded twice takes space only once
- Generates and serves thumbnails alongside video metadata
- Does all of this without touching the internet on its own — every download is explicitly triggered by the user

---

## Requirements

- Python 3.11+
- [yt-dlp](https://github.com/yt-dlp/yt-dlp)
- [FastAPI](https://fastapi.tiangolo.com/) + [uvicorn](https://www.uvicorn.org/)
- [zeroconf](https://pypi.org/project/zeroconf/)
- [aiofiles](https://pypi.org/project/aiofiles/)

```bash
pip install fastapi uvicorn yt-dlp zeroconf aiofiles
```

---

## Running the server

```bash
uvicorn src:app --host 0.0.0.0 --port 8080 --timeout-keep-alive 30
```

The server will announce itself on the local network immediately. The Android client will find it on its own.

Videos are stored at `~/omnicast/store/` by default.

---

## API

| Method | Endpoint            | Description                              |
| ------ | ------------------- | ---------------------------------------- |
| `GET`  | `/health`           | Health check                             |
| `GET`  | `/videos`           | List all videos with metadata            |
| `GET`  | `/video/{hash}`     | Stream a video (supports range requests) |
| `GET`  | `/thumbnail/{hash}` | Get video thumbnail                      |
| `POST` | `/videos?url=...`   | Queue a video download                   |

Downloads run as background tasks — the endpoint returns immediately and the video appears in the library once it's done.

---

## How content is stored

Each video lives in its own directory, identified by a SHA3-512 hash derived from the video's metadata (not the file itself):

```
~/omnicast/store/
└── a282b5c4750d.../
    ├── media.mp4
    ├── media.webp       ← thumbnail
    └── metadata.json    ← title, duration, id
```

This means re-downloading the same video from a different quality or at a different time will still resolve to the same hash — no duplicates.

---

## Architecture

```
[Android client] ──── HTTP (local network) ────> [FastAPI + uvicorn]
                                                         │
                              ┌──────────────────────────┤
                              │                          │
                       [yt-dlp downloader]      [~/omnicast/store/]
                              │                          │
                              └──────── writes ──────────┘
```

The server is stateless. All persistence lives on the filesystem. No database, no cache layer, no cloud dependencies.

---

## Network behavior

OmniCast Server uses mDNS (via Zeroconf) to broadcast its presence on the local network under the `_omnicast._tcp` service type. The Android client listens for this and connects automatically.

This means:

- No manual IP configuration ever
- Works as long as the server and client are on the same network
- Stops broadcasting cleanly when the server shuts down

The server is designed exclusively for **local network use**. It has no authentication, no TLS, and no rate limiting — exposing it to the public internet is your problem, not ours.

---

## Roadmap

- [x] Video download via yt-dlp
- [x] HTTP range request streaming
- [x] mDNS auto-discovery
- [x] SHA3-512 deduplication
- [x] Thumbnail serving
- [x] HTTP keep-alive / connection pooling
- [ ] Authentication — JWT + bcrypt/Argon2
- [ ] Multi-user support — per-user progress, favorites
- [ ] Configurable storage path via CLI args
- [ ] Garbage collector — cleanup by views, age, or disk usage
- [ ] Download queue status endpoint

---

## Legal Notice

OmniCast Server uses [yt-dlp](https://github.com/yt-dlp/yt-dlp) for video downloading. **You are solely responsible for ensuring that any content you download complies with the terms of service of the source platform, applicable copyright law, and any relevant regulations in your jurisdiction.**

OmniCast does not host, distribute, or provide access to any third-party content. It is a personal archival tool intended for lawful, private use on local networks only. The developers make no warranties regarding the legality of any specific use. Use at your own risk.

---

## License

[AGPLv3](LICENSE) — if you run a modified version of OmniCast Server, you must make your source code available.
