import json
from pathlib import Path
from collections import defaultdict

def find_duplicates():
    base_dir = Path.home() / "omnicast/store/music"
    tracks_by_key = defaultdict(list)

    for meta_file in base_dir.glob("*/metadata.json"):
        try:
            with open(meta_file, "r", encoding="utf-8") as f:
                data = json.load(f)
                clean_title = data.get("title", "").lower()
                clean_title = clean_title.replace("(audio)", "").replace("(official audio)", "").strip()
                clean_uploader = data.get("uploader", "").lower().strip()
                key = (clean_uploader, clean_title)
                tracks_by_key[key].append(meta_file.parent)
        except Exception:
            continue

    duplicates = {k: dirs for k, dirs in tracks_by_key.items() if len(dirs) > 1}
    
    if not duplicates:
        print("¡Biblioteca limpia! No se encontraron duplicados reales.")
        return

    print(f"Se encontraron {len(duplicates)} canciones realmente duplicadas:\n")
    for (uploader, title), dirs in duplicates.items():
        print(f"Pista: '{uploader} - {title}' encontrada en:")
        for d in dirs:
            print(f"  - {d.name}")

if __name__ == "__main__":
    find_duplicates()