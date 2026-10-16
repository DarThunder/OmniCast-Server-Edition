import spotipy
from spotipy.oauth2 import SpotifyClientCredentials
import yt_dlp
from ..src.services.fetcher import download_music
import time
import random
import os
from pathlib import Path
from dotenv import load_dotenv
import json

env_path = Path.home() / ".env"
load_dotenv(dotenv_path=env_path)

SPOTIPY_CLIENT_ID = os.getenv("SPOTIPY_CLIENT_ID")
SPOTIPY_CLIENT_SECRET = os.getenv("SPOTIPY_CLIENT_SECRET")

if not SPOTIPY_CLIENT_ID or not SPOTIPY_CLIENT_SECRET:
    raise ValueError("No se encontraron las credenciales de Spotify en ~/.env")

sp = spotipy.Spotify(auth_manager=SpotifyClientCredentials(
    client_id=SPOTIPY_CLIENT_ID,
    client_secret=SPOTIPY_CLIENT_SECRET
))

def get_youtube_url(search_query: str) -> str:
    ydl_opts = {
        'quiet': True,
        'extract_flat': True,
        'no_warnings': True,
        'noplaylist': True,
        'default_search': 'ytsearch',
    }
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        result = ydl.extract_info(f"ytsearch1:{search_query}", download=False)
        
        if 'entries' in result and result['entries']:
            entry = result['entries'][0]
            url = entry.get('url') or entry.get('webpage_url')
            if url and not url.startswith('http'):
                url = f"https://www.youtube.com/watch?v={url}"
            return url
    return None

def mark_track_as_processed(track_id: str):
    with open("migrated_tracks.txt", "a", encoding="utf-8") as f:
        f.write(f"{track_id}\n")

def migrate_spotify_playlist(playlist_url: str):
    results = sp.playlist_tracks(playlist_url)
    tracks = results['items']
    
    while results['next']:
        results = sp.next(results)
        tracks.extend(results['items'])

    existing_tracks = set()
    music_dir = Path.home() / "omnicast/store/music"

    print("Indexando biblioteca local...")
    for meta_path in music_dir.glob("*/metadata.json"):
        try:
            with open(meta_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                t = data.get("title", "").strip().lower()
                u = data.get("uploader", "").strip().lower()
                if t:
                    existing_tracks.add(f"{u} - {t}")
                    existing_tracks.add(t)
        except Exception:
            continue

    print(f"Total de pistas ya listas en disco: {len(existing_tracks)}")
        
    for item in tracks:
        track = item['track']
        if not track:
            continue

        track_id = track['id']
        title = track['name']
        artist = track['artists'][0]['name']
        cover_url = track['album']['images'][0]['url'] if track['album']['images'] else None
        
        norm_title = title.strip().lower()
        norm_artist = artist.strip().lower()
        full_name = f"{norm_artist} - {norm_title}"

        if full_name in existing_tracks or norm_title in existing_tracks:
            print(f"⚡ Ya lista: {artist} - {title} (saltando sin delay)")
            mark_track_as_processed(track_id)
            continue

        search_query = f"{artist} {title} official audio"
        print(f"Buscando en YT: {search_query}")
        
        youtube_url = get_youtube_url(search_query)
        
        if youtube_url:
            print(f" -> Encontrado: {youtube_url}")
            
            spotify_meta = {
                "title": title,
                "uploader": artist,
                "cover_url": cover_url
            }
            
            download_music(youtube_url, spotify_meta=spotify_meta)

            duration_sec = track.get("duration_ms", 180000) / 1000
            sleep_time = (duration_sec * random.uniform(0.03, 0.06)) + random.uniform(2.0, 5.0)

            print(f"Durmiendo {sleep_time:.2f}s (basado en la duración del tema)...")
            time.sleep(sleep_time)
        else:
            print(f" -> No se encontró nada para: {search_query}")

migrate_spotify_playlist("https://open.spotify.com/playlist/77mdspOXsBmodcYD85Fvn6?si=5459a161e7d94db8")