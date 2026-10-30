import json
import matplotlib.pyplot as plt
from mpl_toolkits.mplot3d import Axes3D
import os

LOG_FILE = "injection_log.json"

def main():
    print("=== STEGO VISUALIZER 3D ===")
    
    if not os.path.exists(LOG_FILE):
        print(f"Brak pliku '{LOG_FILE}'. Uruchom najpierw injector.py!")
        return

    print(f"Wczytywanie danych z {LOG_FILE}...")
    try:
        with open(LOG_FILE, "r") as f:
            data = json.load(f)
    except Exception as e:
        print(f"Błąd odczytu JSON: {e}")
        return

    if not data:
        print("Brak danych w logu.")
        return

    print(f"Wczytano {len(data)} punktów. Generowanie wykresów...")

    xs = [d[0] for d in data]
    ys = [d[1] for d in data]
    zs = [d[2] for d in data]
    bits = [d[3] for d in data]

    colors = ['red' if b == 1 else 'lightgray' for b in bits]
    sizes = [15 if b == 1 else 5 for b in bits]

    fig = plt.figure(figsize=(16, 8))
    fig.suptitle(f"Wizualizacja Iniekcji Steganograficznej ({len(data)} bitów)", fontsize=16)

    ax1 = fig.add_subplot(1, 3, 1, projection='3d')
    ax1.set_title("Chmura Danych (3D)")
    ax1.scatter(xs, zs, ys, c=colors, s=sizes, alpha=0.6, marker='s')
    ax1.set_xlabel('X')
    ax1.set_ylabel('Z (Północ-Południe)')
    ax1.set_zlabel('Y (Wysokość)')
    ax1.set_box_aspect([1, 1, 1.5]) 

    ax2 = fig.add_subplot(1, 3, 2)
    ax2.set_title("Widok z góry (X/Z) - Spirala")
    ax2.scatter(xs, zs, c=colors, s=sizes, alpha=0.5, marker='s')
    ax2.set_xlabel('X')
    ax2.set_ylabel('Z')
    ax2.grid(True, linestyle='--', alpha=0.5)
    ax2.set_aspect('equal')

    ax3 = fig.add_subplot(1, 3, 3)
    ax3.set_title("Profil Boczny (Z/Y) - Warstwy")
    ax3.scatter(zs, ys, c=colors, s=sizes, alpha=0.5, marker='s')
    ax3.set_xlabel('Z')
    ax3.set_ylabel('Y (Wysokość)')
    ax3.grid(True, linestyle='--', alpha=0.5)

    from matplotlib.lines import Line2D
    legend_elements = [
        Line2D([0], [0], marker='s', color='w', label='Bit 1 (Ruda)', markerfacecolor='red', markersize=10),
        Line2D([0], [0], marker='s', color='w', label='Bit 0 (Kamień)', markerfacecolor='lightgray', markersize=10)
    ]
    fig.legend(handles=legend_elements, loc='upper right')

    print("Wyświetlanie okna...")
    plt.tight_layout()
    plt.show()

if __name__ == "__main__":
    main()