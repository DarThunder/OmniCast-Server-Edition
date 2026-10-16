import json
from pathlib import Path
import sys

sys.path.append(str(Path(__file__).resolve().parent.parent))

from src.core import configs

def get_track_display_name(directory: Path, dir_hash: str) -> str:
    meta_path = directory / "metadata.json"
    if meta_path.exists():
        try:
            with open(meta_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                title = data.get("title")
                uploader = data.get("uploader") or data.get("artist")
                if title and uploader:
                    return f"{uploader} - {title}"
                if title:
                    return title
        except Exception:
            pass
    return f"Hash: {dir_hash}"

def check_music_integrity():
    music_dir = Path(configs.opts.get("music_path", "music"))

    if not music_dir.exists() or not music_dir.is_dir():
        print(f"[-] Error: Directorio de música no encontrado en: {music_dir}")
        return

    hashed_dirs = [p for p in music_dir.iterdir() if p.is_dir()]
    total_dirs = len(hashed_dirs)

    print(f"[*] Escaneando {total_dirs} directorios en '{music_dir}'...")

    missing_opus = []
    empty_opus = []

    for directory in hashed_dirs:
        dir_hash = directory.name
        display_name = get_track_display_name(directory, dir_hash)

        opus_files = list(directory.glob("*.opus"))

        if not opus_files:
            missing_opus.append((dir_hash, display_name))
        else:
            for opus_file in opus_files:
                if opus_file.stat().st_size == 0:
                    empty_opus.append((dir_hash, display_name, opus_file.name))

    print("\n" + "=" * 60)
    print("REPORTE DE INTEGRIDAD DE BIBLIOTECA")
    print("=" * 60)

    if missing_opus:
        print(f"\n[!] Carpetas SIN archivo .opus ({len(missing_opus)}):")
        for h, name in missing_opus:
            print(f"  - [{h}] {name}")
    else:
        print("\n[✓] Todas las carpetas contienen al menos un archivo .opus.")

    if empty_opus:
        print(f"\n[!] Archivos .opus VACÍOS (0 bytes) ({len(empty_opus)}):")
        for h, name, filename in empty_opus:
            print(f"  - [{h}] {name} -> Archivo: {filename}")
    elif not missing_opus:
        print("[✓] Ningún archivo .opus está vacío.")

    print("\n" + "=" * 60)
    print(f"Total analizados: {total_dirs} | Con fallas: {len(missing_opus) + len(empty_opus)}")
    print("=" * 60)

if __name__ == "__main__":
    check_music_integrity()