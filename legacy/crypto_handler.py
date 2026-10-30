import os
import hashlib
from cryptography.hazmat.primitives.asymmetric import rsa, padding
from cryptography.hazmat.primitives import serialization, hashes
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

class CryptoHandler:
    @staticmethod
    def generate_keys():
        private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        public_key = private_key.public_key()
        
        pem_priv = private_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption()
        )
        pem_pub = public_key.public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo
        )
        return pem_priv, pem_pub

    @staticmethod
    def get_fingerprint_coords(data_bytes: bytes):
        digest = hashlib.sha256(data_bytes).hexdigest()
        hex_x = digest[0:2]
        hex_y = digest[2:4]
        hex_z = digest[4:6]
        
        x = (int(hex_x, 16) - 128) * 10 
        y = int(hex_y, 16)
        z = (int(hex_z, 16) - 128) * 10
        
        return x, y, z

    @staticmethod
    def encrypt_hybrid(data: bytes, recipient_pub_pem: bytes):
        session_key = os.urandom(32)
        iv = os.urandom(12)
        
        encryptor = Cipher(algorithms.AES(session_key), modes.GCM(iv)).encryptor()
        ciphertext = encryptor.update(data) + encryptor.finalize()
        tag = encryptor.tag
        
        encrypted_payload = iv + tag + ciphertext
        
        pub_key = serialization.load_pem_public_key(recipient_pub_pem)
        encrypted_session_key = pub_key.encrypt(
            session_key,
            padding.OAEP(
                mgf=padding.MGF1(algorithm=hashes.SHA256()),
                algorithm=hashes.SHA256(),
                label=None
            )
        )
        
        return encrypted_payload, encrypted_session_key

    @staticmethod
    def decrypt_hybrid(encrypted_payload: bytes, encrypted_session_key: bytes, private_key_pem: bytes):

        try:
            priv_key = serialization.load_pem_private_key(private_key_pem, password=None)
            session_key = priv_key.decrypt(
                encrypted_session_key,
                padding.OAEP(
                    mgf=padding.MGF1(algorithm=hashes.SHA256()),
                    algorithm=hashes.SHA256(),
                    label=None
                )
            )
            
            iv = encrypted_payload[:12]
            tag = encrypted_payload[12:28]
            ciphertext = encrypted_payload[28:]
            
            decryptor = Cipher(algorithms.AES(session_key), modes.GCM(iv, tag)).decryptor()
            return decryptor.update(ciphertext) + decryptor.finalize()
        except Exception as e:
            raise ValueError(f"Błąd deszyfracji (zły klucz lub uszkodzone dane): {e}")