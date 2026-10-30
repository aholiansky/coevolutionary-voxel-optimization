import amulet
import numpy as np
import json
import time
import os

DEFAULT_WORLD_PATH = r"C:\Apps\Crystal-Launcher\instances\Vanilla_1.21.5\.minecraft\saves\New World"
SCAN_RADIUS = 50

TARGET_BASE_NAMES = {"coal_ore", "deepslate_coal_ore"}
BASE_BASE_NAMES = {
    "stone", "deepslate", 
    "andesite", "diorite", "granite", "tuff"
}

MIN_Y = -64
MAX_Y = 320

def get_block_indices(palette, target_base_names):
    indices = []
    for idx, block in enumerate(palette):
        if block.base_name in target_base_names:
            indices.append(idx)
    return indices

def smooth_dict(data_dict, window_size=5):
    ys = sorted(data_dict.keys())
    values = [data_dict[y] for y in ys]
    window = np.ones(window_size) / window_size
    smoothed = np.convolve(values, window, mode='same')
    return {y: round(val, 6) for y, val in zip(ys, smoothed)}

def analyze_world(world_path, center_x, center_z):
    print(f"--- ANALIZA GĘSTOŚCI I RUDY ---")
    print(f"Świat: {world_path}")
    
    center_cx = center_x >> 4
    center_cz = center_z >> 4
    print(f"Centrum skanowania: Chunk ({center_cx}, {center_cz}) [czyli X={center_x}, Z={center_z}]")
    
    try:
        level = amulet.load_level(world_path)
    except Exception as e:
        print(f"[BŁĄD] Nie można otworzyć świata: {e}")
        return

    global_stats = {y: [0, 0] for y in range(MIN_Y, MAX_Y)}
    y_scan_counts = {y: 0 for y in range(MIN_Y, MAX_Y)}

    processed_chunks = 0
    total_chunks_to_scan = (2 * SCAN_RADIUS) ** 2
    total_ore_found = 0
    
    start_time = time.time()
    
    start_chunk_x = center_cx - SCAN_RADIUS
    end_chunk_x = center_cx + SCAN_RADIUS
    start_chunk_z = center_cz - SCAN_RADIUS
    end_chunk_z = center_cz + SCAN_RADIUS

    print(f"Zakres chunków: X[{start_chunk_x} do {end_chunk_x}], Z[{start_chunk_z} do {end_chunk_z}]")

    for cx in range(start_chunk_x, end_chunk_x):
        for cz in range(start_chunk_z, end_chunk_z):
            
            if not level.has_chunk(cx, cz, "minecraft:overworld"):
                continue

            try:
                chunk = level.get_chunk(cx, cz, "minecraft:overworld")
            except Exception:
                continue

            palette = chunk.block_palette
            
            target_ids = get_block_indices(palette, TARGET_BASE_NAMES)
            base_ids = get_block_indices(palette, BASE_BASE_NAMES)

            if not base_ids and not target_ids:
                continue
            
            for cy in chunk.blocks.sub_chunks:
                section_base_y = cy * 16
                
                if section_base_y > MAX_Y or (section_base_y + 16) < MIN_Y:
                    continue

                try:
                    sub_chunk = chunk.blocks.get_sub_chunk(cy)
                except:
                    continue
                
                if target_ids:
                    mask_ore = np.isin(sub_chunk, target_ids)
                    ore_counts = np.count_nonzero(mask_ore, axis=(0, 2))
                else:
                    ore_counts = np.zeros(16, dtype=int)

                if base_ids:
                    mask_base = np.isin(sub_chunk, base_ids)
                    base_counts = np.count_nonzero(mask_base, axis=(0, 2))
                else:
                    base_counts = np.zeros(16, dtype=int)
                
                for local_y in range(16):
                    real_y = section_base_y + local_y
                    
                    if MIN_Y <= real_y < MAX_Y:
                        val_ore = int(ore_counts[local_y])
                        val_base = int(base_counts[local_y])
                        
                        global_stats[real_y][1] += val_ore
                        global_stats[real_y][0] += val_base
                        
                        y_scan_counts[real_y] += 256
                        total_ore_found += val_ore

            processed_chunks += 1
            if processed_chunks % 100 == 0:
                print(f"\rPostęp: {processed_chunks}/{total_chunks_to_scan} | Rudy: {total_ore_found}...", end="")

    print("\n\nAnaliza zakończona. Przetwarzanie...")
    
    if total_ore_found == 0:
        print("[OSTRZEŻENIE] Nadal 0 rudy. Czy na pewno podałeś dobre kordy centrum?")
    
    output_data = {}
    raw_probs = {}
    raw_densities = {}

    for y in range(MIN_Y, MAX_Y):
        stone = global_stats[y][0]
        ore = global_stats[y][1]
        scanned_area = y_scan_counts[y]
        
        total_solid = stone + ore
        if total_solid > 0:
            prob = ore / total_solid
        else:
            prob = 0.0
        
        if scanned_area > 0:
            density = total_solid / scanned_area
        else:
            density = 0.0
            
        raw_probs[y] = prob
        raw_densities[y] = density

    smooth_probs = smooth_dict(raw_probs, 5)
    smooth_densities = smooth_dict(raw_densities, 5)
    
    for y in range(MIN_Y, MAX_Y):
        output_data[y] = {
            "prob": smooth_probs.get(y, 0),
            "stone_density": smooth_densities.get(y, 0)
        }

    with open("ore_distribution.json", "w") as f:
        json.dump(output_data, f, indent=4)
        
    with open("ore_stats_raw.csv", "w") as f:
        f.write("Y,Stone,Ore,ScannedArea,Prob_Raw,Density_Raw,Prob_Smooth,Density_Smooth\n")
        for y in range(MIN_Y, MAX_Y):
            f.write(f"{y},{global_stats[y][0]},{global_stats[y][1]},{y_scan_counts[y]},"
                    f"{raw_probs[y]:.6f},{raw_densities[y]:.6f},"
                    f"{smooth_probs[y]:.6f},{smooth_densities[y]:.6f}\n")

    print(f"\n[SUKCES] Znaleziono łącznie {total_ore_found} bloków rudy")
    print("Wyniki zapisano w 'ore_distribution.json'")

if __name__ == "__main__":
    path = DEFAULT_WORLD_PATH
    if not path or not os.path.exists(path):
        path = input("Podaj pełną ścieżkę do świata: ").strip()
    
    print("Podaj współrzędne gracza (żeby skanować wokół niego):")
    try:
        ux = int(input("X: ").strip())
        uz = int(input("Z: ").strip())
    except:
        print("Błędne dane, używam 0,0")
        ux, uz = 0, 0

    analyze_world(path, ux, uz)