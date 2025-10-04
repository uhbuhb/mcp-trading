"""
Trading Client Factory

This module provides a centralized factory for creating trading platform clients
with consistent error handling and credential management.
"""
import logging
from typing import Dict, Any, Optional, Tuple
from datetime import datetime

from tradier_client import TradierClient
from schwab_client import SchwabClient
from trading_platform_interface import TradingPlatformInterface
from auth_utils import get_user_trading_credentials
from error_handling import TradingError, ErrorCode, validate_platform

logger = logging.getLogger("trading_client_factory")

# Platform to base URL mapping
PLATFORM_BASE_URLS = {
    "tradier": "https://api.tradier.com",
    "tradier_paper": "https://sandbox.tradier.com",
    "schwab": None  # Schwab handles its own base URL
}

class TradingClientFactory:
    """Factory class for creating trading platform clients."""
    
    @staticmethod
    def create_client(
        platform: str,
        credentials: Dict[str, Any]
    ) -> Tuple[TradingPlatformInterface, str]:
        """
        Create a trading client for the specified platform.
        
        Args:
            platform: Trading platform ('tradier', 'tradier_paper', 'schwab')
            credentials: Dictionary containing platform-specific credentials
            
        Returns:
            Tuple of (client, account_identifier)
            - For Tradier: account_identifier is account_number
            - For Schwab: account_identifier is account_hash
            
        Raises:
            TradingError: If platform is unsupported or credentials are invalid
        """
        logger.info(f"Creating trading client for platform: {platform}")
        
        # Validate platform
        validate_platform(platform)
        
        try:
            if platform in ["tradier", "tradier_paper"]:
                return TradingClientFactory._create_tradier_client(platform, credentials)
            elif platform == "schwab":
                return TradingClientFactory._create_schwab_client(credentials)
            else:
                raise TradingError(
                    f"Platform {platform} not implemented",
                    ErrorCode.TRADING_PLATFORM_ERROR
                )
        except TradingError:
            raise
        except Exception as e:
            logger.error(f"Failed to create {platform} client: {e}")
            raise TradingError(
                f"Failed to create {platform} client: {str(e)}",
                ErrorCode.TRADING_PLATFORM_ERROR,
                details={"platform": platform, "error": str(e)}
            )
    
    @staticmethod
    def create_client_for_user(
        user_id: str,
        platform: str,
        db
    ) -> Tuple[TradingPlatformInterface, str]:
        """
        Create a trading client with user-specific credentials from database.
        
        Args:
            user_id: Authenticated user ID from OAuth token
            platform: Trading platform (e.g., 'tradier', 'tradier_paper', 'schwab')
            db: Database session
            
        Returns:
            Tuple of (client, account_identifier)
            
        Raises:
            TradingError: If credentials not found or decryption fails
        """
        logger.info(f"Creating client for user {user_id}, platform {platform}")
        
        try:
            # Fetch and decrypt credentials
            access_token, account_number, refresh_token, account_hash, token_expires_at = get_user_trading_credentials(
                user_id, platform, db
            )
            
            # Build credentials dictionary
            credentials = {
                "access_token": access_token,
                "account_number": account_number,
                "refresh_token": refresh_token,
                "account_hash": account_hash,
                "token_expires_at": token_expires_at
            }
            
            # Create client
            return TradingClientFactory.create_client(platform, credentials)
            
        except ValueError as e:
            raise TradingError(
                str(e),
                ErrorCode.INVALID_CREDENTIALS,
                details={"user_id": user_id, "platform": platform}
            )
    
    @staticmethod
    def _create_tradier_client(
        platform: str,
        credentials: Dict[str, Any]
    ) -> Tuple[TradingPlatformInterface, str]:
        """Create a Tradier client."""
        access_token = credentials.get("access_token")
        account_number = credentials.get("account_number")
        
        if not access_token:
            raise TradingError(
                "Tradier access token is required",
                ErrorCode.INVALID_CREDENTIALS,
                details={"platform": platform, "missing": "access_token"}
            )
        
        if not account_number:
            raise TradingError(
                "Tradier account number is required",
                ErrorCode.INVALID_CREDENTIALS,
                details={"platform": platform, "missing": "account_number"}
            )
        
        base_url = PLATFORM_BASE_URLS[platform]
        client = TradierClient(access_token=access_token, base_url=base_url)
        
        logger.info(f"Created Tradier client for {platform}")
        return client, account_number
    
    @staticmethod
    def _create_schwab_client(
        credentials: Dict[str, Any]
    ) -> Tuple[TradingPlatformInterface, str]:
        """Create a Schwab client."""
        access_token = credentials.get("access_token")
        refresh_token = credentials.get("refresh_token")
        account_hash = credentials.get("account_hash")
        token_expires_at = credentials.get("token_expires_at")
        
        if not access_token:
            raise TradingError(
                "Schwab access token is required",
                ErrorCode.INVALID_CREDENTIALS,
                details={"platform": "schwab", "missing": "access_token"}
            )
        
        if not refresh_token:
            raise TradingError(
                "Schwab refresh token is required",
                ErrorCode.INVALID_CREDENTIALS,
                details={"platform": "schwab", "missing": "refresh_token"}
            )
        
        if not account_hash:
            raise TradingError(
                "Schwab account hash is required",
                ErrorCode.INVALID_CREDENTIALS,
                details={"platform": "schwab", "missing": "account_hash"}
            )
        
        client = SchwabClient(
            access_token=access_token,
            refresh_token=refresh_token,
            account_hash=account_hash,
            token_expires_at=token_expires_at
        )
        
        logger.info("Created Schwab client")
        return client, account_hash
    
    @staticmethod
    def get_supported_platforms() -> list:
        """Get list of supported trading platforms."""
        return ["tradier", "tradier_paper", "schwab"]
    
    @staticmethod
    def get_platform_display_name(platform: str) -> str:
        """Get user-friendly display name for platform."""
        display_names = {
            "tradier": "Tradier Production",
            "tradier_paper": "Tradier Paper Trading",
            "schwab": "Charles Schwab"
        }
        return display_names.get(platform, platform)
    
    @staticmethod
    def validate_platform_credentials(
        platform: str,
        credentials: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Validate platform credentials without creating a client.
        
        Args:
            platform: Trading platform
            credentials: Credentials to validate
            
        Returns:
            Dictionary with validation results
            
        Raises:
            TradingError: If validation fails
        """
        logger.info(f"Validating credentials for platform: {platform}")
        
        validate_platform(platform)
        
        if platform in ["tradier", "tradier_paper"]:
            required_fields = ["access_token", "account_number"]
        elif platform == "schwab":
            required_fields = ["access_token", "refresh_token", "account_hash"]
        else:
            raise TradingError(
                f"Unknown platform: {platform}",
                ErrorCode.TRADING_PLATFORM_ERROR
            )
        
        # Check for required fields
        missing_fields = [field for field in required_fields if not credentials.get(field)]
        if missing_fields:
            raise TradingError(
                f"Missing required fields for {platform}: {', '.join(missing_fields)}",
                ErrorCode.INVALID_CREDENTIALS,
                details={"platform": platform, "missing_fields": missing_fields}
            )
        
        # Platform-specific validation
        if platform in ["tradier", "tradier_paper"]:
            # Validate access token format (basic check)
            access_token = credentials["access_token"]
            if len(access_token) < 10:
                raise TradingError(
                    "Invalid access token format",
                    ErrorCode.INVALID_CREDENTIALS,
                    details={"platform": platform, "field": "access_token"}
                )
            
            # Validate account number format
            account_number = credentials["account_number"]
            if not account_number.replace("-", "").replace(" ", "").isdigit():
                raise TradingError(
                    "Invalid account number format",
                    ErrorCode.INVALID_CREDENTIALS,
                    details={"platform": platform, "field": "account_number"}
                )
        
        elif platform == "schwab":
            # Validate token formats (basic checks)
            access_token = credentials["access_token"]
            refresh_token = credentials["refresh_token"]
            
            if len(access_token) < 10:
                raise TradingError(
                    "Invalid access token format",
                    ErrorCode.INVALID_CREDENTIALS,
                    details={"platform": platform, "field": "access_token"}
                )
            
            if len(refresh_token) < 10:
                raise TradingError(
                    "Invalid refresh token format",
                    ErrorCode.INVALID_CREDENTIALS,
                    details={"platform": platform, "field": "refresh_token"}
                )
            
            # Validate account hash format
            account_hash = credentials["account_hash"]
            if len(account_hash) < 5:
                raise TradingError(
                    "Invalid account hash format",
                    ErrorCode.INVALID_CREDENTIALS,
                    details={"platform": platform, "field": "account_hash"}
                )
        
        logger.info(f"Credentials validation successful for {platform}")
        return {
            "valid": True,
            "platform": platform,
            "message": f"Credentials for {platform} are valid"
        }

# Convenience functions for backward compatibility
def create_trading_client(platform: str, credentials: Dict[str, Any]) -> Tuple[TradingPlatformInterface, str]:
    """Convenience function to create a trading client."""
    return TradingClientFactory.create_client(platform, credentials)

def create_trading_client_for_user(user_id: str, platform: str, db) -> Tuple[TradingPlatformInterface, str]:
    """Convenience function to create a trading client for a user."""
    return TradingClientFactory.create_client_for_user(user_id, platform, db)
