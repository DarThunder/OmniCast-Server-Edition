from sqlalchemy import text
from unidecode import unidecode

from ..src.core.database import engine, SessionLocal
from ..src.models.db import GlobalMedia

def migrate_and_populate():
    with engine.begin() as conn:
        try:
            conn.execute(text("ALTER TABLE global_media ADD COLUMN aliases TEXT NOT NULL DEFAULT '';"))
            print("✓ Columna 'aliases' agregada a global_media")
        except Exception:
            print("• La columna 'aliases' ya existía, continuando...")

        conn.execute(text("""
            CREATE VIRTUAL TABLE IF NOT EXISTS global_media_fts USING fts5(
                hash UNINDEXED,
                title,
                uploader,
                aliases,
                tokenize = 'unicode61 remove_diacritics 2'
            );
        """))

        conn.execute(text("""
            CREATE TRIGGER IF NOT EXISTS gm_ai AFTER INSERT ON global_media BEGIN
                INSERT INTO global_media_fts(hash, title, uploader, aliases)
                VALUES (new.hash, new.title, new.uploader, coalesce(new.aliases, ''));
            END;
        """))

        conn.execute(text("""
            CREATE TRIGGER IF NOT EXISTS gm_ad AFTER DELETE ON global_media BEGIN
                DELETE FROM global_media_fts WHERE hash = old.hash;
            END;
        """))

        conn.execute(text("""
            CREATE TRIGGER IF NOT EXISTS gm_au AFTER UPDATE ON global_media BEGIN
                DELETE FROM global_media_fts WHERE hash = old.hash;
                INSERT INTO global_media_fts(hash, title, uploader, aliases)
                VALUES (new.hash, new.title, new.uploader, coalesce(new.aliases, ''));
            END;
        """))
        print("✓ Tabla virtual y triggers configurados")

    db = SessionLocal()
    try:
        items = db.query(GlobalMedia).all()
        print(f"Procesando {len(items)} archivos multimedia existentes...")

        with engine.begin() as conn:
            conn.execute(text("DELETE FROM global_media_fts;"))

            for item in items:
                raw_title = item.title or ""
                raw_uploader = item.uploader or ""
                
                ascii_title = unidecode(raw_title)
                ascii_uploader = unidecode(raw_uploader)

                variants = []
                if ascii_title.lower() != raw_title.lower():
                    variants.append(ascii_title)
                if ascii_uploader.lower() != raw_uploader.lower():
                    variants.append(ascii_uploader)

                item.aliases = " ".join(variants)

                conn.execute(
                    text("""
                        INSERT INTO global_media_fts(hash, title, uploader, aliases)
                        VALUES (:hash, :title, :uploader, :aliases)
                    """),
                    {
                        "hash": item.hash,
                        "title": raw_title,
                        "uploader": raw_uploader,
                        "aliases": item.aliases,
                    }
                )

        db.commit()
        print("✓ Migración y backfill completados exitosamente sin tocar tus archivos.")
    finally:
        db.close()

if __name__ == "__main__":
    migrate_and_populate()