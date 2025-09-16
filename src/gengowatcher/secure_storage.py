import os
import json
import base64
import logging
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from pathlib import Path
from typing import Optional


class SecureKeyStorage:
    """Securely stores and retrieves API keys using encryption"""
    
    def __init__(self, storage_file: str = "captcha_keys.json", logger: logging.Logger = None):
        self.storage_file = Path(storage_file)
        self.logger = logger or logging.getLogger(__name__)
        self._key = self._derive_key()
        self._cipher = Fernet(self._key)
    
    def _derive_key(self) -> bytes:
        """Derive encryption key from system information"""
        # Use a combination of system-specific information as salt
        try:
            # Try to get more system information
            if hasattr(os, 'uname'):
                salt_data = f"{os.getlogin()}_{os.uname().nodename}_{os.uname().machine}".encode()
            else:
                salt_data = f"{os.getlogin()}_{os.path.expanduser('~')}".encode()
        except Exception:
            # Fallback to a simpler salt
            salt_data = b"gengowatcher_fallback_salt_2025"
        
        # Use a fixed password (in a real implementation, this might come from user input)
        password = b"gengowatcher_captcha_protection_2025"
        
        kdf = PBKDF2HMAC(
            algorithm=hashes.SHA256(),
            length=32,
            salt=salt_data,
            iterations=100000,
        )
        return base64.urlsafe_b64encode(kdf.derive(password))
    
    def store_api_key(self, service: str, api_key: str) -> bool:
        """Securely store an API key"""
        try:
            # Load existing data
            data = {}
            if self.storage_file.exists():
                with open(self.storage_file, 'rb') as f:
                    encrypted_data = f.read()
                if encrypted_data:
                    decrypted_data = self._cipher.decrypt(encrypted_data)
                    data = json.loads(decrypted_data)
            
            # Store the new key
            data[service] = api_key
            
            # Encrypt and save
            json_data = json.dumps(data)
            encrypted_data = self._cipher.encrypt(json_data.encode())
            
            # Create directory if it doesn't exist
            self.storage_file.parent.mkdir(parents=True, exist_ok=True)
            
            with open(self.storage_file, 'wb') as f:
                f.write(encrypted_data)
            
            # Set restrictive file permissions (read/write for owner only)
            try:
                self.storage_file.chmod(0o600)
            except Exception as e:
                self.logger.warning(f"Failed to set restrictive permissions on storage file: {e}")
            
            self.logger.info(f"API key for {service} stored securely")
            return True
            
        except Exception as e:
            self.logger.error(f"Failed to store API key: {e}")
            return False
    
    def retrieve_api_key(self, service: str) -> Optional[str]:
        """Retrieve a stored API key"""
        try:
            if not self.storage_file.exists():
                return None
            
            with open(self.storage_file, 'rb') as f:
                encrypted_data = f.read()
            
            if not encrypted_data:
                return None
            
            decrypted_data = self._cipher.decrypt(encrypted_data)
            data = json.loads(decrypted_data)
            
            return data.get(service)
            
        except Exception as e:
            self.logger.error(f"Failed to retrieve API key: {e}")
            return None
    
    def delete_api_key(self, service: str) -> bool:
        """Delete a stored API key"""
        try:
            if not self.storage_file.exists():
                return True
            
            with open(self.storage_file, 'rb') as f:
                encrypted_data = f.read()
            
            if not encrypted_data:
                return True
            
            decrypted_data = self._cipher.decrypt(encrypted_data)
            data = json.loads(decrypted_data)
            
            if service in data:
                del data[service]
                
                # Encrypt and save
                json_data = json.dumps(data)
                encrypted_data = self._cipher.encrypt(json_data.encode())
                
                with open(self.storage_file, 'wb') as f:
                    f.write(encrypted_data)
                
                self.logger.info(f"API key for {service} deleted")
            
            return True
            
        except Exception as e:
            self.logger.error(f"Failed to delete API key: {e}")
            return False