"""
OAuth-secured MCP Trading Server using FastMCP Context injection.

This is the production version that integrates:
- OAuth 2.1 token validation
- Per-user credential management
- FastMCP Context for user_id injection

All tools use FastMCP Context to access authenticated user information.
"""
import json
import logging
from typing import Optional, Any
from mcp.server.fastmcp import FastMCP, Context
from sqlalchemy.orm import Session

from tradier_client import TradierClient
from schwab_client import SchwabClient
from trading_platform_interface import TradingPlatformInterface
from auth_utils import get_user_trading_credentials
from request_context import get_user_id

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("trading_server_oauth")

# Initialize FastMCP server in STATELESS mode for Railway deployment
# Note: OAuth middleware is added at the FastAPI level in app.py
# Stateless mode prevents session management issues with multiple connections
mcp = FastMCP("trading", stateless_http=True)

# Configure to mount at root of its path (so /mcp mount = /mcp endpoint, not /mcp/mcp)
mcp.settings.streamable_http_path = "/"

logger.info("MCP Trading Server initialized")

# Supported platforms
SUPPORTED_PLATFORMS = ["tradier", "tradier_paper", "schwab"]

class TradingPlatformError(Exception):
    """Custom exception for trading platform errors."""
    pass

def get_user_context_from_ctx(ctx: Context) -> tuple[str, Session]:
    """
    Extract user context from FastMCP Context.

    The user_id is stored in contextvars by the middleware, but we create
    a fresh database session for each tool call to avoid session conflicts.

    Args:
        ctx: FastMCP Context (not used, kept for signature compatibility)

    Returns:
        Tuple of (user_id, db_session)

    Raises:
        ValueError: If not authenticated
    """
    # Get user_id from context (set by middleware)
    from request_context import get_user_id
    user_id = get_user_id()  # Raises ValueError if not authenticated

    # Create a fresh database session for this tool call
    from database import SessionLocal
    if SessionLocal is None:
        from database import init_session_local
        init_session_local()

    db = SessionLocal()
    return user_id, db


# Platform to base URL mapping
PLATFORM_BASE_URLS = {
    "tradier": "https://api.tradier.com",
    "tradier_paper": "https://sandbox.tradier.com",
    "schwab": None  # Schwab handles its own base URL
}

def get_trading_client_for_user(
    user_id: str,
    platform: str,
    db: Session
) -> tuple[TradingPlatformInterface, str]:
    """
    Create trading client with user-specific credentials.

    Args:
        user_id: Authenticated user ID from OAuth token
        platform: Trading platform (e.g., 'tradier', 'tradier_paper', 'schwab')
        db: Database session

    Returns:
        Tuple of (client, account_identifier)
        - For Tradier: account_identifier is account_number
        - For Schwab: account_identifier is account_hash
    """
    logger.info(f"Creating client for user {user_id}, platform {platform}")

    if platform not in SUPPORTED_PLATFORMS:
        raise TradingPlatformError(f"Unsupported platform: {platform}")

    # Fetch and decrypt credentials
    try:
        access_token, account_number, refresh_token, account_hash, token_expires_at = get_user_trading_credentials(
            user_id, platform, db
        )
    except ValueError as e:
        raise TradingPlatformError(str(e))

    # Create client based on platform
    if platform in ["tradier", "tradier_paper"]:
        base_url = PLATFORM_BASE_URLS[platform]
        client = TradierClient(access_token=access_token, base_url=base_url)
        logger.info(f"Created Tradier client for user {user_id} ({platform})")
        return client, account_number

    elif platform == "schwab":
        # Schwab requires refresh token and account hash
        if not refresh_token:
            raise TradingPlatformError("Schwab platform requires refresh token")
        if not account_hash:
            raise TradingPlatformError("Schwab platform requires account hash")

        client = SchwabClient(
            access_token=access_token,
            refresh_token=refresh_token,
            account_hash=account_hash,
            token_expires_at=token_expires_at
        )
        logger.info(f"Created Schwab client for user {user_id}")
        return client, account_hash

    raise TradingPlatformError(f"Platform {platform} not implemented")

# ============================================================================
# MCP TOOLS WITH CONTEXT INJECTION
# ============================================================================

@mcp.tool()
async def get_positions(
    ctx: Context,
    account_id: Optional[str] = None,
    platform: str = "tradier"
) -> str:
    """
    Get current trading positions from trading account.
    
    Args:
        ctx: FastMCP Context (automatically injected, contains user_id and db)
        account_id: Optional account ID override
        platform: Trading platform to use (default: 'tradier')
    
    Returns:
        JSON string containing position information
    """
    # Extract authenticated user context from FastMCP Context
    user_id, db = get_user_context_from_ctx(ctx)
    
    try:
        logger.info(f"get_positions - user: {user_id}, platform: {platform}")
        
        # Get user's trading client
        client, db_account_number = get_trading_client_for_user(user_id, platform, db)
        account_to_use = account_id or db_account_number
        
        # Fetch positions
        positions = client.get_positions(account_to_use)
        
        if not positions:
            return json.dumps({
                "status": "success",
                "message": "No positions found",
                "positions": []
            }, indent=2)
        
        # Format positions
        formatted_positions = [
            {
                "symbol": pos.get("symbol", "N/A"),
                "description": pos.get("description", "N/A"),
                "quantity": pos.get("quantity", "N/A"),
                "cost_basis": pos.get("cost_basis", "N/A"),
                "last_price": pos.get("last_price", "N/A"),
                "market_value": pos.get("market_value", "N/A"),
                "gain_loss": pos.get("gain_loss", "N/A"),
                "gain_loss_percent": pos.get("gain_loss_percent", "N/A")
            }
            for pos in positions
        ]
        
        return json.dumps({
            "status": "success",
            "message": f"Retrieved {len(formatted_positions)} positions",
            "platform": platform,
            "positions": formatted_positions
        }, indent=2)
        
    except TradingPlatformError as e:
        return json.dumps({"status": "error", "message": str(e)}, indent=2)
    except Exception as e:
        logger.error(f"Failed to get positions: {e}", exc_info=True)
        return json.dumps({"status": "error", "message": str(e)}, indent=2)
    finally:
        # Always close the database session
        db.close()

@mcp.tool()
async def get_quote(
    ctx: Context,
    symbol: str,
    platform: str = "tradier"
) -> str:
    """
    Get quote information for a stock symbol.
    
    Args:
        ctx: FastMCP Context (automatically injected)
        symbol: Stock symbol (e.g., 'AAPL', 'MSFT')
        platform: Trading platform to use (default: 'tradier')
    
    Returns:
        JSON string containing quote information
    """
    user_id, db = get_user_context_from_ctx(ctx)

    try:
        logger.info(f"get_quote - symbol: {symbol}, user: {user_id}")

        client, _ = get_trading_client_for_user(user_id, platform, db)
        quote = client.get_quote(symbol)

        return json.dumps({
            "status": "success",
            "message": f"Quote retrieved for {symbol}",
            "platform": platform,
            "quote": quote
        }, indent=2)

    except Exception as e:
        logger.error(f"Failed to get quote: {e}", exc_info=True)
        return json.dumps({"status": "error", "message": str(e)}, indent=2)
    finally:
        db.close()

@mcp.tool()
async def place_multileg_order(
    ctx: Context,
    symbol: str,
    legs: str,
    platform: str,
    order_type: str = "limit",
    price: Optional[str] = None,
    session: str = "normal",
    duration: str = "day",
    preview: bool = True,
    account_id: Optional[str] = None
    
) -> str:
    """
    Place a multileg option order or preview it. If preview value isnt specified, ask user if they want to preview
    the order or actually place it and set preview value accordingly. Same for the other parameters, if they arent 
    specified suggest a value and ask the user if they want something else.
    
    Args:
        ctx: FastMCP Context (automatically injected)
        symbol: Underlying symbol (e.g., 'AAPL')
        legs: JSON string containing array of leg objects with OCC format:
              [{"option_symbol": "V     251017C00340000", "side": "buy_to_open", "quantity": 1}]
              Option symbols in OCC format: [SYMBOL padded with spaces to 6 characters][YYMMDD][C/P][STRIKE padded to 8 digits]
              Example: "V251017C00340000" (V call, Oct 17 2025, $340 strike)
              Note: Option symbols are validated and converted automatically for each platform
        account_id: Optional account ID override
        platform: Trading platform (currently 'tradier', 'tradier_paper', and 'schwab' are supported)
        order_type: Order type ('market' or 'limit')
        duration: Order duration ('day', 'gtc')
        preview: Preview to check if the order would be accepted. This should always be done before placing the order.  (default: True)
        price: Net price for limit orders (as string):
               - Positive: Debit order (pay premium)
               - Negative: Credit order (receive  premium)
               - Cant be zero!!
               - Ignored for market orders
        session: Trading session ('normal', 'am', 'pm', 'seamless')
    
    Returns:
        JSON string containing order response
    """
    user_id, db = get_user_context_from_ctx(ctx)

    try:
        logger.info(f"=== MCP TOOL CALLED ===")
        logger.info(f"place_multileg_order - user: {user_id}, symbol: {symbol}, preview: {preview}")
        logger.info(f"price parameter: {price} (type: {type(price)})")
        logger.info(f"order_type: {order_type}, duration: {duration}")
        logger.info(f"platform: {platform}")
        logger.info(f"legs parameter: {legs} (type: {type(legs)})")

        # Validate
        if not symbol:
            raise TradingPlatformError("Symbol is required")

        # Parse legs
        legs_data = json.loads(legs)
        if not isinstance(legs_data, list) or len(legs_data) == 0:
            raise TradingPlatformError("Legs must be a non-empty array")

        # Get client
        client, db_account_number = get_trading_client_for_user(user_id, platform, db)
        account_to_use = account_id or db_account_number

        # Convert price from string to float if provided
        logger.info(f"=== PRICE CONVERSION ===")
        logger.info(f"Original price: {price} (type: {type(price)})")
        price_float = None
        if price is not None:
            try:
                price_float = float(price)
                logger.info(f"Converted price to float: {price_float} (type: {type(price_float)})")
            except (ValueError, TypeError) as e:
                logger.error(f"Price conversion failed: {e}")
                raise TradingPlatformError(f"Invalid price format: {price}. Must be a valid number.")
        else:
            logger.info("Price is None, keeping as None")

        # Place order
        logger.info(f"=== CALLING CLIENT ===")
        logger.info(f"Calling client.place_multileg_order with:")
        logger.info(f"  account_id: {account_to_use}")
        logger.info(f"  symbol: {symbol}")
        logger.info(f"  legs: {legs_data}")
        logger.info(f"  order_type: {order_type}")
        logger.info(f"  duration: {duration}")
        logger.info(f"  preview: {preview}")
        logger.info(f"  price: {price_float} (type: {type(price_float)})")
        
        response = client.place_multileg_order(
            account_id=account_to_use,
            symbol=symbol,
            legs=legs_data,
            order_type=order_type,
            duration=duration,
            session=session,
            preview=preview,
            price=price_float,
        )
        
        logger.info(f"=== CLIENT RESPONSE ===")
        logger.info(f"Response type: {type(response)}")
        logger.info(f"Response: {response}")

        return json.dumps({
            "status": "success",
            "message": f"Order {'previewed' if preview else 'placed'} successfully",
            "platform": platform,
            "response": response
        }, indent=2)

    except Exception as e:
        logger.error(f"=== EXCEPTION CAUGHT ===")
        logger.error(f"Exception type: {type(e)}")
        logger.error(f"Exception message: {str(e)}")
        logger.error(f"Full traceback:", exc_info=True)
        return json.dumps({"status": "error", "message": str(e)}, indent=2)
    finally:
        db.close()

@mcp.tool()
async def get_balance(
    ctx: Context,
    account_id: Optional[str] = None,
    platform: str = "tradier"
) -> str:
    """
    Get account balance information.
    
    Args:
        ctx: FastMCP Context (automatically injected)
        account_id: Optional account ID override
        platform: Trading platform (default: 'tradier')
    
    Returns:
        JSON string containing balance information
    """
    user_id, db = get_user_context_from_ctx(ctx)

    try:
        client, db_account_number = get_trading_client_for_user(user_id, platform, db)
        account_to_use = account_id or db_account_number

        balance = client.get_balance(account_to_use)

        return json.dumps({
            "status": "success",
            "message": "Balance retrieved successfully",
            "platform": platform,
            "balance": balance
        }, indent=2)

    except Exception as e:
        logger.error(f"Failed to get balance: {e}", exc_info=True)
        return json.dumps({"status": "error", "message": str(e)}, indent=2)
    finally:
        db.close()

@mcp.tool()
async def view_orders(
    ctx: Context,
    account_id: Optional[str] = None,
    platform: str = "tradier",
    include_filled: bool = True
) -> str:
    """
    View orders from trading account.
    
    Args:
        ctx: FastMCP Context (automatically injected)
        account_id: Optional account ID override
        platform: Trading platform (default: 'tradier')
        include_filled: Include filled orders (default: True)
    
    Returns:
        JSON string containing order information
    """
    user_id, db = get_user_context_from_ctx(ctx)

    try:
        client, db_account_number = get_trading_client_for_user(user_id, platform, db)
        account_to_use = account_id or db_account_number

        orders = client.get_orders(account_id=account_to_use, include_filled=include_filled)

        if not orders:
            return json.dumps({
                "status": "success",
                "message": "No orders found",
                "orders": []
            }, indent=2)

        return json.dumps({
            "status": "success",
            "message": f"Retrieved {len(orders)} orders",
            "platform": platform,
            "orders": orders
        }, indent=2)

    except Exception as e:
        logger.error(f"Failed to get orders: {e}", exc_info=True)
        return json.dumps({"status": "error", "message": str(e)}, indent=2)
    finally:
        db.close()

@mcp.tool()
async def cancel_order(
    ctx: Context,
    order_id: str,
    account_id: Optional[str] = None,
    platform: str = "tradier"
) -> str:
    """
    Cancel an existing order.
    
    Args:
        ctx: FastMCP Context (automatically injected)
        order_id: Order ID to cancel
        account_id: Optional account ID override
        platform: Trading platform (default: 'tradier')
    
    Returns:
        JSON string containing cancellation response
    """
    user_id, db = get_user_context_from_ctx(ctx)

    try:
        if not order_id:
            raise TradingPlatformError("Order ID is required")

        client, db_account_number = get_trading_client_for_user(user_id, platform, db)
        account_to_use = account_id or db_account_number

        response = client.cancel_order(account_id=account_to_use, order_id=order_id)

        return json.dumps({
            "status": "success",
            "message": f"Order {order_id} cancelled successfully",
            "platform": platform,
            "response": response
        }, indent=2)

    except Exception as e:
        logger.error(f"Failed to cancel order: {e}", exc_info=True)
        return json.dumps({"status": "error", "message": str(e)}, indent=2)
    finally:
        db.close()

@mcp.tool()
async def get_account_history(
    ctx: Context,
    account_id: Optional[str] = None,
    platform: str = "tradier",
    limit: Optional[int] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None
) -> str:
    """
    Get account transaction history.
    
    Args:
        ctx: FastMCP Context (automatically injected)
        account_id: Optional account ID override
        platform: Trading platform (default: 'tradier')
        limit: Number of records to return
        start_date: Start date (YYYY-MM-DD format)
        end_date: End date (YYYY-MM-DD format)
    
    Returns:
        JSON string containing history information
    """
    user_id, db = get_user_context_from_ctx(ctx)
    
    try:
        client, db_account_number = get_trading_client_for_user(user_id, platform, db)
        account_to_use = account_id or db_account_number
        
        history = client.get_account_history(
            account_id=account_to_use,
            limit=limit,
            start_date=start_date,
            end_date=end_date
        )
        
        return json.dumps({
            "status": "success",
            "message": f"Retrieved {history.get('total_events', 0)} events",
            "platform": platform,
            "history": history
        }, indent=2)
        
    except Exception as e:
        logger.error(f"Failed to get history: {e}", exc_info=True)
        return json.dumps({"status": "error", "message": str(e)}, indent=2)
    finally:
        db.close()

@mcp.tool()
async def get_account_status(ctx: Context, platform: str = "tradier") -> str:
    """
    Get the current account configuration status for the authenticated user.

    Args:
        ctx: FastMCP Context (automatically injected)
        platform: Trading platform (default: 'tradier')

    Returns:
        JSON string containing account status information
    """
    user_id, db = get_user_context_from_ctx(ctx)

    logger.info(f"get_account_status - user: {user_id}, platform: {platform}")

    try:
        # Try to get user's trading credentials
        try:
            _, account_number = get_user_trading_credentials(user_id, platform, db)
            credentials_configured = True
        except ValueError:
            credentials_configured = False
            account_number = None

        return json.dumps({
            "status": "success",
            "message": f"Account status retrieved for {platform}",
            "user_id": user_id,
            "platform": platform,
            "credentials_configured": credentials_configured,
            "account_number": account_number if credentials_configured else "NOT_SET"
        }, indent=2)

    except Exception as e:
        logger.error(f"Failed to get account status: {e}", exc_info=True)
        return json.dumps({
            "status": "error",
            "message": str(e)
        }, indent=2)
    finally:
        db.close()

@mcp.tool()
async def get_account_info(
    ctx: Context,
    account_id: Optional[str] = None,
    platform: str = "tradier"
) -> str:
    """
    Get account information from trading platform.

    Args:
        ctx: FastMCP Context (automatically injected)
        account_id: Optional account ID override
        platform: Trading platform (default: 'tradier')

    Returns:
        JSON string containing account information
    """
    user_id, db = get_user_context_from_ctx(ctx)

    logger.info(f"get_account_info - user: {user_id}, platform: {platform}")

    try:
        client, db_account_number = get_trading_client_for_user(user_id, platform, db)
        account_to_use = account_id or db_account_number

        account_info = client.get_account_info(account_to_use)

        return json.dumps({
            "status": "success",
            "message": f"Account information retrieved successfully from {platform}",
            "platform": platform,
            "account_info": account_info
        }, indent=2)

    except Exception as e:
        logger.error(f"Failed to get account info: {e}", exc_info=True)
        return json.dumps({
            "status": "error",
            "message": str(e),
            "platform": platform,
            "account_info": {}
        }, indent=2)
    finally:
        db.close()

@mcp.tool()
async def change_order(
    ctx: Context,
    order_id: str,
    platform: str,
    account_id: Optional[str] = None,
    order_type: Optional[str] = None,
    price: Optional[str] = None,
    stop: Optional[str] = None,
    duration: Optional[str] = None,
    quantity: Optional[str] = None
) -> str:
    """
    Change/modify an existing order.

    Args:
        ctx: FastMCP Context (automatically injected)
        order_id: Order ID to change
        platform: Trading platform (default: 'tradier')
        account_id: Optional account ID override
        order_type: New order type ('market', 'limit', 'stop', 'stop_limit')
        price: New limit price (required for limit orders)
        stop: New stop price (required for stop orders)
        duration: New order duration ('day', 'gtc', 'pre', 'post')
        quantity: New quantity

    Returns:
        JSON string containing change order response
    """
    user_id, db = get_user_context_from_ctx(ctx)

    logger.info(f"change_order - user: {user_id}, order_id: {order_id}")

    try:
        if not order_id:
            raise TradingPlatformError("Order ID is required to change an order")

        # Validate that at least one parameter is being changed
        if all(param is None for param in [order_type, price, stop, duration, quantity]):
            raise TradingPlatformError("At least one order parameter must be provided for modification")

        # Validate order type and price dependencies
        if order_type in ['limit', 'stop_limit'] and price is None:
            raise TradingPlatformError(f"Price is required for {order_type} orders")

        if order_type in ['stop', 'stop_limit'] and stop is None:
            raise TradingPlatformError(f"Stop price is required for {order_type} orders")

        client, db_account_number = get_trading_client_for_user(user_id, platform, db)
        account_to_use = account_id or db_account_number

        # Change the order
        response = client.change_order(
            account_id=account_to_use,
            order_id=order_id,
            order_type=order_type,
            price=float(price) if price is not None else None,
            stop=float(stop) if stop is not None else None,
            duration=duration,
            quantity=float(quantity) if quantity is not None else None
        )

        # Build changes summary
        changes = []
        if order_type is not None:
            changes.append(f"type to {order_type}")
        if price is not None:
            changes.append(f"price to ${price}")
        if stop is not None:
            changes.append(f"stop to ${stop}")
        if duration is not None:
            changes.append(f"duration to {duration}")
        if quantity is not None:
            changes.append(f"quantity to {quantity}")

        changes_summary = ", ".join(changes)

        return json.dumps({
            "status": "success",
            "message": f"Order {order_id} modification {'submitted' if response else 'completed'} on {platform}",
            "platform": platform,
            "account_id": account_to_use,
            "order_id": order_id,
            "changes": changes_summary,
            "response": response
        }, indent=2)

    except TradingPlatformError as e:
        return json.dumps({
            "status": "error",
            "message": f"Trading platform error: {str(e)}",
            "platform": platform,
            "order_id": order_id,
            "response": {}
        }, indent=2)
    except Exception as e:
        logger.error(f"Failed to change order: {e}", exc_info=True)
        return json.dumps({
            "status": "error",
            "message": f"Failed to change order {order_id} on {platform}: {str(e)}",
            "platform": platform,
            "order_id": order_id,
            "response": {}
        }, indent=2)
    finally:
        db.close()

@mcp.tool()
async def health_check(ctx: Context) -> str:
    """
    Check server health and authentication status.

    Args:
        ctx: FastMCP Context (automatically injected)

    Returns:
        JSON string with health and auth status
    """
    try:
        user_id, _ = get_user_context_from_ctx(ctx)

        return json.dumps({
            "status": "success",
            "message": "MCP Trading Server is running",
            "authenticated": True,
            "user_id": user_id
        }, indent=2)
    except Exception as e:
        logger.debug(f"Health check without authentication: {e}")
        return json.dumps({
            "status": "success",
            "message": "MCP Trading Server is running",
            "authenticated": False
        }, indent=2)

@mcp.tool()
async def list_platforms(ctx: Context) -> str:
    """
    List all supported trading platforms.
    
    Note: This tool doesn't require authentication for discovery.
    
    Returns:
        JSON string containing supported platforms
    """
    return json.dumps({
        "status": "success",
        "message": "Supported trading platforms",
        "platforms": SUPPORTED_PLATFORMS,
        "default_platform": "tradier"
    }, indent=2)

@mcp.tool()
async def revoke_current_token(ctx: Context) -> str:
    """
    Revoke the current session token.
    
    This will immediately invalidate the token used for this request,
    effectively logging out the current session.
    
    Args:
        ctx: FastMCP Context (automatically injected)
    
    Returns:
        JSON string containing revocation status
    """
    user_id, db = get_user_context_from_ctx(ctx)
    
    try:
        # Get the current token from the request context
        from request_context import get_current_token
        current_token = get_current_token()
        
        if not current_token:
            return json.dumps({
                "status": "error",
                "message": "Current token not found in request context"
            }, indent=2)
        
        # Hash the token to find it in the database
        import hashlib
        token_hash = hashlib.sha256(current_token.encode()).hexdigest()
        
        # Find and revoke the token
        from database import OAuthToken
        oauth_token = db.query(OAuthToken).filter(
            OAuthToken.token_hash == token_hash,
            OAuthToken.revoked == False
        ).first()
        
        if not oauth_token:
            return json.dumps({
                "status": "error",
                "message": "Current token not found in database"
            }, indent=2)
        
        # Mark as revoked
        oauth_token.revoked = True
        db.commit()
        
        logger.info(f"Current token revoked for user {user_id}")
        
        return json.dumps({
            "status": "success",
            "message": "Current session token revoked successfully",
            "user_id": user_id,
            "revoked_at": oauth_token.updated_at.isoformat() if oauth_token.updated_at else None
        }, indent=2)
        
    except Exception as e:
        logger.error(f"Failed to revoke current token: {e}", exc_info=True)
        return json.dumps({
            "status": "error",
            "message": f"Failed to revoke current token: {str(e)}"
        }, indent=2)
    finally:
        db.close()

@mcp.tool()
async def revoke_all_tokens(ctx: Context, platform: Optional[str] = None) -> str:
    """
    Revoke all active tokens for the authenticated user.
    
    Args:
        ctx: FastMCP Context (automatically injected)
        platform: Optional platform filter (e.g., 'tradier', 'schwab'). 
                  If not specified, revokes all tokens for all platforms.
    
    Returns:
        JSON string containing revocation status
    """
    user_id, db = get_user_context_from_ctx(ctx)
    
    try:
        from database import OAuthToken
        
        # Build query for active tokens
        query = db.query(OAuthToken).filter(
            OAuthToken.user_id == user_id,
            OAuthToken.revoked == False
        )
        
        # Add platform filter if specified
        if platform:
            query = query.filter(OAuthToken.client_id == platform)
        
        # Get all active tokens
        active_tokens = query.all()
        
        if not active_tokens:
            return json.dumps({
                "status": "success",
                "message": "No active tokens found to revoke",
                "user_id": user_id,
                "platform_filter": platform,
                "revoked_count": 0
            }, indent=2)
        
        # Revoke all tokens
        revoked_count = 0
        for token in active_tokens:
            token.revoked = True
            revoked_count += 1
        
        db.commit()
        
        logger.info(f"Revoked {revoked_count} tokens for user {user_id} (platform: {platform or 'all'})")
        
        return json.dumps({
            "status": "success",
            "message": f"Successfully revoked {revoked_count} active tokens",
            "user_id": user_id,
            "platform_filter": platform,
            "revoked_count": revoked_count
        }, indent=2)
        
    except Exception as e:
        logger.error(f"Failed to revoke all tokens: {e}", exc_info=True)
        return json.dumps({
            "status": "error",
            "message": f"Failed to revoke all tokens: {str(e)}"
        }, indent=2)
    finally:
        db.close()

@mcp.tool()
async def list_active_sessions(ctx: Context) -> str:
    """
    List all active sessions (non-revoked tokens) for the authenticated user.
    
    Args:
        ctx: FastMCP Context (automatically injected)
    
    Returns:
        JSON string containing active sessions information
    """
    user_id, db = get_user_context_from_ctx(ctx)
    
    try:
        from database import OAuthToken
        from datetime import datetime, timezone
        
        # Get all active tokens for the user
        active_tokens = db.query(OAuthToken).filter(
            OAuthToken.user_id == user_id,
            OAuthToken.revoked == False
        ).all()
        
        if not active_tokens:
            return json.dumps({
                "status": "success",
                "message": "No active sessions found",
                "user_id": user_id,
                "active_sessions": []
            }, indent=2)
        
        # Format session information
        sessions = []
        current_time = datetime.now(timezone.utc)
        
        for token in active_tokens:
            # Check if token is expired
            expires_at_utc = token.expires_at.replace(tzinfo=timezone.utc) if token.expires_at.tzinfo is None else token.expires_at
            is_expired = expires_at_utc < current_time
            
            session_info = {
                "client_id": token.client_id,
                "created_at": token.created_at.isoformat(),
                "expires_at": token.expires_at.isoformat() if token.expires_at else None,
                "is_expired": is_expired,
                "scope": token.scope,
                "token_id": token.id  # Internal ID for reference
            }
            sessions.append(session_info)
        
        # Separate active and expired sessions
        active_sessions = [s for s in sessions if not s["is_expired"]]
        expired_sessions = [s for s in sessions if s["is_expired"]]
        
        return json.dumps({
            "status": "success",
            "message": f"Found {len(active_sessions)} active sessions and {len(expired_sessions)} expired sessions",
            "user_id": user_id,
            "active_sessions": active_sessions,
            "expired_sessions": expired_sessions,
            "total_sessions": len(sessions)
        }, indent=2)
        
    except Exception as e:
        logger.error(f"Failed to list active sessions: {e}", exc_info=True)
        return json.dumps({
            "status": "error",
            "message": f"Failed to list active sessions: {str(e)}"
        }, indent=2)
    finally:
        db.close()

# Export the FastMCP server instance
# This will be imported by app.py and mounted at /mcp
__all__ = ["mcp"]

