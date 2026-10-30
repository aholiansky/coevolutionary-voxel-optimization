import os
import zlib
import requests
from reedsolo import RSCodec
from crypto_handler import CryptoHandler
import json
import time

MAGIC_VAL = 0xD35C
PROTOCOL_VERSION = 1 
SERVER_URL = "http://127.0.0.1:5000"
DATA_EC_LEVELS = {
    0: (255, 223),
    1: (255, 191), 
    2: (255, 127), 
    3: (255, 63)  
}

HEADER_ECC_SIZE = 4 
HEADER_DATA_SIZE = 8

MODES = {
    "BINARY": 0b0000, "UTF8": 0b0001, "IMAGE": 0b0010,
    "KEY_ENVELOPE": 0b0011, "AUDIO": 0b0100, "KEY_EXCHANGE": 0b1111
}

def int_to_bin(value, num_bits):
    return f"{value:0{num_bits}b}"

def bytes_to_bits(data_bytes):
    return "".join(f"{b:08b}" for b in data_bytes)

def bits_to_bytes(bits_str):
    return bytes(int(bits_str[i:i+8], 2) for i in range(0, len(bits_str), 8))

class StreamCoder:
    def __init__(self, data_ec_idx=1):
        self.data_ec_id = data_ec_idx
        self.d_n, self.d_k = DATA_EC_LEVELS[data_ec_idx]
        self.data_rsc = RSCodec(self.d_n - self.d_k)
        self.header_rsc = RSCodec(HEADER_ECC_SIZE)

    def _create_header_block(self, mode_name, payload_len_bits, is_encrypted, is_compressed):
        ver_b = int_to_bin(PROTOCOL_VERSION, 6)
        ec_b = int_to_bin(self.data_ec_id, 2)
        
        flag_val = 0
        if is_encrypted: flag_val |= 0b10
        if is_compressed: flag_val |= 0b01
        flags_b = int_to_bin(flag_val, 2)
        
        mode_b = int_to_bin(MODES.get(mode_name, 0), 4)
        len_b = int_to_bin(payload_len_bits, 24)
        reserved_b = "0" * 26 
        
        raw_header_bits = ver_b + ec_b + flags_b + mode_b + len_b + reserved_b
        raw_header_bytes = bits_to_bytes(raw_header_bits)
        protected_header_bytes = self.header_rsc.encode(raw_header_bytes)
        
        return bytes_to_bits(protected_header_bytes)

    def _encode_payload(self, data_bytes):
        encoded_output = bytearray()
        chunk_size = self.d_k
        pad_len = chunk_size - (len(data_bytes) % chunk_size)
        if pad_len != chunk_size:
            data_bytes += b'\x00' * pad_len
            
        for i in range(0, len(data_bytes), chunk_size):
            chunk = data_bytes[i : i+chunk_size]
            encoded_chunk = self.data_rsc.encode(chunk)
            encoded_output.extend(encoded_chunk)
            
        return bytes_to_bits(encoded_output)

    def create_stream(self, primary_data: bytes, primary_mode: str, 
                      secondary_data: bytes, secondary_mode: str,
                      encrypt_primary=False):
        
        print(f"[CODER] Generowanie w trybie V3 (Split Header)...")

        p_payload = zlib.compress(primary_data) if not encrypt_primary else primary_data
        comp_flag = not encrypt_primary 
        
        p_bits_raw = bytes_to_bits(p_payload)
        p_stream_bits = self._encode_payload(bytearray(p_payload))
        h1_bits = self._create_header_block(primary_mode, len(p_bits_raw), encrypt_primary, comp_flag)
        
        s_payload = secondary_data
        s_bits_raw = bytes_to_bits(s_payload)
        s_stream_bits = self._encode_payload(bytearray(s_payload))
        h2_bits = self._create_header_block(secondary_mode, len(s_bits_raw), False, False)
        
        magic = int_to_bin(MAGIC_VAL, 16)
        
        final_stream = (
            magic + h1_bits + p_stream_bits +
            magic + h2_bits + s_stream_bits +
            magic
        )
        return final_stream

def get_recipient_key_online(user_id):
    """Pobiera klucz z serwera REST API"""
    url = f"{SERVER_URL}/get_key/{user_id}"
    print(f" -> Łączenie z serwerem: {url} ...")
    try:
        r = requests.get(url, timeout=5)
        if r.status_code == 200:
            print(" -> [SUKCES] Pobrano klucz publiczny")
            return r.content
        elif r.status_code == 404:
            print(f" -> [BŁĄD] Nie znaleziono użytkownika '{user_id}'.")
        else:
            print(f" -> [BŁĄD] Serwer zwrócił kod: {r.status_code}")
    except Exception as e:
        print(f" -> [BŁĄD SIECI] Nie można połączyć z serwerem: {e}")
    return None

def save_bitstream(bits):
    with open("minecraft_bitstream.txt", "w") as f:
        f.write(bits)
    print(f"\n[SUKCES] Wygenerowano strumień: {len(bits)} bitów")

def main():
    print("=== MINECRAFT STEGO CODER ===")
    print("1. WARIANT 1: Generuj Mapę-Klucz (Wizytówka)")
    print("2. WARIANT 2: Szyfruj Plik (Nadawca)")
    
    choice = input("Wybór: ").strip()
    coder = StreamCoder(data_ec_idx=1) 
    
    if choice == "1":
        print("\n=== GENEROWANIE WIZYTÓWKI Z KLUCZEM (WARIANT 1) ===")
        
        username = input("Podaj nazwę użytkownika (do identyfikacji klucza): ").strip()
        if not username: username = "user_unknown"
        
        if not os.path.exists("recipient_public.pem"):
            priv, pub = CryptoHandler.generate_keys()
            with open("recipient_private.pem", "wb") as f: f.write(priv)
            with open("recipient_public.pem", "wb") as f: f.write(pub)
            print(" -> Wygenerowano nową parę kluczy RSA")
        else:
            with open("recipient_public.pem", "rb") as f: pub = f.read()
            print(" -> Wczytano istniejący klucz publiczny")
            
        timestamp = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
        
        meta_data = {
            "user": username,
            "created_at": timestamp,
            "info": "Minecraft Stego Key Exchange"
        }
        meta_json = json.dumps(meta_data)
        
        cx, cy, cz = CryptoHandler.get_fingerprint_coords(pub)
        
        print("\n" + "="*60)
        print(" [OPCJA SOCJOTECHNICZNA - KANAŁ POBOCZNY] ")
        print(" Wyślij mapę znajomemu i napisz mu na Discordzie/Messengerze:")
        print(f' "Siema, masz mapę. Bazę zróbmy na kordach: {cx}, {cy}, {cz}"')
        print(" (To pozwoli mu zweryfikować, czy otrzymał Twój prawdziwy klucz)")
        print("="*60 + "\n")
        
        bits = coder.create_stream(
            primary_data=meta_json.encode('utf-8'),
            primary_mode="UTF8",
            secondary_data=pub,
            secondary_mode="KEY_EXCHANGE",
            encrypt_primary=False
        )
        save_bitstream(bits)

    elif choice == "2":
        print("\nSzyfrowanie pliku dla Odbiorcy...")
        
        f_path = input("Podaj ścieżkę do pliku: ").strip()
        if not os.path.exists(f_path):
            print("Brak pliku!"); return
            
        with open(f_path, "rb") as f: raw_data = f.read()
        
        ext = os.path.splitext(f_path)[1].lower()
        mode = "BINARY"
        if ext == ".txt": mode = "UTF8"
        elif ext in [".png", ".jpg"]: mode = "IMAGE"
        elif ext == ".mp3": mode = "AUDIO"
        
        recipient_pub = None
        print("\nSkąd pobrać klucz Odbiorcy?")
        print("1. Plik lokalny (recipient_public.pem)")
        print("2. Serwer Online (key_server.py)")
        
        k_choice = input("Wybór: ").strip()
        
        if k_choice == "1":
            pub_path = input("Ścieżka (Enter = recipient_public.pem): ").strip() or "recipient_public.pem"
            if os.path.exists(pub_path):
                with open(pub_path, "rb") as f: recipient_pub = f.read()
            else:
                print("Błąd: Brak pliku klucza")
        elif k_choice == "2":
            uid = input("Podaj ID użytkownika (np. inzynier_test): ").strip()
            recipient_pub = get_recipient_key_online(uid)
        else:
            print("Nieznana opcja")

        if recipient_pub is None:
            print("Nie udało się zdobyć klucza publicznego. Przerywam")
            return
            
        enc_payload, enc_session_key = CryptoHandler.encrypt_hybrid(raw_data, recipient_pub)
        fake_x, fake_y, fake_z = CryptoHandler.get_fingerprint_coords(enc_payload)
        
        print("\n" + "="*50)
        print(" [OPCJA SOCJOTECHNICZNA - KANAŁ POBOCZNY] ")
        print(" Wyślij mapę znajomemu i napisz mu na Discordzie/Messengerze coś w stylu:")
        print(f' "Siema, znalazłem super miejsce na bazę! Sprawdź koordynaty: {fake_x}, {fake_y}, {fake_z}"')
        print("="*50 + "\n")
        
        bits = coder.create_stream(
            primary_data=enc_payload,
            primary_mode=mode, 
            secondary_data=enc_session_key,
            secondary_mode="KEY_ENVELOPE",
            encrypt_primary=True
        )
        save_bitstream(bits)
        
    else:
        print("Nieznana opcja")

if __name__ == "__main__":
    main()