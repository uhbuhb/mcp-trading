"""
Authentication utilities for retrieving per-user credentials.

This module provides the bridge between OAuth tokens and trading platform credentials.
"""
import os
import logging
from datetime import datetime, timezone
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
) -> Tuple[str, str, Optional[str], Optional[str], Optional[datetime]]:
    """
    Retrieve and decrypt trading credentials for a user.

    This function:
    1. Fetches encrypted credentials from database
    2. Decrypts them in-memory
    3. Returns plaintext credentials for immediate use
    4. Credentials should be cleared from memory after use

    Args:
        user_id: User ID from OAuth token
        platform: Trading platform (e.g., 'tradier', 'schwab')
        environment: 'sandbox' or 'production'
        db: Database session

    Returns:
        Tuple of (access_token, account_number, refresh_token, account_hash, token_expires_at)
        - refresh_token: Optional, for OAuth platforms like Schwab
        - account_hash: Optional, for platforms using hashes instead of numbers
        - token_expires_at: Optional, OAuth token expiration time

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

        # Decrypt optional fields for OAuth platforms
        refresh_token = None
        if credential.encrypted_refresh_token:
            refresh_token = encryption_service.decrypt_credential(credential.encrypted_refresh_token)

        account_hash = None
        if credential.encrypted_account_hash:
            account_hash = encryption_service.decrypt_credential(credential.encrypted_account_hash)

        token_expires_at = credential.token_expires_at

        logger.info(f"Successfully decrypted credentials for user {user_id}")
        return access_token, account_number, refresh_token, account_hash, token_expires_at

    except Exception as e:
        logger.error(f"Failed to decrypt credentials for user {user_id}: {e}")
        raise ValueError(f"Failed to decrypt credentials: {e}")

def store_user_trading_credentials(
    user_id: str,
    platform: str,
    environment: str,
    access_token: str,
    account_number: str,
    db: Session,
    refresh_token: Optional[str] = None,
    account_hash: Optional[str] = None,
    token_expires_at: Optional[datetime] = None
) -> None:
    """
    Encrypt and store trading credentials for a user.

    Args:
        user_id: User ID
        platform: Trading platform (e.g., 'tradier', 'schwab')
        environment: 'sandbox' or 'production'
        access_token: Plain text access token
        account_number: Plain text account number
        db: Database session
        refresh_token: Optional OAuth refresh token (for platforms like Schwab)
        account_hash: Optional account hash (for platforms using hashes)
        token_expires_at: Optional OAuth token expiration datetime
    """
    logger.info(f"Storing credentials for user {user_id}, platform {platform}, env {environment}")

    # Encrypt credentials
    encryption_service = get_encryption_service()
    encrypted_token, encrypted_account = encryption_service.encrypt_credentials(
        access_token, account_number
    )

    # Encrypt optional fields
    encrypted_refresh = None
    if refresh_token:
        encrypted_refresh = encryption_service.encrypt_credential(refresh_token)

    encrypted_hash = None
    if account_hash:
        encrypted_hash = encryption_service.encrypt_credential(account_hash)

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
        credential.encrypted_refresh_token = encrypted_refresh
        credential.encrypted_account_hash = encrypted_hash
        credential.token_expires_at = token_expires_at
        credential.updated_at = datetime.now(timezone.utc)
        logger.info(f"Updated credentials for user {user_id}")
    else:
        # Create new
        credential = UserCredential(
            user_id=user_id,
            platform=platform,
            environment=environment,
            encrypted_access_token=encrypted_token,
            encrypted_account_number=encrypted_account,
            encrypted_refresh_token=encrypted_refresh,
            encrypted_account_hash=encrypted_hash,
            token_expires_at=token_expires_at
        )
        db.add(credential)
        logger.info(f"Created new credentials for user {user_id}")

    db.commit()
    logger.info(f"Credentials stored successfully for user {user_id}")

