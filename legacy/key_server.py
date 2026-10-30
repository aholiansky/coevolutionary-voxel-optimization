import os
import zipfile
from flask import Flask, request, send_file, jsonify
from werkzeug.utils import secure_filename

app = Flask(__name__)

KEYS_DIR = "keys_storage"
MAPS_DIR = "maps_storage"

for folder in [KEYS_DIR, MAPS_DIR]:
    if not os.path.exists(folder):
        os.makedirs(folder)

@app.route('/')
def home():
    return "Minecraft Stego Server is running!"

@app.route('/register', methods=['POST'])
def register_key():
    user_id = request.form.get('user_id')
    if not user_id: return jsonify({"error": "Missing user_id"}), 400
    if 'key_file' not in request.files: return jsonify({"error": "Missing key_file"}), 400
        
    file = request.files['key_file']
    save_path = os.path.join(KEYS_DIR, f"{user_id}.pem")
    file.save(save_path)
    print(f"[SERVER] Zarejestrowano klucz dla: {user_id}")
    return jsonify({"message": f"Key registered for {user_id}"}), 200

@app.route('/get_key/<user_id>', methods=['GET'])
def get_key(user_id):
    path = os.path.join(KEYS_DIR, f"{user_id}.pem")
    if os.path.exists(path):
        return send_file(path, mimetype='application/x-pem-file')
    else:
        return jsonify({"error": "User not found"}), 404

@app.route('/upload_map', methods=['POST'])
def upload_map():
    recipient_id = request.form.get('recipient_id')
    if not recipient_id:
        return jsonify({"error": "Missing recipient_id"}), 400

    if 'map_archive' not in request.files:
        return jsonify({"error": "Missing map_archive (zip file)"}), 400
    
    file = request.files['map_archive']
    filename = secure_filename(file.filename)
    
    if not filename.endswith('.zip'):
        return jsonify({"error": "File must be a .zip archive"}), 400

    zip_path = os.path.join(MAPS_DIR, f"{recipient_id}_temp.zip")
    file.save(zip_path)

    extract_folder_name = filename.replace('.zip', '')
    recipient_dir = os.path.join(MAPS_DIR, recipient_id)
    final_extract_path = os.path.join(recipient_dir, extract_folder_name)
    
    if not os.path.exists(final_extract_path):
        os.makedirs(final_extract_path)

    try:
        print(f"[SERVER] Rozpakowywanie mapy dla {recipient_id}...")
        with zipfile.ZipFile(zip_path, 'r') as zip_ref:
            zip_ref.extractall(final_extract_path)
        
        os.remove(zip_path)
        
        print(f"[SERVER] Mapa gotowa w: {final_extract_path}")
        return jsonify({
            "message": "Map uploaded and extracted successfully",
            "path": final_extract_path
        }), 200
        
    except zipfile.BadZipFile:
        return jsonify({"error": "Invalid zip file"}), 400
    except Exception as e:
        return jsonify({"error": str(e)}), 500

if __name__ == '__main__':
    print("=== SERWER STEGANOGRAFII (PORT 5000) ===")
    app.run(debug=True, port=5000)