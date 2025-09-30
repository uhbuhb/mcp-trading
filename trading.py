import os
import json
import logging
import sys
from typing import Any, Dict, List, Optional, Union
from mcp.server.fastmcp import FastMCP
from mcp.types import Tool, TextContent
from tradier_client import TradierClient
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Configure logging
def setup_logging():
    """Set up comprehensive logging for the MCP server."""
    # Create logs directory if it doesn't exist
    os.makedirs("logs", exist_ok=True)
    
    # Configure root logger
    logging.basicConfig(
        level=logging.DEBUG,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[
            logging.FileHandler('logs/trading_server.log'),
            logging.StreamHandler(sys.stdout)
        ]
    )
    
    # Create specific loggers
    server_logger = logging.getLogger('trading_server')
    client_logger = logging.getLogger('trading_client')
    mcp_logger = logging.getLogger('mcp')
    
    # Set levels for different components
    server_logger.setLevel(logging.DEBUG)
    client_logger.setLevel(logging.DEBUG)
    mcp_logger.setLevel(logging.INFO)
    
    return server_logger, client_logger, mcp_logger

# Initialize logging
server_logger, client_logger, mcp_logger = setup_logging()

# Initialize FastMCP server
mcp = FastMCP("trading")
server_logger.info("MCP Trading Server initialized")

# Global client instances for different platforms
clients: Dict[str, Any] = {}

# Supported platforms
SUPPORTED_PLATFORMS = ["tradier"]

class TradingPlatformError(Exception):
    """Custom exception for trading platform errors."""
    pass

def get_user_credentials(platform: str = "tradier", use_sandbox: bool = True) -> tuple[Optional[str], Optional[str]]:
    """
    Get user credentials from environment variables.
    
    Args:
        platform: Trading platform name
        use_sandbox: Whether to use sandbox environment
    
    Returns:
        Tuple of (access_token, account_number) or (None, None) if not found
    """
    server_logger.debug(f"Getting credentials for {platform} from environment variables")
    
    if platform == "tradier":
        if use_sandbox:
            access_token = os.getenv("TRADIER_SANDBOX_ACCESS_TOKEN")
            account_number = os.getenv("TRADIER_SANDBOX_ACCOUNT_NUMBER")
        else:
            access_token = os.getenv("TRADIER_ACCESS_TOKEN")
            account_number = os.getenv("TRADIER_PRODUCTION_ACCOUNT_NUMBER")
        return access_token, account_number
    
    return None, None

def get_trading_client(platform: str = "tradier", use_sandbox: bool = True, 
                      access_token: Optional[str] = None, account_number: Optional[str] = None) -> Any:
    """
    Get or create a trading client instance for the specified platform.
    
    Args:
        platform: Trading platform name (e.g., 'tradier')
        use_sandbox: Whether to use sandbox environment (default: True)
        access_token: Optional access token (if not provided, uses environment)
        account_number: Optional account number (not currently used)
    
    Returns:
        Trading client instance
    
    Raises:
        TradingPlatformError: If platform is not supported or configuration is invalid
    """
    global clients
    
    server_logger.debug(f"Getting trading client for platform: {platform}, sandbox: {use_sandbox}")
    
    if platform not in SUPPORTED_PLATFORMS:
        error_msg = f"Unsupported platform: {platform}. Supported platforms: {SUPPORTED_PLATFORMS}"
        server_logger.error(error_msg)
        raise TradingPlatformError(error_msg)
    
    # Get credentials from parameters or environment
    if access_token is None:
        access_token, _ = get_user_credentials(platform, use_sandbox)
    
    if access_token is None:
        error_msg = f"No access token found for {platform} ({'sandbox' if use_sandbox else 'production'}). Please set the appropriate environment variable."
        server_logger.error(error_msg)
        raise TradingPlatformError(error_msg)
    
    # Create a unique key for this platform and sandbox combination
    client_key = f"{platform}_{'sandbox' if use_sandbox else 'production'}"
    
    # Return existing client if available
    if client_key in clients:
        server_logger.debug(f"Returning cached client for key: {client_key}")
        return clients[client_key]
    
    server_logger.info(f"Creating new client for platform: {platform}, sandbox: {use_sandbox}")
    
    # Create new client based on platform
    if platform == "tradier":
        client = _create_tradier_client(use_sandbox, access_token)
    else:
        error_msg = f"Platform {platform} not implemented yet"
        server_logger.error(error_msg)
        raise TradingPlatformError(error_msg)
    
    # Cache the client
    clients[client_key] = client
    server_logger.info(f"Successfully created and cached client for key: {client_key}")
    return client

def _create_tradier_client(use_sandbox: bool = True, access_token: Optional[str] = None) -> TradierClient:
    """Create a Tradier client instance."""
    server_logger.debug(f"Creating Tradier client, sandbox: {use_sandbox}")
    
    # Use provided token or fall back to environment variables
    if access_token is None:
        if use_sandbox:
            access_token = os.getenv("TRADIER_SANDBOX_ACCESS_TOKEN")
            if not access_token:
                error_msg = "TRADIER_SANDBOX_ACCESS_TOKEN environment variable is required for sandbox mode"
                server_logger.error(error_msg)
                raise TradingPlatformError(error_msg)
            server_logger.debug("Using sandbox access token from environment")
        else:
            access_token = os.getenv("TRADIER_ACCESS_TOKEN")
            if not access_token:
                error_msg = "TRADIER_ACCESS_TOKEN environment variable is required for production mode"
                server_logger.error(error_msg)
                raise TradingPlatformError(error_msg)
            server_logger.debug("Using production access token from environment")
    else:
        server_logger.debug(f"Using provided access token for {'sandbox' if use_sandbox else 'production'}")
    
    try:
        client = TradierClient(access_token=access_token, sandbox=use_sandbox)
        server_logger.info(f"Successfully created Tradier client (sandbox: {use_sandbox})")
        return client
    except Exception as e:
        error_msg = f"Failed to create Tradier client: {str(e)}"
        server_logger.error(error_msg)
        raise TradingPlatformError(error_msg)

def _get_account_id(platform: str = "tradier", use_sandbox: bool = True, account_number: Optional[str] = None) -> Optional[str]:
    """Get the account ID from parameters or environment variables."""
    # Use provided account number if available
    if account_number is not None:
        return account_number
    
    # Get from environment variables
    if platform == "tradier":
        if use_sandbox:
            return os.getenv("TRADIER_SANDBOX_ACCOUNT_NUMBER")
        else:
            return os.getenv("TRADIER_PRODUCTION_ACCOUNT_NUMBER")
    else:
        # For future platforms, add their account ID environment variables here
        return None

@mcp.tool()
def get_account_status() -> str:
    """
    Get the current account configuration status from environment variables.
    
    Returns:
        JSON string containing account status information
    """
    server_logger.info("Getting account status")
    
    try:
        status = {
            "status": "success",
            "message": "Account status retrieved from environment variables",
            "environment_variables": {
                "TRADIER_SANDBOX_ACCESS_TOKEN": "SET" if os.getenv("TRADIER_SANDBOX_ACCESS_TOKEN") else "NOT_SET",
                "TRADIER_ACCESS_TOKEN": "SET" if os.getenv("TRADIER_ACCESS_TOKEN") else "NOT_SET",
                "TRADIER_SANDBOX_ACCOUNT_NUMBER": "SET" if os.getenv("TRADIER_SANDBOX_ACCOUNT_NUMBER") else "NOT_SET",
                "TRADIER_PRODUCTION_ACCOUNT_NUMBER": "SET" if os.getenv("TRADIER_PRODUCTION_ACCOUNT_NUMBER") else "NOT_SET"
            }
        }
        
        return json.dumps(status, indent=2)
        
    except Exception as e:
        return json.dumps({
            "status": "error",
            "message": f"Failed to get account status: {str(e)}"
        }, indent=2)

@mcp.tool()
def get_positions(account_id: Optional[str] = None, platform: str = "tradier", use_sandbox: bool = True) -> str:
    """
    Get current trading positions from trading account.
    
    Args:
        account_id: Optional specific account ID. If not provided, uses account ID from session or environment variables.
        platform: Trading platform to use (default: 'tradier')
        use_sandbox: Whether to use sandbox environment (default: True)
    
    Returns:
        JSON string containing position information
    """
    server_logger.info(f"Getting positions - platform: {platform}, sandbox: {use_sandbox}, account_id: {account_id or 'auto'}")
    
    try:
        # Use provided account ID or get from session/environment
        if account_id is None:
            account_id = _get_account_id(platform=platform, use_sandbox=use_sandbox)
            server_logger.debug(f"Using account ID from session/environment: {account_id}")
        
        client = get_trading_client(platform=platform, use_sandbox=use_sandbox)
        server_logger.debug(f"Retrieving positions from {platform} for account {account_id}")
        positions = client.get_positions(account_id)
        
        # Format the response
        if not positions:
            return json.dumps({
                "status": "success",
                "message": "No positions found",
                "positions": []
            }, indent=2)
        
        # Format positions for better readability
        formatted_positions = []
        for position in positions:
            formatted_position = {
                "symbol": position.get("symbol", "N/A"),
                "description": position.get("description", "N/A"),
                "quantity": position.get("quantity", "N/A"),
                "cost_basis": position.get("cost_basis", "N/A"),
                "date_acquired": position.get("date_acquired", "N/A"),
                "last_price": position.get("last_price", "N/A"),
                "market_value": position.get("market_value", "N/A"),
                "gain_loss": position.get("gain_loss", "N/A"),
                "gain_loss_percent": position.get("gain_loss_percent", "N/A"),
                "type": position.get("type", "N/A")
            }
            formatted_positions.append(formatted_position)
        
        return json.dumps({
            "status": "success",
            "message": f"Retrieved {len(formatted_positions)} positions from {platform}",
            "platform": platform,
            "positions": formatted_positions
        }, indent=2)
        
    except Exception as e:
        return json.dumps({
            "status": "error",
            "message": f"Failed to get positions from {platform}: {str(e)}",
            "platform": platform,
            "positions": []
        }, indent=2)

@mcp.tool()
def get_account_info(platform: str = "tradier", use_sandbox: bool = True) -> str:
    """
    Get account information from trading platform.
    
    Args:
        platform: Trading platform to use (default: 'tradier')
        use_sandbox: Whether to use sandbox environment (default: True)
    
    Returns:
        JSON string containing account information
    """
    try:
        client = get_trading_client(platform=platform, use_sandbox=use_sandbox)
        account_info = client.get_account_info()
        
        return json.dumps({
            "status": "success",
            "message": f"Account information retrieved successfully from {platform}",
            "platform": platform,
            "account_info": account_info
        }, indent=2)
        
    except Exception as e:
        return json.dumps({
            "status": "error",
            "message": f"Failed to get account info from {platform}: {str(e)}",
            "platform": platform,
            "account_info": {}
        }, indent=2)

@mcp.tool()
def get_balance(account_id: Optional[str] = None, platform: str = "tradier", use_sandbox: bool = True) -> str:
    """
    Get account balance information from trading platform.
    
    Args:
        account_id: Optional specific account ID. If not provided, uses account ID from environment variables.
        platform: Trading platform to use (default: 'tradier')
        use_sandbox: Whether to use sandbox environment (default: True)
    
    Returns:
        JSON string containing balance information
    """
    try:
        # Use environment account ID if none provided
        if account_id is None:
            account_id = _get_account_id(platform=platform, use_sandbox=use_sandbox)
        
        client = get_trading_client(platform=platform, use_sandbox=use_sandbox)
        balance = client.get_balance(account_id)
        
        return json.dumps({
            "status": "success",
            "message": f"Balance information retrieved successfully from {platform}",
            "platform": platform,
            "balance": balance
        }, indent=2)
        
    except Exception as e:
        return json.dumps({
            "status": "error",
            "message": f"Failed to get balance from {platform}: {str(e)}",
            "platform": platform,
            "balance": {}
        }, indent=2)

@mcp.tool()
def get_quote(symbol: str, platform: str = "tradier", use_sandbox: bool = True) -> str:
    """
    Get quote information for a stock symbol.
    
    Args:
        symbol: Stock symbol (e.g., 'AAPL', 'MSFT')
        platform: Trading platform to use (default: 'tradier')
        use_sandbox: Whether to use sandbox environment (default: True)
    
    Returns:
        JSON string containing quote information
    """
    try:
        client = get_trading_client(platform=platform, use_sandbox=use_sandbox)
        quote = client.get_quote(symbol)
        
        return json.dumps({
            "status": "success",
            "message": f"Quote retrieved for {symbol} from {platform}",
            "platform": platform,
            "quote": quote
        }, indent=2)
        
    except Exception as e:
        return json.dumps({
            "status": "error",
            "message": f"Failed to get quote for {symbol} from {platform}: {str(e)}",
            "platform": platform,
            "quote": {}
        }, indent=2)

@mcp.tool()
def place_multileg_order(account_id: Optional[str] = None, platform: str = "tradier", 
                        use_sandbox: bool = True, symbol: str = "", legs: str = "",
                        order_type: str = "market", duration: str = "day", 
                        preview: bool = False, price: Optional[float] = None) -> str:
    """
    Place a multileg order (spread trade) or preview it.
    
    Args:
        account_id: Optional specific account ID. If not provided, uses account ID from environment variables.
        platform: Trading platform to use (default: 'tradier')
        use_sandbox: Whether to use sandbox environment (default: True)
        symbol: Underlying symbol (e.g., 'AAPL')
        legs: JSON string containing array of leg objects. Each leg should have:
              - side: 'buy_to_open', 'sell_to_open', 'buy_to_close', or 'sell_to_close'
              - quantity: Number of contracts
              - option_symbol: OCC option symbol
        order_type: Order type ('market', 'credit', 'debit', 'even'')
        duration: Order duration ('day', 'gtc', etc.)
        preview: If True, preview the order without executing
        price: Net price for limit (debit, credit) orders (required for debit or credit order_type)
              - Positive price = debit spread (paying premium)
              - Negative price = credit spread (receiving premium)
    
    Returns:
        JSON string containing order response or preview information
    """
    try:
        # Use environment account ID if none provided
        if account_id is None:
            account_id = _get_account_id(platform=platform, use_sandbox=use_sandbox)
        
        if not account_id:
            raise TradingPlatformError(f"No account ID provided for {platform}")
        
        if not symbol:
            raise TradingPlatformError("Symbol is required for multileg orders")
        
        if not legs:
            raise TradingPlatformError("Legs are required for multileg orders")
        
        # Validate price parameter for limit orders
        if order_type in ['debit', 'credit'] and price is None:
            raise TradingPlatformError("Price is required for limit orders")
        
        # Parse legs JSON
        try:
            legs_data = json.loads(legs)
            if not isinstance(legs_data, list) or len(legs_data) == 0:
                raise ValueError("Legs must be a non-empty array")
        except json.JSONDecodeError as e:
            raise TradingPlatformError(f"Invalid JSON format for legs: {str(e)}")
        
        # Validate each leg
        for i, leg in enumerate(legs_data):
            if not isinstance(leg, dict):
                raise TradingPlatformError(f"Leg {i} must be an object")
            
            required_fields = ['side', 'quantity', 'option_symbol']
            for field in required_fields:
                if field not in leg:
                    raise TradingPlatformError(f"Leg {i} missing required field: {field}")
            
            if leg['side'] not in ['buy_to_open', 'sell_to_open', 'buy_to_close', 'sell_to_close']:
                raise TradingPlatformError(f"Leg {i} has invalid side: {leg['side']}")
            
            try:
                leg['quantity'] = float(leg['quantity'])
                if leg['quantity'] <= 0:
                    raise ValueError("Quantity must be positive")
            except (ValueError, TypeError):
                raise TradingPlatformError(f"Leg {i} has invalid quantity: {leg['quantity']}")
        
        client = get_trading_client(platform=platform, use_sandbox=use_sandbox)
        
        # Place the multileg order
        response = client.place_multileg_order(
            account_id=account_id,
            symbol=symbol,
            legs=legs_data,
            order_type=order_type,
            duration=duration,
            preview=preview,
            price=price
        )
        
        # Format the response
        return json.dumps({
            "status": "success",
            "message": f"Multileg order {'previewed' if preview else 'placed'} successfully on {platform}",
            "platform": platform,
            "account_id": account_id,
            "symbol": symbol,
            "order_type": order_type,
            "duration": duration,
            "preview": preview,
            "price": price,
            "legs": legs_data,
            "response": response
        }, indent=2)
        
    except TradingPlatformError as e:
        return json.dumps({
            "status": "error",
            "message": f"Trading platform error: {str(e)}",
            "platform": platform,
            "account_id": account_id,
            "symbol": symbol,
            "order_type": order_type,
            "price": price,
            "legs": legs,
            "response": {}
        }, indent=2)
    except Exception as e:
        return json.dumps({
            "status": "error",
            "message": f"Failed to place multileg order on {platform}: {str(e)}",
            "platform": platform,
            "account_id": account_id,
            "symbol": symbol,
            "order_type": order_type,
            "price": price,
            "legs": legs,
            "response": {}
        }, indent=2)

@mcp.tool()
def view_orders(account_id: Optional[str] = None, platform: str = "tradier", 
                use_sandbox: bool = True, include_filled: bool = True) -> str:
    """
    View orders from trading account.
    
    Args:
        account_id: Optional specific account ID. If not provided, uses account ID from environment variables.
        platform: Trading platform to use (default: 'tradier')
        use_sandbox: Whether to use sandbox environment (default: True)
        include_filled: Whether to include filled orders (default: True)
    
    Returns:
        JSON string containing order information
    """
    try:
        # Use environment account ID if none provided
        if account_id is None:
            account_id = _get_account_id(platform=platform, use_sandbox=use_sandbox)
        
        client = get_trading_client(platform=platform, use_sandbox=use_sandbox)
        orders = client.get_orders(account_id=account_id, include_filled=include_filled)
        
        # Format the response
        if not orders:
            return json.dumps({
                "status": "success",
                "message": "No orders found",
                "orders": []
            }, indent=2)
        
        # Format orders for better readability
        formatted_orders = []
        for order in orders:
            formatted_order = {
                "id": order.get("id", "N/A"),
                "symbol": order.get("symbol", "N/A"),
                "description": order.get("description", "N/A"),
                "side": order.get("side", "N/A"),
                "quantity": order.get("quantity", "N/A"),
                "type": order.get("type", "N/A"),
                "duration": order.get("duration", "N/A"),
                "price": order.get("price", "N/A"),
                "status": order.get("status", "N/A"),
                "create_date": order.get("create_date", "N/A"),
                "transaction_date": order.get("transaction_date", "N/A"),
                "class": order.get("class", "N/A"),
                "option_symbol": order.get("option_symbol", "N/A"),
                "legs": order.get("legs", "N/A")
            }
            formatted_orders.append(formatted_order)
        
        return json.dumps({
            "status": "success",
            "message": f"Retrieved {len(formatted_orders)} orders from {platform}",
            "platform": platform,
            "account_id": account_id,
            "include_filled": include_filled,
            "orders": formatted_orders
        }, indent=2)
        
    except Exception as e:
        return json.dumps({
            "status": "error",
            "message": f"Failed to get orders from {platform}: {str(e)}",
            "platform": platform,
            "account_id": account_id,
            "orders": []
        }, indent=2)

@mcp.tool()
def cancel_order(order_id: str, account_id: Optional[str] = None, platform: str = "tradier", 
                use_sandbox: bool = True) -> str:
    """
    Cancel an existing order.
    
    Args:
        order_id: Order ID to cancel
        account_id: Optional specific account ID. If not provided, uses account ID from environment variables.
        platform: Trading platform to use (default: 'tradier')
        use_sandbox: Whether to use sandbox environment (default: True)
    
    Returns:
        JSON string containing cancellation response
    """
    try:
        # Use environment account ID if none provided
        if account_id is None:
            account_id = _get_account_id(platform=platform, use_sandbox=use_sandbox)
        
        if not account_id:
            raise TradingPlatformError(f"No account ID provided for {platform}")
        
        if not order_id:
            raise TradingPlatformError("Order ID is required to cancel an order")
        
        client = get_trading_client(platform=platform, use_sandbox=use_sandbox)
        
        # Cancel the order
        response = client.cancel_order(account_id=account_id, order_id=order_id)
        
        return json.dumps({
            "status": "success",
            "message": f"Order {order_id} cancellation {'submitted' if response else 'completed'} on {platform}",
            "platform": platform,
            "account_id": account_id,
            "order_id": order_id,
            "response": response
        }, indent=2)
        
    except TradingPlatformError as e:
        return json.dumps({
            "status": "error",
            "message": f"Trading platform error: {str(e)}",
            "platform": platform,
            "account_id": account_id,
            "order_id": order_id,
            "response": {}
        }, indent=2)
    except Exception as e:
        return json.dumps({
            "status": "error",
            "message": f"Failed to cancel order {order_id} on {platform}: {str(e)}",
            "platform": platform,
            "account_id": account_id,
            "order_id": order_id,
            "response": {}
        }, indent=2)

@mcp.tool()
def change_order(order_id: str, account_id: Optional[str] = None, platform: str = "tradier", 
                use_sandbox: bool = True, order_type: Optional[str] = None, 
                price: Optional[float] = None, stop: Optional[float] = None,
                duration: Optional[str] = None, quantity: Optional[float] = None) -> str:
    """
    Change/modify an existing order.
    
    Args:
        order_id: Order ID to change
        account_id: Optional specific account ID. If not provided, uses account ID from environment variables.
        platform: Trading platform to use (default: 'tradier')
        use_sandbox: Whether to use sandbox environment (default: True)
        order_type: New order type ('market', 'limit', 'stop', 'stop_limit')
        price: New limit price (required for limit orders)
        stop: New stop price (required for stop orders)
        duration: New order duration ('day', 'gtc', 'pre', 'post')
        quantity: New quantity
    
    Returns:
        JSON string containing change order response
    """
    try:
        # Use environment account ID if none provided
        if account_id is None:
            account_id = _get_account_id(platform=platform, use_sandbox=use_sandbox)
        
        if not account_id:
            raise TradingPlatformError(f"No account ID provided for {platform}")
        
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
        
        client = get_trading_client(platform=platform, use_sandbox=use_sandbox)
        
        # Change the order
        response = client.change_order(
            account_id=account_id,
            order_id=order_id,
            order_type=order_type,
            price=price,
            stop=stop,
            duration=duration,
            quantity=quantity
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
            "account_id": account_id,
            "order_id": order_id,
            "changes": changes_summary,
            "response": response
        }, indent=2)
        
    except TradingPlatformError as e:
        return json.dumps({
            "status": "error",
            "message": f"Trading platform error: {str(e)}",
            "platform": platform,
            "account_id": account_id,
            "order_id": order_id,
            "response": {}
        }, indent=2)
    except Exception as e:
        return json.dumps({
            "status": "error",
            "message": f"Failed to change order {order_id} on {platform}: {str(e)}",
            "platform": platform,
            "account_id": account_id,
            "order_id": order_id,
            "response": {}
        }, indent=2)

@mcp.tool()
def get_account_history(account_id: Optional[str] = None, platform: str = "tradier", 
                       use_sandbox: bool = True, limit: Optional[int] = None, 
                       page: Optional[int] = None, start_date: Optional[str] = None, 
                       end_date: Optional[str] = None, type_filter: Optional[str] = None) -> str:
    """
    Get historical activity for a trading account.
    
    Args:
        account_id: Optional specific account ID. If not provided, uses account ID from environment variables.
        platform: Trading platform to use (default: 'tradier')
        use_sandbox: Whether to use sandbox environment (default: True)
        limit: Number of records to return (optional)
        page: Page number for pagination (optional)
        start_date: Start date in YYYY-MM-DD format (optional)
        end_date: End date in YYYY-MM-DD format (optional)
        type_filter: Filter by transaction type (optional)
    
    Returns:
        JSON string containing account history information
    """
    try:
        # Use environment account ID if none provided
        if account_id is None:
            account_id = _get_account_id(platform=platform, use_sandbox=use_sandbox)
        
        client = get_trading_client(platform=platform, use_sandbox=use_sandbox)
        
        # Get account history
        history = client.get_account_history(
            account_id=account_id,
            limit=limit,
            page=page,
            start_date=start_date,
            end_date=end_date,
            type_filter=type_filter
        )
        
        # Build summary message
        summary_parts = []
        if history['start_date'] and history['end_date']:
            summary_parts.append(f"from {history['start_date']} to {history['end_date']}")
        elif history['start_date']:
            summary_parts.append(f"from {history['start_date']}")
        elif history['end_date']:
            summary_parts.append(f"until {history['end_date']}")
        
        if history['type_filter']:
            summary_parts.append(f"filtered by {history['type_filter']}")
        
        summary = " ".join(summary_parts) if summary_parts else "all available"
        
        return json.dumps({
            "status": "success",
            "message": f"Retrieved {history['total_events']} historical events {summary} from {platform}",
            "platform": platform,
            "account_id": account_id,
            "total_events": history['total_events'],
            "filters": {
                "start_date": start_date,
                "end_date": end_date,
                "type_filter": type_filter,
                "limit": limit,
                "page": page
            },
            "events": history['events']
        }, indent=2)
        
    except Exception as e:
        return json.dumps({
            "status": "error",
            "message": f"Failed to get account history from {platform}: {str(e)}",
            "platform": platform,
            "account_id": account_id,
            "total_events": 0,
            "events": []
        }, indent=2)

@mcp.tool()
def list_platforms() -> str:
    """
    List all supported trading platforms.
    
    Returns:
        JSON string containing supported platforms
    """
    server_logger.info("Listing supported platforms")
    return json.dumps({
        "status": "success",
        "message": f"Supported trading platforms: {', '.join(SUPPORTED_PLATFORMS)}",
        "platforms": SUPPORTED_PLATFORMS,
        "default_platform": "tradier"
    }, indent=2)

@mcp.tool()
def health_check() -> str:
    """
    Check the health status of the MCP trading server.
    
    Returns:
        JSON string containing server health information
    """
    server_logger.info("Performing health check")
    
    health_status = {
        "status": "success",
        "message": "MCP Trading Server is running",
        "server_info": {
            "name": "trading",
            "supported_platforms": SUPPORTED_PLATFORMS,
            "cached_clients": list(clients.keys()),
            "environment_variables": {
                "TRADIER_SANDBOX_ACCESS_TOKEN": "SET" if os.getenv("TRADIER_SANDBOX_ACCESS_TOKEN") else "NOT_SET",
                "TRADIER_ACCESS_TOKEN": "SET" if os.getenv("TRADIER_ACCESS_TOKEN") else "NOT_SET",
                "TRADIER_SANDBOX_ACCOUNT_NUMBER": "SET" if os.getenv("TRADIER_SANDBOX_ACCOUNT_NUMBER") else "NOT_SET",
                "TRADIER_PRODUCTION_ACCOUNT_NUMBER": "SET" if os.getenv("TRADIER_PRODUCTION_ACCOUNT_NUMBER") else "NOT_SET"
            }
        }
    }
    
    # Test client creation if possible (using environment variables)
    try:
        test_client = get_trading_client(platform="tradier", use_sandbox=True)
        health_status["server_info"]["client_test"] = "PASSED"
        server_logger.info("Health check passed - client creation successful")
    except Exception as e:
        health_status["server_info"]["client_test"] = f"FAILED: {str(e)}"
        health_status["status"] = "warning"
        health_status["message"] = f"MCP Trading Server is running but client test failed: {str(e)}"
        server_logger.warning(f"Health check warning - client test failed: {str(e)}")
    
    return json.dumps(health_status, indent=2)

if __name__ == "__main__":
    server_logger.info("Starting MCP Trading Server...")
    server_logger.info(f"Supported platforms: {SUPPORTED_PLATFORMS}")
    server_logger.info("Server is ready to accept connections")
    
    try:
        # Run as HTTP server on all interfaces
        import uvicorn
        from mcp.server.fastmcp import FastMCP
        
        # Create the ASGI app
        app = mcp.streamable_http_app()
        
        # Run with uvicorn
        server_logger.info("Starting HTTP server on http://0.0.0.0:8000/mcp")
        uvicorn.run(app, host="0.0.0.0", port=8000, log_level="info")
        
    except KeyboardInterrupt:
        server_logger.info("Server stopped by user")
    except Exception as e:
        server_logger.error(f"Server error: {str(e)}")
        raise

