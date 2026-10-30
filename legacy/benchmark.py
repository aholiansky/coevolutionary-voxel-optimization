import time
import psutil
import os
import threading
import numpy as np
import matplotlib.pyplot as plt
from io import BytesIO
import injector
import extractor
from stream_coder import StreamCoder

TEST_SIZES = [100, 500, 1000, 2500, 5000, 10000, 25000, 50000, 100000, 250000, 500000] 
ITERATIONS = 3
MOCK_DISTRIBUTION_FILE = "ore_distribution.json"

class MockBlock:
    def __init__(self, base_name):
        self.base_name = base_name

class MockPalette:
    def __init__(self):
        self._blocks = {0: MockBlock("stone"), 1: MockBlock("coal_ore")}
    
    def __getitem__(self, item):
        return self._blocks.get(item, MockBlock("air"))
    
    def get_add_block(self, block):
        if "coal" in block.base_name: return 1
        return 0

class MockChunk:
    def __init__(self):
        self.raw_blocks = np.zeros((16, 384, 16), dtype=int)
        self.block_palette = MockPalette()
        self.changed = False

    @property
    def blocks(self):
        return self

    def __getitem__(self, idx):
        x, y, z = idx
        array_y = y + 64
        if 0 <= array_y < 384:
            return self.raw_blocks[x, array_y, z]
        return 0

    def __setitem__(self, idx, value):
        x, y, z = idx
        array_y = y + 64
        if 0 <= array_y < 384:
            self.raw_blocks[x, array_y, z] = value

class MockLevel:
    def __init__(self):
        self.chunks = {}

    def get_chunk(self, cx, cz, dimension):
        if (cx, cz) not in self.chunks:
            self.chunks[(cx, cz)] = MockChunk()
        return self.chunks[(cx, cz)]
    
    def save(self):
        pass
    
    def close(self):
        pass

class ResourceMonitor(threading.Thread):
    def __init__(self):
        threading.Thread.__init__(self)
        self.running = True
        self.cpu_usage = []
        self.ram_usage = [] # MB
        self.process = psutil.Process(os.getpid())

    def run(self):
        while self.running:
            self.cpu_usage.append(self.process.cpu_percent(interval=None))
            mem_info = self.process.memory_info()
            self.ram_usage.append(mem_info.rss / 1024 / 1024) 
            time.sleep(0.05)

    def stop(self):
        self.running = False

    def get_stats(self):
        if not self.cpu_usage: return 0, 0
        avg_cpu = sum(self.cpu_usage) / len(self.cpu_usage)
        max_ram = max(self.ram_usage)
        return avg_cpu, max_ram

def benchmark_operation(func, *args):
    monitor = ResourceMonitor()
    
    psutil.cpu_percent()
    
    monitor.start()
    start_time = time.time()
    
    try:
        result = func(*args)
    except Exception as e:
        print(f" [BŁĄD KRYTYCZNY W TESTACH]: {e}")
        result = None
    
    end_time = time.time()
    monitor.stop()
    monitor.join()
    
    avg_cpu, max_ram = monitor.get_stats()
    duration = end_time - start_time
    
    return duration, avg_cpu, max_ram, result

def run_performance_suite():
    print("=== PERFORMANCE TEST SUITE (INJECTOR & EXTRACTOR) ===")
    
    if not os.path.exists(MOCK_DISTRIBUTION_FILE):
        print(f"[SETUP] Generowanie tymczasowego {MOCK_DISTRIBUTION_FILE}...")
        import json
        dummy_dist = {str(y): {"prob": 0.05} for y in range(-64, 320)}
        with open(MOCK_DISTRIBUTION_FILE, "w") as f:
            json.dump(dummy_dist, f)
    
    model = injector.ProbabilityModel(MOCK_DISTRIBUTION_FILE)
    
    results = {
        'sizes': TEST_SIZES,
        'inject_time': [], 'inject_ram': [], 'inject_cpu': [],
        'extract_time': [], 'extract_ram': [], 'extract_cpu': []
    }

    coder = StreamCoder(data_ec_idx=1) # Medium EC

    for size in TEST_SIZES:
        print(f"\n--- TEST: {size} Bytes Payload ---")
        
        raw_data = os.urandom(size)
        
        bitstream_str = coder.create_stream(
            primary_data=raw_data,
            primary_mode="BINARY",
            secondary_data=b"KEY_MOCK",
            secondary_mode="BINARY",
            encrypt_primary=False
        )
        total_bits = len(bitstream_str)
        print(f"Długość bitstreamu: {total_bits} bitów (~{total_bits/8/1024:.2f} KB)")

        i_times, i_rams, i_cpus = [], [], []
        e_times, e_rams, e_cpus = [], [], []

        for it in range(ITERATIONS):
            level = MockLevel()
            dt, cpu, ram, _ = benchmark_operation(
                injector.inject_bitstream, 
                level, 0, 0, bitstream_str, model
            )
            i_times.append(dt); i_rams.append(ram); i_cpus.append(cpu)
            dt_e, cpu_e, ram_e, extracted_bits = benchmark_operation(
                extractor.extract_smart,
                level, 0, 0, model
            )
            e_times.append(dt_e); e_rams.append(ram_e); e_cpus.append(cpu_e)
            print(f" Iteracja {it+1}: Inj={dt:.2f}s, Ext={dt_e:.2f}s")
        results['inject_time'].append(np.mean(i_times))
        results['inject_ram'].append(np.mean(i_rams))
        results['inject_cpu'].append(np.mean(i_cpus))
        results['extract_time'].append(np.mean(e_times))
        results['extract_ram'].append(np.mean(e_rams))
        results['extract_cpu'].append(np.mean(e_cpus))

    print("\nGenerowanie wykresów wydajności...")
    
    fig, axs = plt.subplots(1, 3, figsize=(18, 5))
    
    axs[0].plot(TEST_SIZES, results['inject_time'], 'o-', label='Iniekcja')
    axs[0].plot(TEST_SIZES, results['extract_time'], 's-', label='Ekstrakcja')
    axs[0].set_title("Czas Wykonania vs Rozmiar Danych")
    axs[0].set_xlabel("Rozmiar Payloadu [bajty]")
    axs[0].set_ylabel("Czas [s]")
    axs[0].legend()
    axs[0].grid(True)

    axs[1].plot(TEST_SIZES, results['inject_ram'], 'o-', label='Iniekcja')
    axs[1].plot(TEST_SIZES, results['extract_ram'], 's-', label='Ekstrakcja')
    axs[1].set_title("Maksymalne Zużycie Pamięci RAM")
    axs[1].set_xlabel("Rozmiar Payloadu [bajty]")
    axs[1].set_ylabel("RAM [MB]")
    axs[1].legend()
    axs[1].grid(True)

    axs[2].plot(TEST_SIZES, results['inject_cpu'], 'o-', label='Iniekcja')
    axs[2].plot(TEST_SIZES, results['extract_cpu'], 's-', label='Ekstrakcja')
    axs[2].set_title("Średnie Obciążenie CPU")
    axs[2].set_xlabel("Rozmiar Payloadu [bajty]")
    axs[2].set_ylabel("CPU [%]")
    axs[2].legend()
    axs[2].grid(True)

    plt.tight_layout()
    plt.savefig("wykres_wydajnosci.png")
    print("[SUKCES] Zapisano 'wykres_wydajnosci.png'")

if __name__ == "__main__":
    run_performance_suite()