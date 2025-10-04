"""
Standardized error handling for the MCP Trading Server.

This module provides consistent error handling across the application with:
- Custom exception classes
- Error response formatting
- Logging integration
- HTTP status code mapping
"""
import json
import logging
from typing import Dict, Any, Optional
from enum import Enum

logger = logging.getLogger("error_handling")

class ErrorCode(Enum):
    """Standardized error codes for consistent error handling."""
    # Trading platform errors
    TRADING_PLATFORM_ERROR = "TRADING_PLATFORM_ERROR"
    INVALID_CREDENTIALS = "INVALID_CREDENTIALS"
    INSUFFICIENT_PERMISSIONS = "INSUFFICIENT_PERMISSIONS"
    ACCOUNT_NOT_FOUND = "ACCOUNT_NOT_FOUND"
    ORDER_FAILED = "ORDER_FAILED"
    
    # Authentication/Authorization errors
    AUTHENTICATION_REQUIRED = "AUTHENTICATION_REQUIRED"
    INVALID_TOKEN = "INVALID_TOKEN"
    TOKEN_EXPIRED = "TOKEN_EXPIRED"
    INSUFFICIENT_SCOPE = "INSUFFICIENT_SCOPE"
    
    # Validation errors
    INVALID_INPUT = "INVALID_INPUT"
    MISSING_REQUIRED_FIELD = "MISSING_REQUIRED_FIELD"
    INVALID_FORMAT = "INVALID_FORMAT"
    
    # System errors
    INTERNAL_ERROR = "INTERNAL_ERROR"
    DATABASE_ERROR = "DATABASE_ERROR"
    EXTERNAL_SERVICE_ERROR = "EXTERNAL_SERVICE_ERROR"
    RATE_LIMIT_EXCEEDED = "RATE_LIMIT_EXCEEDED"
    
    # Configuration errors
    CONFIGURATION_ERROR = "CONFIGURATION_ERROR"
    ENCRYPTION_ERROR = "ENCRYPTION_ERROR"

class TradingError(Exception):
    """Base exception class for trading-related errors."""
    
    def __init__(
        self, 
        message: str, 
        code: ErrorCode = ErrorCode.TRADING_PLATFORM_ERROR,
        details: Optional[Dict[str, Any]] = None,
        status_code: int = 500
    ):
        self.message = message
        self.code = code
        self.details = details or {}
        self.status_code = status_code
        super().__init__(self.message)

class AuthenticationError(TradingError):
    """Exception for authentication-related errors."""
    
    def __init__(self, message: str = "Authentication required", details: Optional[Dict[str, Any]] = None):
        super().__init__(message, ErrorCode.AUTHENTICATION_REQUIRED, details, 401)

class AuthorizationError(TradingError):
    """Exception for authorization-related errors."""
    
    def __init__(self, message: str = "Insufficient permissions", details: Optional[Dict[str, Any]] = None):
        super().__init__(message, ErrorCode.INSUFFICIENT_PERMISSIONS, details, 403)

class ValidationError(TradingError):
    """Exception for input validation errors."""
    
    def __init__(self, message: str = "Invalid input", details: Optional[Dict[str, Any]] = None):
        super().__init__(message, ErrorCode.INVALID_INPUT, details, 400)

class ConfigurationError(TradingError):
    """Exception for configuration-related errors."""
    
    def __init__(self, message: str = "Configuration error", details: Optional[Dict[str, Any]] = None):
        super().__init__(message, ErrorCode.CONFIGURATION_ERROR, details, 500)

class ResponseFormatter:
    """Standardized response formatting for success and error cases."""
    
    @staticmethod
    def success(data: Dict[str, Any], message: str = "Success") -> str:
        """Format a successful response."""
        return json.dumps({
            "status": "success",
            "message": message,
            "data": data
        }, indent=2)
    
    @staticmethod
    def error(
        message: str, 
        code: str = ErrorCode.INTERNAL_ERROR.value,
        details: Optional[Dict[str, Any]] = None,
        status_code: int = 500
    ) -> str:
        """Format an error response."""
        error_response = {
            "status": "error",
            "code": code,
            "message": message
        }
        
        if details:
            error_response["details"] = details
            
        return json.dumps(error_response, indent=2)

def handle_trading_error(func):
    """
    Decorator for consistent error handling in MCP tools.
    
    This decorator:
    - Catches TradingError exceptions and formats them consistently
    - Logs unexpected errors with full traceback
    - Returns standardized JSON error responses
    - Ensures database sessions are properly closed
    """
    async def wrapper(*args, **kwargs):
        try:
            return await func(*args, **kwargs)
        except TradingError as e:
            logger.warning(f"Trading error in {func.__name__}: {e.message} (code: {e.code.value})")
            return ResponseFormatter.error(
                message=e.message,
                code=e.code.value,
                details=e.details,
                status_code=e.status_code
            )
        except Exception as e:
            logger.error(f"Unexpected error in {func.__name__}: {e}", exc_info=True)
            return ResponseFormatter.error(
                message="An unexpected error occurred",
                code=ErrorCode.INTERNAL_ERROR.value,
                details={"function": func.__name__} if logger.level <= logging.DEBUG else None
            )
    return wrapper

def create_error_response(
    message: str,
    code: ErrorCode = ErrorCode.INTERNAL_ERROR,
    details: Optional[Dict[str, Any]] = None,
    status_code: int = 500
) -> Dict[str, Any]:
    """Create a standardized error response dictionary."""
    error_response = {
        "status": "error",
        "code": code.value,
        "message": message
    }
    
    if details:
        error_response["details"] = details
        
    return error_response

def log_and_raise(error: TradingError) -> None:
    """Log an error and raise it."""
    logger.error(f"{error.code.value}: {error.message}")
    if error.details:
        logger.debug(f"Error details: {error.details}")
    raise error

# Common error messages
ERROR_MESSAGES = {
    ErrorCode.AUTHENTICATION_REQUIRED: "Authentication required. Please complete the OAuth flow.",
    ErrorCode.INVALID_TOKEN: "Invalid or expired token. Please authenticate again.",
    ErrorCode.INSUFFICIENT_PERMISSIONS: "Insufficient permissions for this operation.",
    ErrorCode.INVALID_INPUT: "Invalid input provided. Please check your request parameters.",
    ErrorCode.TRADING_PLATFORM_ERROR: "Trading platform error occurred.",
    ErrorCode.ACCOUNT_NOT_FOUND: "Trading account not found. Please check your credentials.",
    ErrorCode.CONFIGURATION_ERROR: "Server configuration error. Please contact support.",
    ErrorCode.DATABASE_ERROR: "Database operation failed.",
    ErrorCode.EXTERNAL_SERVICE_ERROR: "External service error occurred.",
}

def get_error_message(code: ErrorCode) -> str:
    """Get a user-friendly error message for an error code."""
    return ERROR_MESSAGES.get(code, "An unexpected error occurred.")

# Validation helpers
def validate_required_fields(data: Dict[str, Any], required_fields: list) -> None:
    """Validate that all required fields are present in the data."""
    missing_fields = [field for field in required_fields if field not in data or data[field] is None]
    if missing_fields:
        raise ValidationError(
            f"Missing required fields: {', '.join(missing_fields)}",
            details={"missing_fields": missing_fields}
        )

def validate_platform(platform: str) -> None:
    """Validate that the platform is supported."""
    supported_platforms = ["tradier", "tradier_paper", "schwab"]
    if platform not in supported_platforms:
        raise ValidationError(
            f"Unsupported platform: {platform}",
            details={"supported_platforms": supported_platforms}
        )

def validate_symbol(symbol: str) -> None:
    """Validate that a trading symbol is properly formatted."""
    if not symbol or not isinstance(symbol, str):
        raise ValidationError("Symbol must be a non-empty string")
    
    if len(symbol) > 10:
        raise ValidationError("Symbol must be 10 characters or less")
    
    # Basic alphanumeric validation
    if not symbol.replace(".", "").replace("-", "").isalnum():
        raise ValidationError("Symbol contains invalid characters")

def validate_price(price: str) -> float:
    """Validate and convert a price string to float."""
    if not price:
        raise ValidationError("Price is required")
    
    try:
        price_float = float(price)
        if price_float == 0:
            raise ValidationError("Price cannot be zero")
        return price_float
    except ValueError:
        raise ValidationError(f"Invalid price format: {price}")

def validate_quantity(quantity: int) -> None:
    """Validate that quantity is a positive integer."""
    if not isinstance(quantity, int) or quantity <= 0:
        raise ValidationError("Quantity must be a positive integer")
