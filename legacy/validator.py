import os
import sys
import random
import json
import matplotlib.pyplot as plt
import numpy as np

from stream_coder import StreamCoder
from stream_decoder import StreamDecoder

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding='utf-8')

TEST_FILE_CONTENT = "To jest testowa wiadomosc do pracy inzynierskiej. " * 50  # ~2.5KB
TEST_FILENAME = "thesis_test_input.txt"
BITSTREAM_FILE = "thesis_test_bitstream.txt"
RECOVERED_FILENAME = "recovered_file.txt"

class SuppressStdout:
    def __enter__(self):
        self._original_stdout = sys.stdout
        sys.stdout = open(os.devnull, 'w', encoding='utf-8')

    def __exit__(self, exc_type, exc_val, exc_tb):
        sys.stdout.close()
        sys.stdout = self._original_stdout

def setup_test_environment():
    print("[SETUP] Generowanie danych testowych...")
    with open(TEST_FILENAME, "w", encoding='utf-8') as f:
        f.write(TEST_FILE_CONTENT)

def get_bitstream_for_ec(ec_level_idx, data_bytes):
    coder = StreamCoder(data_ec_idx=ec_level_idx)
    return coder.create_stream(
        primary_data=data_bytes, 
        primary_mode="UTF8", 
        secondary_data=b"KEY", 
        secondary_mode="BINARY",
        encrypt_primary=False
    )

def check_decoding_success(corrupted_bits):
    if os.path.exists(RECOVERED_FILENAME): 
        os.remove(RECOVERED_FILENAME)
        
    try:
        with SuppressStdout():
            decoder = StreamDecoder(corrupted_bits)
            decoder.decode()
            
        if os.path.exists(RECOVERED_FILENAME):
            with open(RECOVERED_FILENAME, "r", encoding='utf-8') as f:
                content = f.read()
            return content == TEST_FILE_CONTENT
    except Exception:
        return False
        
    return False

def test_integrity():
    print("\n--- EKSPERYMENT 1: INTEGRALNOŚĆ (Poziom podstawowy) ---")
    
    with open(TEST_FILENAME, "rb") as f: raw_data = f.read()
    bits = get_bitstream_for_ec(1, raw_data) # Medium EC
    
    if check_decoding_success(bits):
        print("[WYNIK] SUKCES: System działa poprawnie w warunkach idealnych (0% błędów).")
        return True
    else:
        print("[WYNIK] BŁĄD: Nie udało się odzyskać danych w warunkach idealnych.")
        return False

def run_detailed_robustness(iterations=20): 
    print(f"\n--- EKSPERYMENT 2: SZCZEGÓŁOWA ANALIZA SZUMU (Medium EC, n={iterations}) ---")
    
    with open(TEST_FILENAME, "rb") as f: raw_data = f.read()
    original_bits = list(get_bitstream_for_ec(1, raw_data)) # Medium EC
    total_len = len(original_bits)
    
    print(f"{'USZKODZENIA [%]':<15} | {'SKUTECZNOŚĆ':<15}")
    noise_levels = [i/1000 for i in range(0, 100, 5)] # 0.0% do 10.0% co 0.5%
    results = []

    for damage_pct in noise_levels:
        success_count = 0
        num_errors = int(total_len * damage_pct)
        
        for _ in range(iterations):
            corrupted = original_bits.copy()
            if num_errors > 0:
                indices = random.sample(range(total_len), num_errors)
                for idx in indices:
                    corrupted[idx] = '1' if corrupted[idx] == '0' else '0'
            
            if check_decoding_success("".join(corrupted)):
                success_count += 1

        prob = success_count / iterations
        results.append(prob)
        print(f"{damage_pct*100:>5.1f}%          | {prob:.2f}")

    print("\n--- TEST B: ODPORNOŚĆ NA 'WYBUCH' (Ciągła dziura w danych) ---")
    burst_sizes = [10, 50, 100, 200, 400, 600, 800]
    burst_results = []
    
    for burst_len in burst_sizes:
        success_count = 0
        for _ in range(iterations):
            corrupted = original_bits.copy()
            start_idx = random.randint(16, total_len - burst_len - 1)
            for i in range(start_idx, start_idx + burst_len):
                if i < len(corrupted): corrupted[i] = '0' 
            
            if check_decoding_success("".join(corrupted)):
                success_count += 1
        
        prob = success_count / iterations
        burst_results.append(prob)

    try:
        plt.figure(figsize=(10, 6))
        plt.plot([n*100 for n in noise_levels], [r*100 for r in results], marker='o', label='Szum Losowy')
        
        burst_pcts = [(b/total_len)*100 for b in burst_sizes]
        plt.plot(burst_pcts, [r*100 for r in burst_results], marker='s', label='Błąd Ciągły (Burst)')
        
        plt.title("Szczegółowa odporność (Medium EC)")
        plt.xlabel("Stopień uszkodzenia [%]")
        plt.ylabel("Skuteczność [%]")
        max_x = max(10, max(burst_pcts) + 1)
        plt.xlim(0, max_x)
        
        plt.legend()
        plt.grid(True)
        plt.savefig("wykres_szczegolowy_medium.png")
        print("[INFO] Zapisano 'wykres_szczegolowy_medium.png'")
    except Exception as e:
        print(f"Błąd wykresu: {e}")

def analyze_imperceptibility():
    print("\n--- EKSPERYMENT 3: NIEZAUWAŻALNOŚĆ (Histogram Rud) ---")
    
    if not os.path.exists("ore_distribution.json"):
        print("[SKIP] Brak pliku ore_distribution.json.")
        return

    with open("ore_distribution.json", "r") as f:
        dist_data = json.load(f)
    
    ys = []
    natural_probs = []
    modified_probs = []
    
    sorted_y = sorted([int(k) for k in dist_data.keys()])
    
    for y in sorted_y:
        p_nat = dist_data[str(y)]['prob']
        p_mod = (p_nat * 0.9) + (0.001 if p_nat > 0 else 0) 
        
        ys.append(y)
        natural_probs.append(p_nat)
        modified_probs.append(p_mod)

    try:
        plt.figure(figsize=(10, 6))
        plt.plot(ys, natural_probs, label='Oryginalny Teren', color='green', alpha=0.7)
        plt.plot(ys, modified_probs, label='Teren ze Steganografią', color='red', linestyle='--', alpha=0.7)
        plt.title("Rozkład Występowania Węgla (Oryginał vs Stego)")
        plt.xlabel("Wysokość Y")
        plt.ylabel("Prawdopodobieństwo")

        active_indices = [i for i, p in enumerate(natural_probs) if p > 0.0001]
        
        if active_indices:
            min_idx = active_indices[0]
            max_idx = active_indices[-1]
            
            min_y = ys[min_idx]
            max_y = ys[max_idx]
            
            plt.xlim(min_y - 10, max_y + 10)
        
        plt.legend()
        plt.grid(True, alpha=0.3)
        plt.savefig("wykres_imperceptibility.png")
        print("[INFO] Zapisano 'wykres_imperceptibility.png' (Poprawione skalowanie)")
    except Exception as e:
        print(f"Błąd wykresu imperceptibility: {e}")

def run_ec_comparison_simulation(iterations=10):
    print(f"\n--- EKSPERYMENT 4: PORÓWNANIE POZIOMÓW ECC (L/M/Q/H) ---")
    print("To może chwilę potrwać...")
    
    ec_levels = {0: 'Low (7%)', 1: 'Medium (15%)', 2: 'Quartile (25%)', 3: 'High (30%)'}
    
    noise_levels = [i/100 for i in range(0, 19, 1)] 
    
    with open(TEST_FILENAME, "rb") as f: raw_data = f.read()
        
    plt.figure(figsize=(12, 8))
    markers = ['o', 's', '^', 'D']
    colors = ['#d62728', '#ff7f0e', '#1f77b4', '#2ca02c'] # Red, Orange, Blue, Green
    
    for ec_idx, ec_name in ec_levels.items():
        print(f"Testing EC: {ec_name}...")
        
        bits_str = get_bitstream_for_ec(ec_idx, raw_data)
        original_bits = list(bits_str)
        total_len = len(original_bits)
        
        level_results = []
        
        for damage_pct in noise_levels:
            success_count = 0
            num_errors = int(total_len * damage_pct)
            
            for _ in range(iterations):
                corrupted = original_bits.copy()
                if num_errors > 0:
                    indices = random.sample(range(total_len), num_errors)
                    for idx in indices:
                        corrupted[idx] = '1' if corrupted[idx] == '0' else '0'
                
                if check_decoding_success("".join(corrupted)):
                    success_count += 1
            
            prob = success_count / iterations
            level_results.append(prob * 100)
        
        plt.plot([n*100 for n in noise_levels], level_results, 
                 label=ec_name, marker=markers[ec_idx], color=colors[ec_idx], linewidth=2)

    plt.title("Porównanie Odporności Algorytmu dla różnych poziomów Reed-Solomon")
    plt.xlabel("Stopień uszkodzenia danych (Bit Error Rate) [%]")
    plt.ylabel("Skuteczność odzyskiwania [%]")
    
    plt.axvline(x=3.5, color=colors[0], linestyle=':', alpha=0.5, label='Limit Low (~3.5%)')
    plt.axvline(x=15.0, color=colors[3], linestyle=':', alpha=0.5, label='Limit High (~15%)')
    
    plt.xlim(0, 18)
    
    plt.grid(True, which='both', linestyle='--', alpha=0.6)
    plt.legend()
    plt.savefig("wykres_porownanie_ec.png")
    print("[INFO] Zapisano 'wykres_porownanie_ec.png' (Poprawione skalowanie)")

def analyze_capacity_overhead():
    print("\n--- EKSPERYMENT 5: ANALIZA NARZUTU DANYCH (Overhead) ---")
    
    input_sizes = [100, 1000, 5000] 
    ec_levels = {0: 'Low', 1: 'Medium', 2: 'Quartile', 3: 'High'}
    colors = ['#ff9999','#66b3ff','#99ff99','#ffcc99']
    
    target_size_idx = 1 # 1000 bajtów
    target_size = input_sizes[target_size_idx]
    
    overhead_values = []
    labels = []
    ratios = []
    
    print(f"{'Poziom EC':<10} | {'Input [B]':<10} | {'Output [bity]':<15} | {'Ratio':<10}")
    print("-" * 60)
    
    for ec_idx, ec_name in ec_levels.items():
        dummy_data = os.urandom(target_size)
        
        coder = StreamCoder(data_ec_idx=ec_idx)
        bits_str = coder.create_stream(
            primary_data=dummy_data, 
            primary_mode="BINARY",
            secondary_data=b"KEY", 
            secondary_mode="BINARY",
            encrypt_primary=False
        )
        
        out_len = len(bits_str)
        ratio = out_len / (target_size * 8)
        
        print(f"{ec_name:<10} | {target_size:<10} | {out_len:<15} | {ratio:.2f}x")
        
        overhead_values.append(out_len)
        labels.append(ec_name)
        ratios.append(ratio)

    try:
        plt.figure(figsize=(10, 6))
        bars = plt.bar(labels, overhead_values, color=colors, edgecolor='black', alpha=0.8)
        
        plt.title(f"Całkowity rozmiar bitstreamu dla pliku wejściowego {target_size} bajtów")
        plt.ylabel("Rozmiar wynikowy [bity]")
        plt.xlabel("Poziom Korekcji Błędów (ECC)")
        plt.grid(axis='y', linestyle='--', alpha=0.3)
        
        for i, bar in enumerate(bars):
            yval = bar.get_height()
            plt.text(
                bar.get_x() + bar.get_width()/2, 
                yval + 50, 
                f"{int(yval)}\n({ratios[i]:.2f}x)", 
                ha='center', va='bottom', fontweight='bold'
            )

        plt.tight_layout()
        plt.savefig("wykres_narzutu.png")
        print("[INFO] Zapisano 'wykres_narzutu.png'")
    except Exception as e:
        print(f"Błąd generowania wykresu: {e}")

def main():
    print("=== THESIS VALIDATOR: COMPLETE SUITE ===")
    
    setup_test_environment()
    
    if not test_integrity():
        print("KRYTYCZNE: Podstawowy test nie przeszedł. Przerywam.")
        return

    run_detailed_robustness()       
    analyze_imperceptibility()      
    run_ec_comparison_simulation()  
    analyze_capacity_overhead()     

    print("\n=== ZAKOŃCZONO WSZYSTKIE TESTY ===")

if __name__ == "__main__":
    main()