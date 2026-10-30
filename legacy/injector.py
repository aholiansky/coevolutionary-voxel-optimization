import amulet
import os
import sys
import time
import json
import logging

logging.getLogger('amulet').setLevel(logging.ERROR)

INPUT_FILE = "minecraft_bitstream.txt"
DIST_FILE = "ore_distribution.json"
DENSITY_MULTIPLIER = 1.0 
VOID_STREAK_LIMIT = 500 

VALID_BLOCKS = {
    "stone", "deepslate", "andesite", "diorite", "granite", "tuff", 
    "coal_ore", "deepslate_coal_ore"
}

COAL_NORMAL = amulet.Block.from_string_blockstate("minecraft:coal_ore")
COAL_DEEP   = amulet.Block.from_string_blockstate("minecraft:deepslate_coal_ore")
STONE_NORMAL= amulet.Block.from_string_blockstate("minecraft:stone")
STONE_DEEP  = amulet.Block.from_string_blockstate("minecraft:deepslate")

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

def inject_bitstream(level, center_x, center_z, bits, model):
    cursor = 0
    total_bits = len(bits)
    mod_chunks = set()
    debug_points = []
    
    current_chunk = None
    last_cx, last_cz = None, None

    print(f"Rozpoczynanie iniekcji {total_bits} bitów...")
    start_time = time.time()

    for y in range(-64, 320):
        if cursor >= total_bits: break
        
        p_val = model.get_prob(y)
        if p_val <= 0: continue 

        gen = leg_based_spiral()
        void_streak = 0
        
        for x_off, z_off in gen:
            if cursor >= total_bits: break
            if void_streak > VOID_STREAK_LIMIT: break 

            real_x = center_x + x_off
            real_z = center_z + z_off
            
            cx, cz = real_x >> 4, real_z >> 4
            
            if (cx, cz) != (last_cx, last_cz):
                try:
                    current_chunk = level.get_chunk(cx, cz, "minecraft:overworld")
                    void_streak = 0
                except:
                    current_chunk = None
                last_cx, last_cz = cx, cz
            
            if current_chunk is None:
                void_streak += 1
                continue

            rand_val = deterministic_hash(real_x, y, real_z)
            
            if rand_val < (p_val * DENSITY_MULTIPLIER):
                lx, lz = real_x % 16, real_z % 16
                try:
                    bid = current_chunk.blocks[lx, y, lz]
                    base_name = current_chunk.block_palette[bid].base_name
                except: continue

                if base_name not in VALID_BLOCKS: continue

                bit_to_write = bits[cursor]
                cursor += 1
                
                is_deep = ("deepslate" in base_name) or (y < 0)
                
                if bit_to_write == '1':
                    target_block = COAL_DEEP if is_deep else COAL_NORMAL
                else:
                    target_block = STONE_DEEP if is_deep else STONE_NORMAL

                if base_name != target_block.base_name:
                    new_id = current_chunk.block_palette.get_add_block(target_block)
                    current_chunk.blocks[lx, y, lz] = new_id
                    current_chunk.changed = True
                    mod_chunks.add((cx, cz))
                
                debug_points.append((real_x, y, real_z, int(bit_to_write)))

            if cursor % 1000 == 0:
                pct = (cursor / total_bits) * 100
                sys.stdout.write(f"\r[Y={y}] Postęp: {pct:.1f}% ({cursor}/{total_bits})   ")
                sys.stdout.flush()

    print(f"\n\nZakończono. Zapisano {cursor} bitów.")
    print(f"Generowanie pliku wizualizacji 'injection_log.json' ({len(debug_points)} punktów)...")
    with open("injection_log.json", "w") as f:
        json.dump(debug_points, f)
    
    return cursor, mod_chunks

def main():
    print("=== INJECTOR Z LOGOWANIEM ===")
    
    if not os.path.exists(INPUT_FILE):
        print(f"Brak {INPUT_FILE}"); return
    with open(INPUT_FILE, "r") as f: bits = f.read().strip()
    if not bits: print("Pusty strumień bitów"); return

    if not os.path.exists(DIST_FILE):
        print(f"Brak {DIST_FILE}"); return
    model = ProbabilityModel(DIST_FILE)

    w_path = input("Ścieżka świata Minecraft: ").strip()
    try: level = amulet.load_level(w_path)
    except Exception as e: print(f"Błąd: {e}"); return

    print("Start iniekcji...")
    t0 = time.time()
    bits_done, changed_chunks = inject_bitstream(level, 0, 0, bits, model)
    
    if bits_done < len(bits):
        print(f"\n[CRITICAL] Zapisano tylko {bits_done} z {len(bits)} bitów!")
    else:
        print("\n[SUKCES] Wszystkie dane zapisane.")
        print("Zapisywanie zmian na dysku...")
        level.save()
        level.close()
        print(f"Gotowe. Czas: {round(time.time()-t0, 2)}s")

if __name__ == "__main__":
    main()