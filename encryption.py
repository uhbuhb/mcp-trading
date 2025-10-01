"""
Credential encryption service using Fernet (symmetric encryption).

CRITICAL SECURITY NOTES:
- The ENCRYPTION_KEY must be stored securely (Railway secrets, not in code)
- Key rotation should be implemented for production
- Encryption key should be 32 URL-safe base64-encoded bytes
"""
import os
import logging
from typing import Tuple, Optional
from cryptography.fernet import Fernet

logger = logging.getLogger("encryption")

class CredentialEncryption:
    """Service for encrypting and decrypting user credentials."""
    
    def __init__(self, encryption_key: Optional[str] = None):
        """
        Initialize encryption service.
        
        Args:
            encryption_key: Base64-encoded Fernet key. If not provided, reads from environment.
        
        Raises:
            ValueError: If no encryption key is available
        """
        if encryption_key is None:
            encryption_key = os.getenv("ENCRYPTION_KEY")
        
        if not encryption_key:
            # For development only - generate a new key
            # In production, this MUST be set in Railway secrets
            logger.warning("No ENCRYPTION_KEY found in environment. Generating new key for development.")
            logger.warning("⚠️  This key will be lost on restart! Set ENCRYPTION_KEY in production.")
            encryption_key = Fernet.generate_key().decode()
            logger.info(f"Generated encryption key: {encryption_key}")
            logger.info("Add this to your Railway secrets: ENCRYPTION_KEY={key}")
        
        try:
            self.fernet = Fernet(encryption_key.encode() if isinstance(encryption_key, str) else encryption_key)
            logger.info("Encryption service initialized successfully")
        except Exception as e:
            logger.error(f"Failed to initialize encryption: {e}")
            raise ValueError(f"Invalid encryption key: {e}")
    
    def encrypt_credential(self, credential: str) -> bytes:
        """
        Encrypt a credential string.
        
        Args:
            credential: Plain text credential to encrypt
        
        Returns:
            Encrypted credential as bytes
        """
        if not credential:
            raise ValueError("Cannot encrypt empty credential")
        
        try:
            encrypted = self.fernet.encrypt(credential.encode())
            logger.debug("Credential encrypted successfully")
            return encrypted
        except Exception as e:
            logger.error(f"Encryption failed: {e}")
            raise
    
    def decrypt_credential(self, encrypted_credential: bytes) -> str:
        """
        Decrypt an encrypted credential.
        
        Args:
            encrypted_credential: Encrypted credential bytes
        
        Returns:
            Decrypted credential string
        """
        if not encrypted_credential:
            raise ValueError("Cannot decrypt empty credential")
        
        try:
            decrypted = self.fernet.decrypt(encrypted_credential).decode()
            logger.debug("Credential decrypted successfully")
            return decrypted
        except Exception as e:
            logger.error(f"Decryption failed: {e}")
            raise
    
    def encrypt_credentials(self, access_token: str, account_number: str) -> Tuple[bytes, bytes]:
        """
        Encrypt both access token and account number.
        
        Args:
            access_token: Trading platform access token
            account_number: Trading account number
        
        Returns:
            Tuple of (encrypted_token, encrypted_account_number)
        """
        encrypted_token = self.encrypt_credential(access_token)
        encrypted_account = self.encrypt_credential(account_number)
        logger.info("Credentials encrypted successfully")
        return encrypted_token, encrypted_account
    
    def decrypt_credentials(self, encrypted_token: bytes, encrypted_account: bytes) -> Tuple[str, str]:
        """
        Decrypt both access token and account number.
        
        Args:
            encrypted_token: Encrypted access token
            encrypted_account: Encrypted account number
        
        Returns:
            Tuple of (access_token, account_number)
        """
        access_token = self.decrypt_credential(encrypted_token)
        account_number = self.decrypt_credential(encrypted_account)
        logger.debug("Credentials decrypted successfully")
        return access_token, account_number

# Global encryption service instance
_encryption_service: Optional[CredentialEncryption] = None

def get_encryption_service() -> CredentialEncryption:
    """Get or create the global encryption service instance."""
    global _encryption_service
    if _encryption_service is None:
        _encryption_service = CredentialEncryption()
    return _encryption_service

def generate_encryption_key() -> str:
    """
    Generate a new Fernet encryption key.
    
    Use this once to generate your ENCRYPTION_KEY for Railway.
    
    Returns:
        Base64-encoded encryption key
    """
    key = Fernet.generate_key().decode()
    print("=" * 60)
    print("🔐 NEW ENCRYPTION KEY GENERATED")
    print("=" * 60)
    print(f"\nAdd this to your Railway environment variables:\n")
    print(f"ENCRYPTION_KEY={key}\n")
    print("⚠️  KEEP THIS SECRET! Store it securely in Railway.")
    print("=" * 60)
    return key

if __name__ == "__main__":
    # Generate a key for initial setup
    generate_encryption_key()

