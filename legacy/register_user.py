import requests
import os
from crypto_handler import CryptoHandler

SERVER_URL = "http://127.0.0.1:5000"

def main():
    print("=== REJESTRACJA UŻYTKOWNIKA W SYSTEMIE ===")
    user_id = input("Podaj nazwę użytkownika: ").strip()
    
    if not os.path.exists("recipient_public.pem"):
        print("Generowanie nowej pary kluczy...")
        priv, pub = CryptoHandler.generate_keys()
        with open("recipient_private.pem", "wb") as f: f.write(priv)
        with open("recipient_public.pem", "wb") as f: f.write(pub)
    else:
        print("Znaleziono istniejące klucze lokalne")

    print(f"Wysyłanie klucza publicznego na {SERVER_URL}...")
    
    with open("recipient_public.pem", "rb") as f:
        files = {'key_file': f}
        data = {'user_id': user_id}
        try:
            r = requests.post(f"{SERVER_URL}/register", data=data, files=files)
            if r.status_code == 200:
                print(f"[SUKCES] Zarejestrowano użytkownika '{user_id}'.")
            else:
                print(f"[BŁĄD] Serwer odpowiedział: {r.text}")
        except Exception as e:
            print(f"[BŁĄD SIECI] Czy serwer działa? {e}")

if __name__ == "__main__":
    main()