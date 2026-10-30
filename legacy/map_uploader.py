import os
import shutil
import requests

SERVER_URL = "http://127.0.0.1:5000"

def zip_world_folder(world_path):
    base_name = os.path.basename(os.path.normpath(world_path))
    zip_name = f"{base_name}.zip"
    
    print(f"Pakowanie świata '{base_name}' do archiwum...")
    
    root_dir = os.path.dirname(world_path)
    base_dir = os.path.basename(world_path)
    
    archive_path = shutil.make_archive(os.path.join(root_dir, base_name), 'zip', root_dir, base_dir)
    
    return archive_path, zip_name

def upload_map_to_server(zip_path, zip_filename, recipient_id):
    url = f"{SERVER_URL}/upload_map"
    print(f"Wysyłanie mapy do użytkownika: {recipient_id}...")
    
    with open(zip_path, 'rb') as f:
        files = {'map_archive': (zip_filename, f)}
        data = {'recipient_id': recipient_id}
        
        try:
            r = requests.post(url, data=data, files=files)
            if r.status_code == 200:
                print("[SUKCES] Mapa wysłana i rozpakowana na serwerze")
                print(f"Server Info: {r.json().get('message')}")
            else:
                print(f"[BŁĄD] Serwer odrzucił plik: {r.text}")
        except Exception as e:
            print(f"[BŁĄD SIECI] {e}")

def main():
    print("=== MINECRAFT MAP UPLOADER ===")
    
    world_path = input("Podaj pełną ścieżkę do folderu świata (np. .../saves/New World): ").strip()
    if not os.path.exists(world_path) or not os.path.isdir(world_path):
        print("Błąd: Podana ścieżka nie istnieje lub nie jest folderem")
        return

    recipient = input("Podaj ID odbiorcy (dla kogo jest ta mapa?): ").strip()
    if not recipient:
        print("Musisz podać ID odbiorcy"); return

    try:
        zip_full_path, zip_name = zip_world_folder(world_path)
    except Exception as e:
        print(f"Błąd pakowania: {e}"); return

    upload_map_to_server(zip_full_path, zip_name, recipient)
    
    try:
        os.remove(zip_full_path)
        print("Tymczasowy plik ZIP został usunięty")
    except:
        pass

if __name__ == "__main__":
    main()