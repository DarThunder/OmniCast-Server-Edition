from pathlib import Path

from src.core import configs
from ..src.services.storage import get_metadata_from_directory
from ..src.core.database import SessionLocal
from ..src.models.db import GlobalMedia

def sync_database():
    db = SessionLocal()
    print("Iniciando escaneo de directorios físicos...")

    videos_path = Path(configs.opts["videos_path"])
    videos_meta = get_metadata_from_directory(videos_path)
    added_videos = 0

    for item in videos_meta:
        if not db.query(GlobalMedia).filter(GlobalMedia.hash == item["id"]).first():
            db.add(GlobalMedia(
                hash=item["id"], 
                title=item.get("title", "Desconocido"), 
                uploader=item.get("uploader", ""), 
                media_type="video"
            ))
            added_videos += 1

    music_path = Path(configs.opts["music_path"])
    music_meta = get_metadata_from_directory(music_path)
    added_music = 0

    for item in music_meta:
        if not db.query(GlobalMedia).filter(GlobalMedia.hash == item["id"]).first():
            db.add(GlobalMedia(
                hash=item["id"], 
                title=item.get("title", "Desconocido"), 
                uploader=item.get("uploader", ""), 
                media_type="music"
            ))
            added_music += 1

    db.commit()
    db.close()
    
    print("Sincronización completada exitosamente.")
    print(f"Nuevos videos indexados: {added_videos}")
    print(f"Nuevas pistas de música indexadas: {added_music}")

if __name__ == "__main__":
    sync_database()