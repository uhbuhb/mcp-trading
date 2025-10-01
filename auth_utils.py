"""
Authentication utilities for retrieving per-user credentials.

This module provides the bridge between OAuth tokens and trading platform credentials.
"""
import os
import logging
from datetime import datetime
from typing import Tuple, Optional
from sqlalchemy.orm import Session

from database import User, UserCredential
from encryption import get_encryption_service

logger = logging.getLogger("auth_utils")

def get_user_trading_credentials(
    user_id: str,
    platform: str,
    environment: str,
    db: Session
) -> Tuple[str, str]:
    """
    Retrieve and decrypt trading credentials for a user.
    
    This function:
    1. Fetches encrypted credentials from database
    2. Decrypts them in-memory
    3. Returns plaintext credentials for immediate use
    4. Credentials should be cleared from memory after use
    
    Args:
        user_id: User ID from OAuth token
        platform: Trading platform (e.g., 'tradier')
        environment: 'sandbox' or 'production'
        db: Database session
    
    Returns:
        Tuple of (access_token, account_number)
    
    Raises:
        ValueError: If credentials not found or decryption fails
    """
    logger.info(f"Fetching credentials for user {user_id}, platform {platform}, env {environment}")
    
    # Fetch encrypted credentials
    credential = db.query(UserCredential).filter(
        UserCredential.user_id == user_id,
        UserCredential.platform == platform,
        UserCredential.environment == environment
    ).first()
    
    if not credential:
        logger.error(f"No credentials found for user {user_id} on {platform} ({environment})")
        raise ValueError(
            f"No {platform} credentials configured for {environment}. "
            f"Please visit {os.getenv('SERVER_URL', 'http://localhost:8000')}/setup to add your credentials."
        )
    
    # Decrypt credentials
    encryption_service = get_encryption_service()
    try:
        access_token, account_number = encryption_service.decrypt_credentials(
            credential.encrypted_access_token,
            credential.encrypted_account_number
        )
        
        logger.info(f"Successfully decrypted credentials for user {user_id}")
        return access_token, account_number
        
    except Exception as e:
        logger.error(f"Failed to decrypt credentials for user {user_id}: {e}")
        raise ValueError(f"Failed to decrypt credentials: {e}")

def store_user_trading_credentials(
    user_id: str,
    platform: str,
    environment: str,
    access_token: str,
    account_number: str,
    db: Session
) -> None:
    """
    Encrypt and store trading credentials for a user.
    
    Args:
        user_id: User ID
        platform: Trading platform (e.g., 'tradier')
        environment: 'sandbox' or 'production'
        access_token: Plain text access token
        account_number: Plain text account number
        db: Database session
    """
    logger.info(f"Storing credentials for user {user_id}, platform {platform}, env {environment}")
    
    # Encrypt credentials
    encryption_service = get_encryption_service()
    encrypted_token, encrypted_account = encryption_service.encrypt_credentials(
        access_token, account_number
    )
    
    # Check if credentials already exist
    credential = db.query(UserCredential).filter(
        UserCredential.user_id == user_id,
        UserCredential.platform == platform,
        UserCredential.environment == environment
    ).first()
    
    if credential:
        # Update existing
        credential.encrypted_access_token = encrypted_token
        credential.encrypted_account_number = encrypted_account
        credential.updated_at = datetime.utcnow()
        logger.info(f"Updated credentials for user {user_id}")
    else:
        # Create new
        credential = UserCredential(
            user_id=user_id,
            platform=platform,
            environment=environment,
            encrypted_access_token=encrypted_token,
            encrypted_account_number=encrypted_account
        )
        db.add(credential)
        logger.info(f"Created new credentials for user {user_id}")
    
    db.commit()
    logger.info(f"Credentials stored successfully for user {user_id}")

