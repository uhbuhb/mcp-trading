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
from auth_utils import get_user_trading_credentials
from request_context import get_request_context

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("trading_server_oauth")

# Initialize FastMCP server
# Note: OAuth middleware is added at the FastAPI level in app.py
mcp = FastMCP("trading")

# Configure to mount at root of its path (so /mcp mount = /mcp endpoint, not /mcp/mcp)
mcp.settings.streamable_http_path = "/"

logger.info("MCP Trading Server initialized")

# Supported platforms
SUPPORTED_PLATFORMS = ["tradier"]

class TradingPlatformError(Exception):
    """Custom exception for trading platform errors."""
    pass

def get_user_context_from_ctx(ctx: Context) -> tuple[str, Session]:
    """
    Extract user context from FastMCP Context.
    
    The user_id and db session are stored in contextvars by the middleware,
    so we don't actually use the ctx parameter - but we keep it for consistency
    with the tool signatures.
    
    Args:
        ctx: FastMCP Context (not used, kept for signature compatibility)
    
    Returns:
        Tuple of (user_id, db_session)
    
    Raises:
        ValueError: If not authenticated
    """
    return get_request_context()

def get_trading_client_for_user(
    user_id: str,
    platform: str,
    environment: str,
    db: Session
) -> tuple[Any, str]:
    """
    Create trading client with user-specific credentials.
    
    Args:
        user_id: Authenticated user ID from OAuth token
        platform: Trading platform (e.g., 'tradier')
        environment: 'sandbox' or 'production'
        db: Database session
    
    Returns:
        Tuple of (client, account_number)
    """
    logger.info(f"Creating client for user {user_id}, platform {platform}, env {environment}")
    
    if platform not in SUPPORTED_PLATFORMS:
        raise TradingPlatformError(f"Unsupported platform: {platform}")
    
    # Fetch and decrypt credentials
    try:
        access_token, account_number = get_user_trading_credentials(
            user_id, platform, environment, db
        )
    except ValueError as e:
        raise TradingPlatformError(str(e))
    
    # Create client
    if platform == "tradier":
        use_sandbox = (environment == "sandbox")
        client = TradierClient(access_token=access_token, sandbox=use_sandbox)
        logger.info(f"Created Tradier client for user {user_id}")
        return client, account_number
    
    raise TradingPlatformError(f"Platform {platform} not implemented")

# ============================================================================
# MCP TOOLS WITH CONTEXT INJECTION
# ============================================================================

@mcp.tool()
async def get_positions(
    ctx: Context,
    account_id: Optional[str] = None,
    platform: str = "tradier",
    use_sandbox: bool = True
) -> str:
    """
    Get current trading positions from trading account.
    
    Args:
        ctx: FastMCP Context (automatically injected, contains user_id and db)
        account_id: Optional account ID override
        platform: Trading platform to use (default: 'tradier')
        use_sandbox: Whether to use sandbox environment (default: True)
    
    Returns:
        JSON string containing position information
    """
    # Extract authenticated user context from FastMCP Context
    user_id, db = get_user_context_from_ctx(ctx)
    
    environment = "sandbox" if use_sandbox else "production"
    logger.info(f"get_positions - user: {user_id}, platform: {platform}, env: {environment}")
    
    try:
        # Get user's trading client
        client, db_account_number = get_trading_client_for_user(user_id, platform, environment, db)
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
            "environment": environment,
            "positions": formatted_positions
        }, indent=2)
        
    except TradingPlatformError as e:
        return json.dumps({"status": "error", "message": str(e)}, indent=2)
    except Exception as e:
        logger.error(f"Failed to get positions: {e}", exc_info=True)
        return json.dumps({"status": "error", "message": str(e)}, indent=2)

@mcp.tool()
async def get_quote(
    ctx: Context,
    symbol: str,
    platform: str = "tradier",
    use_sandbox: bool = True
) -> str:
    """
    Get quote information for a stock symbol.
    
    Args:
        ctx: FastMCP Context (automatically injected)
        symbol: Stock symbol (e.g., 'AAPL', 'MSFT')
        platform: Trading platform to use (default: 'tradier')
        use_sandbox: Whether to use sandbox environment (default: True)
    
    Returns:
        JSON string containing quote information
    """
    user_id, db = get_user_context_from_ctx(ctx)
    environment = "sandbox" if use_sandbox else "production"
    
    logger.info(f"get_quote - symbol: {symbol}, user: {user_id}")
    
    try:
        client, _ = get_trading_client_for_user(user_id, platform, environment, db)
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

@mcp.tool()
async def place_multileg_order(
    ctx: Context,
    symbol: str,
    legs: str,
    account_id: Optional[str] = None,
    platform: str = "tradier",
    use_sandbox: bool = True,
    order_type: str = "market",
    duration: str = "day",
    preview: bool = False,
    price: Optional[float] = None
) -> str:
    """
    Place a multileg order (spread trade) or preview it.
    
    Args:
        ctx: FastMCP Context (automatically injected)
        symbol: Underlying symbol (e.g., 'AAPL')
        legs: JSON string containing array of leg objects
        account_id: Optional account ID override
        platform: Trading platform (default: 'tradier')
        use_sandbox: Use sandbox environment (default: True)
        order_type: Order type ('market', 'credit', 'debit', 'even')
        duration: Order duration ('day', 'gtc')
        preview: Preview without executing (default: False)
        price: Net price for limit orders
    
    Returns:
        JSON string containing order response
    """
    user_id, db = get_user_context_from_ctx(ctx)
    environment = "sandbox" if use_sandbox else "production"
    
    logger.info(f"place_multileg_order - user: {user_id}, symbol: {symbol}, preview: {preview}")
    
    try:
        # Validate
        if not symbol:
            raise TradingPlatformError("Symbol is required")
        
        # Parse legs
        legs_data = json.loads(legs)
        if not isinstance(legs_data, list) or len(legs_data) == 0:
            raise TradingPlatformError("Legs must be a non-empty array")
        
        # Get client
        client, db_account_number = get_trading_client_for_user(user_id, platform, environment, db)
        account_to_use = account_id or db_account_number
        
        # Place order
        response = client.place_multileg_order(
            account_id=account_to_use,
            symbol=symbol,
            legs=legs_data,
            order_type=order_type,
            duration=duration,
            preview=preview,
            price=price
        )
        
        return json.dumps({
            "status": "success",
            "message": f"Order {'previewed' if preview else 'placed'} successfully",
            "platform": platform,
            "environment": environment,
            "response": response
        }, indent=2)
        
    except Exception as e:
        logger.error(f"Failed to place order: {e}", exc_info=True)
        return json.dumps({"status": "error", "message": str(e)}, indent=2)

@mcp.tool()
async def get_balance(
    ctx: Context,
    account_id: Optional[str] = None,
    platform: str = "tradier",
    use_sandbox: bool = True
) -> str:
    """
    Get account balance information.
    
    Args:
        ctx: FastMCP Context (automatically injected)
        account_id: Optional account ID override
        platform: Trading platform (default: 'tradier')
        use_sandbox: Use sandbox environment (default: True)
    
    Returns:
        JSON string containing balance information
    """
    user_id, db = get_user_context_from_ctx(ctx)
    environment = "sandbox" if use_sandbox else "production"
    
    try:
        client, db_account_number = get_trading_client_for_user(user_id, platform, environment, db)
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

@mcp.tool()
async def view_orders(
    ctx: Context,
    account_id: Optional[str] = None,
    platform: str = "tradier",
    use_sandbox: bool = True,
    include_filled: bool = True
) -> str:
    """
    View orders from trading account.
    
    Args:
        ctx: FastMCP Context (automatically injected)
        account_id: Optional account ID override
        platform: Trading platform (default: 'tradier')
        use_sandbox: Use sandbox environment (default: True)
        include_filled: Include filled orders (default: True)
    
    Returns:
        JSON string containing order information
    """
    user_id, db = get_user_context_from_ctx(ctx)
    environment = "sandbox" if use_sandbox else "production"
    
    try:
        client, db_account_number = get_trading_client_for_user(user_id, platform, environment, db)
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

@mcp.tool()
async def cancel_order(
    ctx: Context,
    order_id: str,
    account_id: Optional[str] = None,
    platform: str = "tradier",
    use_sandbox: bool = True
) -> str:
    """
    Cancel an existing order.
    
    Args:
        ctx: FastMCP Context (automatically injected)
        order_id: Order ID to cancel
        account_id: Optional account ID override
        platform: Trading platform (default: 'tradier')
        use_sandbox: Use sandbox environment (default: True)
    
    Returns:
        JSON string containing cancellation response
    """
    user_id, db = get_user_context_from_ctx(ctx)
    environment = "sandbox" if use_sandbox else "production"
    
    try:
        if not order_id:
            raise TradingPlatformError("Order ID is required")
        
        client, db_account_number = get_trading_client_for_user(user_id, platform, environment, db)
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

@mcp.tool()
async def get_account_history(
    ctx: Context,
    account_id: Optional[str] = None,
    platform: str = "tradier",
    use_sandbox: bool = True,
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
        use_sandbox: Use sandbox environment (default: True)
        limit: Number of records to return
        start_date: Start date (YYYY-MM-DD format)
        end_date: End date (YYYY-MM-DD format)
    
    Returns:
        JSON string containing history information
    """
    user_id, db = get_user_context_from_ctx(ctx)
    environment = "sandbox" if use_sandbox else "production"
    
    try:
        client, db_account_number = get_trading_client_for_user(user_id, platform, environment, db)
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
    except:
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

# Export the FastMCP server instance
# This will be imported by app.py and mounted at /mcp
__all__ = ["mcp"]

