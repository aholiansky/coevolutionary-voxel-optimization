import os
import zlib
from reedsolo import RSCodec, ReedSolomonError
from crypto_handler import CryptoHandler
import json

MAGIC_VAL = 0xD35C
MAGIC_BITS = f"{MAGIC_VAL:016b}"

HEADER_DATA_SIZE = 8
HEADER_ECC_SIZE = 4
HEADER_TOTAL_SIZE = HEADER_DATA_SIZE + HEADER_ECC_SIZE

DATA_EC_LEVELS = {
    0: (255, 223),
    1: (255, 191),
    2: (255, 127), 
    3: (255, 63)  
}

MODES_REV = {
    0b0000: ("BINARY",       ".bin"),
    0b0001: ("UTF8",         ".txt"),
    0b0010: ("IMAGE",        ".png"),
    0b0011: ("KEY_ENVELOPE", ".key"),
    0b0100: ("AUDIO",        ".mp3"),
    0b1111: ("KEY_EXCHANGE", ".pem")
}

def bits_to_bytes(bits):
    return bytearray([int(bits[i:i+8], 2) for i in range(0, len(bits), 8)])

class StreamDecoder:
    def __init__(self, stream_bits):
        self.stream = stream_bits
        self.cursor = 0
        self.header_rsc = RSCodec(HEADER_ECC_SIZE)

    def _read_segment(self):
        h_bits_len = HEADER_TOTAL_SIZE * 8
        h_chunk = self.stream[self.cursor : self.cursor + h_bits_len]
        
        if len(h_chunk) < h_bits_len:
            print(" [DEBUG] Koniec strumienia lub ucięty nagłówek")
            return None, None, False, False, 0

        try:
            h_decoded = self.header_rsc.decode(bits_to_bytes(h_chunk))[0]
        except ReedSolomonError:
            print(" [ERROR] Nagłówek uszkodzony nieodwracalnie (RS Failed)!")
            return None, None, False, False, 0

        self.cursor += h_bits_len
        
        h_bits = "".join(f"{b:08b}" for b in h_decoded)
        
        ver = int(h_bits[0:6], 2)
        ec_idx = int(h_bits[6:8], 2)
        flags = int(h_bits[8:10], 2)
        mode_val = int(h_bits[10:14], 2)
        payload_len_bits = int(h_bits[14:38], 2) 
        
        is_comp = bool(flags & 1)    
        is_enc = bool((flags >> 1) & 1)
        
        mode_info = MODES_REV.get(mode_val, ("UNKNOWN", ".dat"))
        mode_name = mode_info[0]
        
        n, k = DATA_EC_LEVELS[ec_idx]
        data_bytes_per_block = k
        block_size_bits = n * 8
        
        payload_bytes_needed = (payload_len_bits + 7) // 8
        num_blocks = (payload_bytes_needed + data_bytes_per_block - 1) // data_bytes_per_block
        if payload_bytes_needed == 0: num_blocks = 0
        
        total_segment_bits = num_blocks * block_size_bits
        
        payload_chunk = self.stream[self.cursor : self.cursor + total_segment_bits]
        self.cursor += total_segment_bits
        
        if len(payload_chunk) < total_segment_bits:
            print(" [ERROR] Ucięty strumień payloadu (brak danych)")
            return None, None, False, False, 0

        payload_rsc = RSCodec(n - k)
        decoded_data = bytearray()
        
        payload_bytes = bits_to_bytes(payload_chunk)
        
        try:
            for i in range(0, len(payload_bytes), n):
                block = payload_bytes[i : i+n]
                decoded_block = payload_rsc.decode(block)[0]
                decoded_data.extend(decoded_block)
        except ReedSolomonError:
            print(" [ERROR] Błąd w danych payloadu (zbyt duże uszkodzenia)")
            return None, None, False, False, 0

        final_len_bytes = (payload_len_bits + 7) // 8
        final_data = decoded_data[:final_len_bytes]
        
        return final_data, mode_name, is_enc, is_comp, payload_len_bits

    def decode(self):
        print("Skanowanie strumienia w poszukiwaniu MAGIC...")
        pos = self.stream.find(MAGIC_BITS)
        if pos == -1: return print("Błąd: Nie znaleziono MAGIC (Początek danych)")
        self.cursor = pos + 16
        
        print("\n[1/2] Dekodowanie Segmentu Głównego...")
        data1, mode1, enc1, comp1, len1 = self._read_segment()
        
        if not data1:
            print("Nie udało się odczytać pierwszego segmentu")
            return

        print(f" -> Typ: {mode1}")
        print(f" -> Rozmiar: {len1} bitów")
        print(f" -> Zaszyfrowany: {enc1}, Kompresja: {comp1}")

        window = self.stream[self.cursor : self.cursor + 1024]
        rel_pos = window.find(MAGIC_BITS)
        
        data2, mode2 = None, None
        
        if rel_pos != -1:
            self.cursor += rel_pos + 16
            print("\n[2/2] Dekodowanie Segmentu Metadanych...")
            data2, mode2, _, _, _ = self._read_segment()
            if data2:
                print(f" -> Typ: {mode2} ({len(data2)} bajtów)")
        else:
            print(" -> Brak drugiego segmentu (lub uszkodzony znacznik MAGIC2)")

        print("\n--- PRZETWARZANIE DANYCH ---")
        
        final_payload = data1
        
        if comp1 and not enc1:
            try:
                final_payload = zlib.decompress(final_payload)
                print(f" -> [SUKCES] Dekompresja ZLIB: {len(data1)}B -> {len(final_payload)}B")
            except Exception as e:
                print(f" -> [BŁĄD] Nieudana dekompresja: {e}")

        if mode2 == "KEY_EXCHANGE":
            print("\n[WARIANT 1] Wykryto wizytówkę z kluczem publicznym")
            
            detected_user = "unknown"
            detected_time = "unknown"
            
            if mode1 == "UTF8":
                try:
                    meta_json = final_payload.decode('utf-8', errors='ignore')
                    meta_data = json.loads(meta_json)
                    
                    detected_user = meta_data.get("user", "unknown")
                    detected_time = meta_data.get("created_at", "unknown")
                    
                    print(f" -> Użytkownik:  {detected_user}")
                    print(f" -> Data klucza: {detected_time}")
                except json.JSONDecodeError:
                    print(" -> [WARN] Nie udało się odczytać metadanych JSON (format legacy?)")
            
            cx, cy, cz = CryptoHandler.get_fingerprint_coords(bytes(data2))
            
            print("\n--- WERYFIKACJA AUTENTYCZNOŚCI ---")
            print(f"Obliczony Fingerprint klucza: X={cx}, Y={cy}, Z={cz}")
            print("Porównaj te koordynaty z wiadomością od nadawcy (Discord/Messenger)")
            print("Jeśli się zgadzają -> Klucz jest autentyczny")
            print("----------------------------------")
            
            safe_username = "".join(c for c in detected_user if c.isalnum() or c in ('_', '-'))
            filename = f"recipient_public_{safe_username}.pem"
            
            with open(filename, "wb") as f:
                f.write(data2)
            
            print(f" [SUKCES] Zapisano klucz publiczny jako: '{filename}'")
            print(" Możesz go teraz użyć w Coderze (Wariant 2), podając tę ścieżkę")

        elif mode2 == "KEY_ENVELOPE" and enc1:
            print("[WARIANT 2] Wykryto zaszyfrowane dane")
            
            if not os.path.exists("recipient_private.pem"):
                print(" [BŁĄD] Brak pliku 'recipient_private.pem'. Nie można odszyfrować danych")
                return
            
            print("\n--- WERYFIKACJA FINGERPRINTU (Przykrywka) ---")
            rec_x, rec_y, rec_z = CryptoHandler.get_fingerprint_coords(bytes(data1))
            print(f"Obliczony Fingerprint danych: X={rec_x}, Y={rec_y}, Z={rec_z}")
            print("Porównaj te koordynaty z wiadomością od nadawcy (Discord/Messenger)")
            print("Jeśli się różnią - PLIK JEST USZKODZONY lub PODMIENIONY!")
            print("---------------------------------------------")

            print(" -> Odszyfrowywanie klucza sesji (RSA)...")
            try:
                with open("recipient_private.pem", "rb") as f: priv_pem = f.read()
                
                decrypted_payload = CryptoHandler.decrypt_hybrid(
                    bytes(data1), 
                    bytes(data2), 
                    priv_pem
                )
                final_payload = decrypted_payload
                print(" -> [SUKCES] Dane odszyfrowane (AES-GCM)")
                
            except Exception as e:
                print(f" -> [BŁĄD KRYPTOGRAFICZNY] {e}")
                return

        ext = ".dat"
        for k, v in MODES_REV.items():
            if v[0] == mode1:
                ext = v[1]
                break
        
        out_filename = f"recovered_file{ext}"
        with open(out_filename, "wb") as f:
            f.write(final_payload)
            
        print(f"\n[KONIEC] Zapisano plik jako: {out_filename}")
        if mode1 == "UTF8":
            print(f"Treść: {final_payload.decode('utf-8', errors='ignore')[:200]}...")

def main():
    print("=== MINECRAFT STEGO DECODER ===")
    
    if not os.path.exists("minecraft_bitstream.txt"):
        print("Brak pliku 'minecraft_bitstream.txt'. Uruchom najpierw extractor.py!")
        return
        
    with open("minecraft_bitstream.txt", "r") as f:
        bits = f.read().strip()
        
    decoder = StreamDecoder(bits)
    decoder.decode()

if __name__ == "__main__":
    main()