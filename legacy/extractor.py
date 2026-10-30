import amulet
import os
import sys
import time
import json
import logging
import math

try:
    from reedsolo import RSCodec, ReedSolomonError
except ImportError:
    print("Brak biblioteki reedsolo. Zainstaluj: pip install reedsolo")
    sys.exit(1)

logging.getLogger('amulet').setLevel(logging.ERROR)

MAGIC_VAL = 0xD35C
MAGIC_BITS_STR = f"{MAGIC_VAL:016b}" 
HEADER_DATA_BYTES = 8
HEADER_ECC_BYTES = 4
HEADER_TOTAL_BITS = (HEADER_DATA_BYTES + HEADER_ECC_BYTES) * 8

DATA_EC_LEVELS = {
    0: (255, 223), 
    1: (255, 191), 
    2: (255, 127), 
    3: (255, 63)
}

DIST_FILE = "ore_distribution.json"
VALID_BLOCKS = {
    "stone", "deepslate", "andesite", "diorite", "granite", "tuff", 
    "coal_ore", "deepslate_coal_ore"
}
COAL_NAMES = {"coal_ore", "deepslate_coal_ore"}
DENSITY_MULTIPLIER = 1.0 
VOID_STREAK_LIMIT = 200

class ProbabilityModel:
    def __init__(self, json_path):
        self.probs = {}
        if os.path.exists(json_path):
            with open(json_path, "r") as f:
                data = json.load(f)
                self.probs = {int(k): v['prob'] for k, v in data.items()}
    def get_prob(self, y): return self.probs.get(y, 0.005)

def deterministic_hash(x, y, z):
    h = (x * 374761393) ^ (y * 668265263) ^ (z * 432352741)
    h = (h ^ (h >> 13)) * 1274126177
    return (h & 0xFFFFFFF) / 0xFFFFFFF

def leg_based_spiral():
    x, z = 0, 0
    yield x, z
    leg = 1
    direction = 0
    moves = [(1, 0), (0, 1), (-1, 0), (0, -1)]
    while True:
        for _ in range(2):
            dx, dz = moves[direction]
            for _ in range(leg):
                x += dx
                z += dz
                yield x, z
            direction = (direction + 1) % 4
        leg += 1

def bits_to_bytes(bits: str): 
    return bytearray([int(bits[i:i+8], 2) for i in range(0, len(bits), 8)])

def parse_header_and_calc_size(header_bits_raw):
    rsc = RSCodec(HEADER_ECC_BYTES)
    try:
        decoded = rsc.decode(bits_to_bytes(header_bits_raw))[0]
    except ReedSolomonError:
        return None, None

    h_bits = "".join(f"{b:08b}" for b in decoded)
    
    ec_idx = int(h_bits[6:8], 2)
    payload_len_bits = int(h_bits[14:38], 2)
    
    n, k = DATA_EC_LEVELS[ec_idx]
    
    data_bytes_needed = (payload_len_bits + 7) // 8

    num_blocks = math.ceil(data_bytes_needed / k)
    
    total_segment_bits = num_blocks * n * 8
    
    return total_segment_bits, ec_idx

def extract_smart(level, center_x, center_z, model):
    extracted_bits = ""

    state = 0
    target_len = 0 
    cursor_offset = 0 
    print(f"Skanowanie (Szukam sygnatury startowej)...")
    
    current_chunk = None
    last_cx, last_cz = None, None

    for y in range(-64, 320):
        if state == 99: break

        p_val = model.get_prob(y)
        if p_val <= 0: continue

        gen = leg_based_spiral()
        void_streak = 0
        
        for x_off, z_off in gen:
            if state == 99: break
            if void_streak > VOID_STREAK_LIMIT: break 

            real_x = center_x + x_off
            real_z = center_z + z_off

            cx, cz = real_x >> 4, real_z >> 4
            if (cx, cz) != (last_cx, last_cz):
                try:
                    current_chunk = level.get_chunk(cx, cz, "minecraft:overworld")
                    void_streak = 0
                except: current_chunk = None
                last_cx, last_cz = cx, cz
            
            if not current_chunk:
                void_streak += 1
                continue

            rand_val = deterministic_hash(real_x, y, real_z)
            if rand_val >= (p_val * DENSITY_MULTIPLIER):
                continue

            lx, lz = real_x % 16, real_z % 16
            try:
                bid = current_chunk.blocks[lx, y, lz]
                base = current_chunk.block_palette[bid].base_name
            except: continue

            if base not in VALID_BLOCKS: continue

            bit = '1' if base in COAL_NAMES else '0'
            extracted_bits += bit
            
            if len(extracted_bits) % 500 == 0:
                states_str = ["Szukam MAGIC1", "Analiza HDR1", "Pobieranie Danych", 
                              "Szukam MAGIC2", "Analiza HDR2", "Pobieranie Metadanych", 
                              "Szukam KONIEC", "KONIEC"]
                st_name = states_str[min(state, 7)]
                sys.stdout.write(f"\rStatus: {st_name} | Pobrane bity: {len(extracted_bits)} | Y={y}   ")
                sys.stdout.flush()
            
            if state == 0:
                if len(extracted_bits) >= 16:
                    if extracted_bits[-16:] == MAGIC_BITS_STR:
                        print(f"\n[OK] Znaleziono MAGIC1 na pozycji {len(extracted_bits)-16}.")
                        state = 1
                        target_len = len(extracted_bits) + HEADER_TOTAL_BITS

            elif state == 1:
                if len(extracted_bits) >= target_len:
                    hdr_start = target_len - HEADER_TOTAL_BITS
                    hdr_bits = extracted_bits[hdr_start : target_len]
                    
                    seg_size, _ = parse_header_and_calc_size(hdr_bits)
                    if seg_size is not None:
                        print(f" -> Nagłówek 1 OK. Długość Segmentu 1: {seg_size} bitów")
                        state = 2
                        target_len = len(extracted_bits) + seg_size
                    else:
                        print("\n[BŁĄD] Nagłówek 1 uszkodzony! Restart skanowania...")
                        state = 0

            elif state == 2:
                if len(extracted_bits) >= target_len:
                    state = 3

            elif state == 3:
                if extracted_bits[-16:] == MAGIC_BITS_STR:
                     print(f"\n[OK] Znaleziono MAGIC2 (Metadane)")
                     state = 4
                     target_len = len(extracted_bits) + HEADER_TOTAL_BITS

            elif state == 4:
                if len(extracted_bits) >= target_len:
                    hdr_start = target_len - HEADER_TOTAL_BITS
                    hdr_bits = extracted_bits[hdr_start : target_len]
                    
                    seg_size, _ = parse_header_and_calc_size(hdr_bits)
                    if seg_size is not None:
                        print(f" -> Nagłówek 2 OK. Długość Segmentu 2: {seg_size} bitów")
                        state = 5
                        target_len = len(extracted_bits) + seg_size
                    else:
                        print("\n[BŁĄD] Nagłówek 2 uszkodzony!")
                        state = 99

            elif state == 5:
                if len(extracted_bits) >= target_len:
                    state = 6

            elif state == 6:
                if extracted_bits[-16:] == MAGIC_BITS_STR:
                    print(f"\n[SUKCES] Znaleziono MAGIC3 (Koniec transmisji)")
                    state = 99
                    break

    return extracted_bits

def main():
    print("=== EXTRACTOR INTELLIGENT V3 ===")
    
    model = ProbabilityModel(DIST_FILE)
    w_path = input("Ścieżka świata: ").strip()
    try: level = amulet.load_level(w_path)
    except Exception as e: print(f"Błąd: {e}"); return

    print("Rozpoczynam ekstrakcję od (0,0)...")
    t0 = time.time()
    
    bits = extract_smart(level, 0, 0, model)
    
    if not bits:
        print("\n[BŁĄD] Nie znaleziono żadnych danych.")
    else:
        print(f"\n[KONIEC] Pobrano {len(bits)} bitów w {round(time.time()-t0, 2)}s.")
        with open("minecraft_bitstream.txt", "w") as f:
            f.write(bits)
        print("Zapisano 'minecraft_bitstream.txt'. Uruchom teraz stream_decoder.py")

if __name__ == "__main__":
    main()