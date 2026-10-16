import json
import requests

BASE_URL = "http://localhost:8081"
USERNAME = "DarThunder"
PASSWORD = "inmaterium12"

def test_login_and_feed():
    session = requests.Session()

    login_url = f"{BASE_URL}/token"
    login_payload = {
        "username": USERNAME,
        "password": PASSWORD,
    }

    print(f"[*] Enviando login a {login_url}...")
    token_resp = session.post(login_url, data=login_payload)

    if token_resp.status_code != 200:
        print(f"[!] Error al iniciar sesión ({token_resp.status_code}):")
        print(token_resp.text)
        return

    token_data = token_resp.json()
    token = token_data.get("access_token")
    print("[+] Login exitoso. Token recibido.")

    headers = {"Authorization": f"Bearer {token}"}

    feed_url = f"{BASE_URL}/feed"
    params = {"media_type": "music", "skip": 0, "limit": 5}

    print(f"[*] Consultando feed: {feed_url} con parámetros {params}...")
    feed_resp = session.get(feed_url, headers=headers, params=params)

    print(f"[*] Status code: {feed_resp.status_code}")

    try:
        data = feed_resp.json()
        print("[+] Respuesta recibida:")
        print(json.dumps(data, indent=2, ensure_ascii=False))
    except Exception:
        print("[!] Respuesta no es JSON:")
        print(feed_resp.text)


if __name__ == "__main__":
    test_login_and_feed()