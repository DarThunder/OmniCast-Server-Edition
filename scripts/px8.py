import sqlite3

from ..src.core.configs import DB_PATH
from ..src.core.database import Base, engine

def run_migration():
    print(f"Migrando base de datos en: {DB_PATH}")
    
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    cursor.execute("PRAGMA table_info(users)")
    columns = [col[1] for col in cursor.fetchall()]
    
    if "bio" not in columns:
        print("-> Agregando columna 'bio' a la tabla 'users'...")
        cursor.execute("ALTER TABLE users ADD COLUMN bio TEXT;")
        conn.commit()
    else:
        print("-> Columna 'bio' ya existe en 'users'.")
        
    conn.close()

    print("-> Creando tablas nuevas del modelo...")
    Base.metadata.create_all(bind=engine)
    print("Migración completada con éxito.")

if __name__ == "__main__":
    run_migration()