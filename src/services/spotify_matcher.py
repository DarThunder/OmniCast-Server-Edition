import re
import difflib
import requests
from typing import Optional, Dict

class SpotifyMatcher:
    def __init__(self, client_id: str, client_secret: str):
        self.client_id = client_id
        self.client_secret = client_secret
        self.access_token = None

    def _authenticate(self):
        url = "https://accounts.spotify.com/api/token"
        resp = requests.post(
            url,
            data={"grant_type": "client_credentials"},
            auth=(self.client_id, self.client_secret),
            timeout=10
        )
        if resp.status_code == 200:
            self.access_token = resp.json().get("access_token")

    def _clean_text(self, text: str) -> str:
        cleaned = re.sub(
            r"(?i)\s*[\(\[\{].*?(official|video|audio|lyrics|music|remastered|visualizer|4k|hd|sub español).*?[\)\]\}]",
            "",
            text
        )
        cleaned = re.sub(r"(?i)\b(feat\.?|ft\.?)\s+[^\-]+", "", cleaned)
        cleaned = re.sub(r"[^\w\s\-]", " ", cleaned)
        return " ".join(cleaned.split()).strip()

    def find_metadata(self, yt_title: str, yt_uploader: str = "") -> Optional[Dict]:
        if not self.access_token:
            self._authenticate()

        clean_title = self._clean_text(yt_title)
        artist_hint = self._clean_text(yt_uploader) if yt_uploader else ""

        if " - " in clean_title:
            parts = clean_title.split(" - ", 1)
            artist_hint = parts[0].strip()
            clean_title = parts[1].strip()

        queries = [
            f"track:{clean_title} artist:{artist_hint}" if artist_hint else clean_title,
            f"{artist_hint} {clean_title}".strip(),
            clean_title
        ]

        headers = {"Authorization": f"Bearer {self.access_token}"}

        for q in queries:
            try:
                resp = requests.get(
                    "https://api.spotify.com/v1/search",
                    params={"q": q, "type": "track", "limit": 5},
                    headers=headers,
                    timeout=10
                )
                if resp.status_code == 401:
                    self._authenticate()
                    headers = {"Authorization": f"Bearer {self.access_token}"}
                    resp = requests.get(
                        "https://api.spotify.com/v1/search",
                        params={"q": q, "type": "track", "limit": 5},
                        headers=headers,
                        timeout=10
                    )

                items = resp.json().get("tracks", {}).get("items", [])
                if not items:
                    continue

                best_match = None
                best_score = 0.0

                for item in items:
                    sp_title = item.get("name", "")
                    sp_artist = ", ".join([a["name"] for a in item.get("artists", [])])
                    
                    target_pair = f"{artist_hint} {clean_title}".lower()
                    candidate_pair = f"{sp_artist} {sp_title}".lower()
                    
                    score = difflib.SequenceMatcher(None, target_pair, candidate_pair).ratio()

                    if score > best_score:
                        best_score = score
                        best_match = item

                if best_match and best_score >= 0.55:
                    images = best_match.get("album", {}).get("images", [])
                    cover_url = images[0]["url"] if images else None

                    return {
                        "title": best_match.get("name"),
                        "uploader": ", ".join([a["name"] for a in best_match.get("artists", [])]),
                        "cover_url": cover_url,
                        "album": best_match.get("album", {}).get("name")
                    }
            except Exception as e:
                print(f"[!] Error buscando en Spotify: {e}")

        return None