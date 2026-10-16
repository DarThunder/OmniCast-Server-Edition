import subprocess
from pathlib import Path

def normalize_thumbnails_to_webp():
    base_dir = Path.home() / "omnicast/store/music"
    
    if not base_dir.exists():
        print(f"El directorio {base_dir} no existe.")
        return

    extensions_to_search = ['**/*.jpg', '**/*.jpeg', '**/*.JPG', '**/*.JPEG']
    
    for ext in extensions_to_search:
        for img_path in base_dir.glob(ext):
            if not img_path.is_file():
                continue
            
            target_path = img_path.parent / "media.webp"
            
            print(f"Procesando: {img_path.name} en {img_path.parent.name}...")
            
            cmd = [
                "ffmpeg",
                "-y",
                "-i", str(img_path),
                str(target_path)
            ]
            
            try:
                result = subprocess.run(
                    cmd, 
                    stdout=subprocess.DEVNULL, 
                    stderr=subprocess.DEVNULL
                )
                
                if result.returncode == 0:
                    img_path.unlink()
                    print(f"  -> Éxito. {img_path.name} eliminado.")
                else:
                    print(f"  -> Error: FFmpeg no pudo convertir {img_path.name}")
                    
            except FileNotFoundError:
                print("Error: No se encontró FFmpeg. Asegúrate de que esté instalado y en tu PATH.")
                return
            except Exception as e:
                print(f"  -> Excepción inesperada: {e}")

if __name__ == "__main__":
    normalize_thumbnails_to_webp()
    print("Limpieza completada.")