import sqlite3
import argparse
from pathlib import Path

def get_db_path() -> Path:
    return Path.home() / "omnicast" / "store" / "omnicast.db"

def fetch_logs(limit: int, username: str = None, action: str = None):
    db_path = get_db_path()
    if not db_path.exists():
        print(f"Error: No se encontró la base de datos en {db_path}")
        return

    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    cursor = conn.cursor()

    query = """
        SELECT a.id, a.timestamp, u.username, a.action, a.details
        FROM audit_logs a
        LEFT JOIN users u ON a.user_id = u.id
        WHERE 1=1
    """
    params = []

    if username:
        query += " AND u.username = ?"
        params.append(username)
    
    if action:
        query += " AND a.action = ?"
        params.append(action)

    query += " ORDER BY a.timestamp DESC LIMIT ?"
    params.append(limit)

    try:
        cursor.execute(query, params)
        rows = cursor.fetchall()
    except sqlite3.OperationalError as e:
        print(f"Error al consultar la base de datos: {e}")
        return
    finally:
        conn.close()

    if not rows:
        print("No se encontraron registros que coincidan con los criterios.")
        return

    print(f"{'ID':<6} | {'Fecha/Hora (UTC)':<20} | {'Usuario':<15} | {'Acción':<22} | {'Detalles'}")
    print("-" * 100)
    for row in rows:
        r_id, ts, uname, act, det = row
        uname = uname if uname else "Sistema/Anon"
        act = act if act else "N/A"
        det = det if det else ""
        
        ts_str = str(ts)[:19] 
        
        print(f"{r_id:<6} | {ts_str:<20} | {uname:<15} | {act:<22} | {det}")

def main():
    parser = argparse.ArgumentParser(
        description="CLI para visualizar los logs de auditoría de OmniCast",
        formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument(
        "-l", "--limit", 
        type=int, 
        default=50, 
        help="Cantidad máxima de registros a mostrar (por defecto: 50)"
    )
    parser.add_argument(
        "-u", "--user", 
        type=str, 
        help="Filtrar por nombre de usuario exacto"
    )
    parser.add_argument(
        "-a", "--action", 
        type=str, 
        help="Filtrar por tipo de acción (ej. LOGIN, DOWNLOAD_VIDEO_START)"
    )

    args = parser.parse_args()
    fetch_logs(limit=args.limit, username=args.user, action=args.action)

if __name__ == '__main__':
    main()