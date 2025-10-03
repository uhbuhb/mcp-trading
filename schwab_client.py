"""
Schwab API Client
Handles all API interactions with the Schwab trading platform using schwab-py library.
"""

import os
import json
import logging
from typing import Dict, List, Optional, Any
from datetime import datetime, timedelta, timezone
from schwab.auth import easy_client
from schwab.orders.equities import equity_buy_market, equity_sell_market
from schwab.orders.options import option_buy_to_open_market, option_sell_to_close_market
from schwab.orders.generic import OrderBuilder
from schwab.orders.common import OrderType, Duration, Session, OrderStrategyType
from schwab.orders.common import OptionInstruction
from trading_platform_interface import TradingPlatformInterface
from option_symbol_utils import convert_occ_to_schwab_format

logger = logging.getLogger("schwab_client")



class SchwabClient(TradingPlatformInterface):
    """Client for interacting with the Schwab API."""

    def __init__(self, access_token: str, refresh_token: str, account_hash: str,
                 app_key: Optional[str] = None, app_secret: Optional[str] = None,
                 token_expires_at: Optional[datetime] = None, token_path: Optional[str] = None):
        """
        Initialize the Schwab client using stored tokens for API access.

        Args:
            access_token: OAuth access token
            refresh_token: OAuth refresh token
            account_hash: Schwab account hash
            app_key: Schwab app key (defaults to env var)
            app_secret: Schwab app secret (defaults to env var)
            token_expires_at: When the access token expires
            token_path: Path to store authentication tokens (unused, kept for compatibility)
        """
        self.account_hash = account_hash
        self.access_token = access_token
        self.refresh_token = refresh_token
        self.token_expires_at = token_expires_at
        self.app_key = app_key or os.getenv("SCHWAB_APP_KEY")
        self.app_secret = app_secret or os.getenv("SCHWAB_APP_SECRET")
        
        # Validate required parameters
        if not self.app_key:
            raise ValueError("SCHWAB_APP_KEY environment variable is required")
        if not self.app_secret:
            raise ValueError("SCHWAB_APP_SECRET environment variable is required")
        if not access_token:
            raise ValueError("access_token is required")
        if not refresh_token:
            raise ValueError("refresh_token is required")
        if not account_hash:
            raise ValueError("account_hash is required")
        
        # Initialize HTTP client for direct API calls
        import httpx
        self.http_client = httpx.Client()
        
        logger.info(f"Initialized SchwabClient for account hash: {account_hash[:8]}...")

    def _check_token_refresh(self):
        """Check if token needs refresh and refresh if necessary."""
        if not self.token_expires_at:
            return  # No expiration info, assume token is valid
        
        # Check if token expires in the next 5 minutes
        current_time = datetime.now(timezone.utc)
        
        # Handle timezone-aware comparison - ensure both datetimes are timezone-aware
        expires_at = self.token_expires_at
        # If expires_at is naive, assume it's UTC
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)
        
        if expires_at > current_time + timedelta(minutes=5):
            return  # Token is still valid
        
        logger.info("Access token expired or expiring soon, refreshing...")
        self._refresh_access_token()
    
    def _refresh_access_token(self):
        """Refresh the access token using the refresh token."""
        import base64
        
        # Prepare refresh request
        token_url = "https://api.schwabapi.com/v1/oauth/token"
        
        # Create Basic Auth header
        credentials = f"{self.app_key}:{self.app_secret}"
        basic_auth = base64.b64encode(credentials.encode()).decode()
        
        headers = {
            "Authorization": f"Basic {basic_auth}",
            "Content-Type": "application/x-www-form-urlencoded"
        }
        
        data = {
            "grant_type": "refresh_token",
            "refresh_token": self.refresh_token
        }
        
        try:
            response = self.http_client.post(token_url, data=data, headers=headers)
            response.raise_for_status()
            
            token_response = response.json()
            
            # Update tokens
            self.access_token = token_response["access_token"]
            if "refresh_token" in token_response:
                self.refresh_token = token_response["refresh_token"]
            
            # Update expiration time
            expires_in = token_response.get("expires_in", 1800)  # Default 30 minutes
            self.token_expires_at = datetime.now(timezone.utc) + timedelta(seconds=expires_in)
            
            logger.info("Successfully refreshed access token")
            
            # TODO: Update stored credentials in database
            # This would require access to the database session
            
        except Exception as e:
            logger.error(f"Failed to refresh access token: {e}")
            raise

    def get_account_info(self, account_id: Optional[str] = None) -> Dict[str, Any]:
        """
        Get account information.

        Args:
            account_id: Specific account hash (optional, uses default if not provided)

        Returns:
            Account information dictionary
        """
        self._check_token_refresh()
        account_to_use = account_id or self.account_hash

        try:
            # Make direct API call to Schwab
            headers = {
                "Authorization": f"Bearer {self.access_token}",
                "Accept": "application/json"
            }
            
            url = f"https://api.schwabapi.com/trader/v1/accounts/{account_to_use}"
            response = self.http_client.get(url, headers=headers)
            response.raise_for_status()
            
            data = response.json()

            if 'securitiesAccount' in data:
                account = data['securitiesAccount']
                return {
                    'account_id': account.get('accountId', 'N/A'),
                    'account_number': account.get('accountNumber', 'N/A'),
                    'type': account.get('type', 'N/A'),
                    'is_day_trader': account.get('isDayTrader', False),
                    'is_closing_only': account.get('isClosingOnlyRestricted', False),
                    'round_trips': account.get('roundTrips', 0)
                }
            else:
                # Return raw data for debugging when expected structure not found
                logger.warning("Expected 'securitiesAccount' not found in response, returning raw data")
                return {
                    'raw_response': data,
                    'message': 'Expected securitiesAccount structure not found in response'
                }

        except Exception as e:
            logger.error(f"Failed to get account info: {e}")
            raise Exception(f"API request failed: {e}")

    def get_account_number(self) -> str:
        """
        Get the account hash.

        Returns:
            Account hash string
        """
        return self.account_hash

    def get_positions(self, account_id: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        Get current positions.

        Args:
            account_id: Specific account hash (optional)

        Returns:
            List of position dictionaries
        """
        self._check_token_refresh()
        account_to_use = account_id or self.account_hash

        try:
            # Make direct API call to Schwab
            headers = {
                "Authorization": f"Bearer {self.access_token}",
                "Accept": "application/json"
            }
            
            # Get account with positions
            url = f"https://api.schwabapi.com/trader/v1/accounts/{account_to_use}"
            params = {"fields": "positions"}
            response = self.http_client.get(url, headers=headers, params=params)
            response.raise_for_status()
            
            data = response.json()

            if 'securitiesAccount' in data and 'positions' in data['securitiesAccount']:
                positions_data = data['securitiesAccount']['positions']

                formatted_positions = []
                for pos in positions_data:
                    instrument = pos.get('instrument', {})
                    formatted_pos = {
                        'symbol': instrument.get('symbol', 'N/A'),
                        'description': instrument.get('description', 'N/A'),
                        'quantity': pos.get('longQuantity', 0) - pos.get('shortQuantity', 0),
                        'cost_basis': pos.get('averagePrice', 0) * abs(pos.get('longQuantity', 0) - pos.get('shortQuantity', 0)),
                        'last_price': pos.get('marketValue', 0) / abs(pos.get('longQuantity', 1)) if pos.get('longQuantity', 0) != 0 else 0,
                        'market_value': pos.get('marketValue', 0),
                        'gain_loss': pos.get('currentDayProfitLoss', 0),
                        'type': instrument.get('assetType', 'N/A')
                    }
                    formatted_positions.append(formatted_pos)

                return formatted_positions
            else:
                # Return raw data for debugging when expected structure not found
                logger.warning("Expected 'securitiesAccount' or 'positions' not found in response, returning raw data")
                return [{
                    'raw_response': data,
                    'message': 'Expected securitiesAccount.positions structure not found in response'
                }]

        except Exception as e:
            logger.error(f"Failed to get positions: {e}")
            raise Exception(f"API request failed: {e}")

    def get_quote(self, symbol: str) -> Dict[str, Any]:
        """
        Get quote information for a stock symbol.

        Args:
            symbol: Stock symbol (e.g., 'AAPL')

        Returns:
            Quote information dictionary
        """
        self._check_token_refresh()

        try:
            # Make direct API call to Schwab
            headers = {
                "Authorization": f"Bearer {self.access_token}",
                "Accept": "application/json"
            }
            
            url = f"https://api.schwabapi.com/marketdata/v1/quotes"
            params = {"symbols": symbol}
            response = self.http_client.get(url, headers=headers, params=params)
            response.raise_for_status()
            
            data = response.json()

            if symbol in data:
                quote = data[symbol]['quote']
                return {
                    'symbol': quote.get('symbol', 'N/A'),
                    'description': data[symbol].get('fundamental', {}).get('companyName', 'N/A'),
                    'last': quote.get('lastPrice', 'N/A'),
                    'bid': quote.get('bidPrice', 'N/A'),
                    'ask': quote.get('askPrice', 'N/A'),
                    'volume': quote.get('totalVolume', 'N/A'),
                    'high': quote.get('highPrice', 'N/A'),
                    'low': quote.get('lowPrice', 'N/A'),
                    'open': quote.get('openPrice', 'N/A'),
                    'previous_close': quote.get('closePrice', 'N/A'),
                    'change': quote.get('netChange', 'N/A'),
                    'change_percentage': quote.get('netPercentChange', 'N/A'),
                    'bid_size': quote.get('bidSize', 'N/A'),
                    'ask_size': quote.get('askSize', 'N/A')
                }
            else:
                raise Exception(f"No quote data found for symbol: {symbol}")

        except Exception as e:
            logger.error(f"Failed to get quote: {e}")
            raise Exception(f"API request failed: {e}")

    def get_balance(self, account_id: Optional[str] = None) -> Dict[str, Any]:
        """
        Get account balance information.

        Args:
            account_id: Specific account hash (optional)

        Returns:
            Balance information dictionary
        """
        self._check_token_refresh()
        account_to_use = account_id or self.account_hash

        try:
            # Make direct API call to Schwab
            headers = {
                "Authorization": f"Bearer {self.access_token}",
                "Accept": "application/json"
            }
            
            url = f"https://api.schwabapi.com/trader/v1/accounts/{account_to_use}"
            response = self.http_client.get(url, headers=headers)
            response.raise_for_status()
            
            data = response.json()

            if 'securitiesAccount' in data:
                balances = data['securitiesAccount'].get('currentBalances', {})
                initial_balances = data['securitiesAccount'].get('initialBalances', {})

                return {
                    'total_cash': float(balances.get('cashBalance', 0)),
                    'cash_available': float(balances.get('cashAvailableForTrading', 0)),
                    'cash_unsettled': float(balances.get('unsettledCash', 0)),
                    'total_equity': float(balances.get('equity', 0)),
                    'long_market_value': float(balances.get('longMarketValue', 0)),
                    'short_market_value': float(balances.get('shortMarketValue', 0)),
                    'buying_power': float(balances.get('buyingPower', 0)),
                    'day_trade_buying_power': float(balances.get('dayTradingBuyingPower', 0)),
                    'maintenance_requirement': float(balances.get('maintenanceRequirement', 0)),
                    'pending_deposits': float(balances.get('pendingDeposits', 0)),
                }
            else:
                # Return raw data for debugging when expected structure not found
                logger.warning("Expected 'securitiesAccount' not found in response, returning raw data")
                return {
                    'raw_response': data,
                    'message': 'Expected securitiesAccount structure not found in response'
                }

        except Exception as e:
            logger.error(f"Failed to get balance: {e}")
            raise Exception(f"API request failed: {e}")

    def get_orders(self, account_id: Optional[str] = None, include_filled: bool = True) -> List[Dict[str, Any]]:
        """
        Get orders for an account.

        Args:
            account_id: Specific account hash (optional)
            include_filled: Whether to include filled orders (default: True)

        Returns:
            List of order dictionaries
        """
        self._check_token_refresh()
        account_to_use = account_id or self.account_hash

        try:
            # Make direct API call to Schwab
            headers = {
                "Authorization": f"Bearer {self.access_token}",
                "Accept": "application/json"
            }
            
            # Get orders from last 90 days to ensure we don't miss recent orders
            from_date = datetime.now() - timedelta(days=90)
            to_date = datetime.now()
            
            url = f"https://api.schwabapi.com/trader/v1/accounts/{account_to_use}/orders"
            params = {
                "fromEnteredTime": from_date.strftime("%Y-%m-%dT%H:%M:%S.000Z"),
                "toEnteredTime": to_date.strftime("%Y-%m-%dT%H:%M:%S.000Z"),
                "maxResults": 500
            }
            
            logger.info(f"Requesting orders from URL: {url}")
            logger.info(f"Request params: {params}")
            
            response = self.http_client.get(url, headers=headers, params=params)
            
            if response.status_code != 200:
                logger.error(f"Orders API error: {response.status_code} - {response.text}")
                response.raise_for_status()
            
            data = response.json()

            if isinstance(data, list):
                # Debug: Log the structure of the first order to understand the format
                if data:
                    logger.info(f"Sample order structure: {json.dumps(data[0], indent=2)}")
                return data
            else:
                logger.warning(f"Unexpected response format: {type(data)} - {data}")
                return []

        except Exception as e:
            logger.error(f"Failed to get orders: {e}")
            raise Exception(f"API request failed: {e}")

    def create_multi_leg_option_order(self, legs: List[Dict[str, Any]], 
                                    order_type: str = 'market',
                                    price: Optional[float] = None,
                                    duration: str = 'day',
                                    session: str = 'normal') -> OrderBuilder:
        """
        Create a multi-leg option order using OrderBuilder.

        Args:
            legs: List of standardized leg dictionaries, each containing:
                - option_symbol: OCC format option symbol (e.g., 'V     251017C00340000')
                - side: Order side ('buy_to_open', 'sell_to_open', 'buy_to_close', 'sell_to_close')
                - quantity: Number of contracts
            order_type: Order type ('market' or 'limit')
            price: Net price for limit orders (positive for credit, negative for debit, CANT BE ZERO!!)
            duration: Order duration ('day', 'gtc', 'pre', 'post')
            session: Trading session ('normal', 'am', 'pm', 'seamless')
            

        Returns:
            OrderBuilder object ready for placement
        """
        try:
            # Create OrderBuilder
            order = OrderBuilder()


            # Set order type - transform interface format to Schwab format
            logger.info(f"create_multi_leg_option_order: order_type={order_type}, price={price} (type: {type(price)})")
            if order_type == 'market':
                order.set_order_type(OrderType.MARKET)
            elif order_type == 'limit':
                if price is None or price == 0:
                    raise ValueError("Limit order requires a price")
                if price > 0:
                    order.set_order_type(OrderType.NET_DEBIT)
                if price < 0:
                    order.set_order_type(OrderType.NET_CREDIT)

                logger.info(f"Setting price to: {str(price)}")
                order.set_price(str(price))  # Schwab expects price as string
            else:
                raise ValueError(f"Unsupported order type: {order_type}. Only 'market' and 'limit' are supported.")

            # Set duration
            if duration == 'gtc':
                order.set_duration(Duration.GOOD_TILL_CANCEL)
            elif duration == 'pre':
                order.set_duration(Duration.EXTENDED_HOURS)
            elif duration == 'post':
                order.set_duration(Duration.EXTENDED_HOURS)
            else:
                order.set_duration(Duration.DAY)

            # Set session
            if session == 'am':
                order.set_session(Session.AM)
            elif session == 'pm':
                order.set_session(Session.PM)
            elif session == 'seamless':
                order.set_session(Session.SEAMLESS)
            else:
                order.set_session(Session.NORMAL)

            # Set order strategy type - required for multileg orders
            order.set_order_strategy_type(OrderStrategyType.SINGLE)

            # Add legs - transform standardized format to Schwab format
            for leg in legs:
                option_symbol = leg.get('option_symbol')
                side = leg.get('side')
                quantity = leg.get('quantity')

                if not all([option_symbol, side, quantity]):
                    raise ValueError("Each leg must have 'option_symbol', 'side', and 'quantity'")

                # Convert OCC option symbol to Schwab format
                try:
                    schwab_symbol = convert_occ_to_schwab_format(option_symbol)
                    logger.info(f"Converted option symbol: '{option_symbol}' -> '{schwab_symbol}' (length: {len(schwab_symbol)})")
                except Exception as e:
                    logger.error(f"Failed to convert option symbol {option_symbol}: {e}")
                    raise ValueError(f"Invalid option symbol format: {option_symbol}")

                # Map standardized side strings to Schwab instruction enum
                instruction_map = {
                    'buy_to_open': OptionInstruction.BUY_TO_OPEN,
                    'sell_to_open': OptionInstruction.SELL_TO_OPEN,
                    'buy_to_close': OptionInstruction.BUY_TO_CLOSE,
                    'sell_to_close': OptionInstruction.SELL_TO_CLOSE
                }

                if side.lower() not in instruction_map:
                    raise ValueError(f"Unsupported side: {side}")

                order.add_option_leg(
                    symbol=schwab_symbol,
                    instruction=instruction_map[side.lower()],
                    quantity=int(quantity)
                )

            return order

        except Exception as e:
            logger.error(f"Failed to create multi-leg option order: {e}")
            raise Exception(f"Multi-leg order creation failed: {e}")

    def place_multileg_order(self, account_id: str, symbol: str, legs: list, 
                           order_type: str = 'market', duration: str = 'day', session: str = 'normal',
                           preview: bool = True, price: Optional[float] = None) -> Dict[str, Any]:
        """
        Place a multileg order (spread trade) or preview it.
        
        Args:
            account_id: Account hash
            symbol: Underlying symbol
            legs: List of standardized leg dictionaries, each containing:
                - option_symbol: OCC format option symbol (e.g., 'V251017C00340000')
                - side: Order side ('buy_to_open', 'sell_to_open', 'buy_to_close', 'sell_to_close')
                - quantity: Number of contracts (integer)
            order_type: Order type ('market' or 'limit')
            duration: Order duration ('day', 'gtc', etc.)
            preview: If True, preview the order without executing
            price: Net price for limit orders (positive for credit, negative for debit, 0 for even)
        
        Returns:
            Order response dictionary
        """
        self._check_token_refresh()
        
        logger.info(f"place_multileg_order called with price: {price} (type: {type(price)})")

        try:
            # Create OrderBuilder from the parameters
            order_builder = self.create_multi_leg_option_order(
                legs=legs,
                order_type=order_type,
                duration=duration,
                session=session,
                price=price,
            )
            
            # Use the existing place_multi_leg_option_order method
            return self.place_multi_leg_option_order(account_id, order_builder, preview)

        except Exception as e:
            logger.error(f"Failed to place multileg order: {e}")
            raise Exception(f"Multileg order placement failed: {e}")

    def place_multi_leg_option_order(self, account_id: str, order: OrderBuilder,
                                   preview: bool = False) -> Dict[str, Any]:
        """
        Place a multi-leg option order.

        Args:
            account_id: Account hash
            order: OrderBuilder object created with create_multi_leg_option_order
            preview: If True, preview the order without executing

        Returns:
            Order response dictionary
        """
        self._check_token_refresh()

        try:
            # Make direct API call to Schwab
            headers = {
                "Authorization": f"Bearer {self.access_token}",
                "Accept": "application/json",
                "Content-Type": "application/json"
            }
            
            # Build the order payload
            order_payload = order.build()
            logger.info(f"Schwab order payload: {json.dumps(order_payload, indent=2)}")
            
            if preview:
                url = f"https://api.schwabapi.com/trader/v1/accounts/{account_id}/previewOrder"
            else:
                url = f"https://api.schwabapi.com/trader/v1/accounts/{account_id}/orders"
                
            response = self.http_client.post(url, headers=headers, json=order_payload)
            
            # Log response details for debugging
            if response.status_code not in [200, 201]:
                logger.error(f"Schwab API error: {response.status_code} - {response.text}")
                logger.error(f"Request payload was: {json.dumps(order_payload, indent=2)}")
            
            response.raise_for_status()
            
            # Handle empty response body (common for successful order creation)
            if not response.text.strip():
                logger.info(f"Order created successfully with status {response.status_code} (empty response body)")
                return {"status": "success", "message": "Order created successfully"}
            
            return response.json()

        except Exception as e:
            logger.error(f"Failed to place multi-leg option order: {e}")
            raise Exception(f"Multi-leg order placement failed: {e}")

    def modify_order(self, account_id: str, order_id: str, 
                    order_type: Optional[str] = None,
                    price: Optional[float] = None,
                    duration: Optional[str] = None) -> Dict[str, Any]:
        """
        Modify an existing order by updating only the specified parameters.

        Args:
            account_id: Account hash
            order_id: Order ID to modify
            order_type: New order type ('market', 'limit') - optional
            price: New limit price (for limit orders) - optional
            duration: New order duration ('day', 'gtc', 'pre', 'post') - optional

        Returns:
            Order modification response dictionary
        """
        self._check_token_refresh()

        try:
            # Get the existing order first to understand its current state
            orders = self.get_orders(account_id, include_filled=True)
            existing_order = None
            
            for order in orders:
                if order.get('orderId') == order_id:
                    existing_order = order
                    break
            
            if not existing_order:
                raise Exception(f"Order {order_id} not found")

            # Check if order is filled
            if existing_order.get('status') == 'FILLED':
                raise Exception(f"Order modification failed: Order {order_id} is already filled")

            # update values of existing_order with received values
            if order_type is not None:
                existing_order['orderType'] = order_type
            if price is not None:
                existing_order['price'] = price
            if duration is not None:
                existing_order['duration'] = duration
            
            # Replace the order with the modified version
            headers = {
                "Authorization": f"Bearer {self.access_token}",
                "Accept": "application/json",
                "Content-Type": "application/json"
            }
            
            url = f"https://api.schwabapi.com/trader/v1/accounts/{account_id}/orders/{order_id}"
            response = self.http_client.put(url, headers=headers, json=existing_order)
            response.raise_for_status()
            return response.json()

        except Exception as e:
            logger.error(f"Failed to modify order: {e}")
            raise Exception(f"Order modification failed: {e}")

    def cancel_order(self, account_id: str, order_id: str) -> Dict[str, Any]:
        """
        Cancel an existing order.

        Args:
            account_id: Account hash
            order_id: Order ID to cancel

        Returns:
            Cancel order response dictionary
        """
        self._check_token_refresh()

        try:
            # Make direct API call to Schwab
            headers = {
                "Authorization": f"Bearer {self.access_token}",
                "Accept": "application/json"
            }
            
            url = f"https://api.schwabapi.com/trader/v1/accounts/{account_id}/orders/{order_id}"
            response = self.http_client.delete(url, headers=headers)
            response.raise_for_status()
            return {"status": "success", "message": f"Order {order_id} cancelled"}

        except Exception as e:
            logger.error(f"Failed to cancel order: {e}")
            raise Exception(f"Cancel order failed: {e}")

    def get_account_history(self, account_id: Optional[str] = None, limit: Optional[int] = None,
                           start_date: Optional[str] = None, end_date: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        Get account transaction history.

        Args:
            account_id: Optional account ID override
            limit: Maximum number of transactions to return
            start_date: Start date for history (YYYY-MM-DD)
            end_date: End date for history (YYYY-MM-DD)

        Returns:
            List of transaction dictionaries
        """
        self._check_token_refresh()

        try:
            account_to_use = account_id or self.account_hash
            headers = {
                "Authorization": f"Bearer {self.access_token}",
                "Accept": "application/json"
            }
            
            # Build query parameters
            params = {}
            if limit is not None:
                params['maxResults'] = limit
            if start_date is not None:
                params['startDate'] = start_date
            if end_date is not None:
                params['endDate'] = end_date
            
            url = f"https://api.schwabapi.com/trader/v1/accounts/{account_to_use}/transactions"
            response = self.http_client.get(url, headers=headers, params=params)
            response.raise_for_status()
            
            data = response.json()
            return data.get('transactions', [])

        except Exception as e:
            logger.error(f"Failed to get account history: {e}")
            raise Exception(f"Account history retrieval failed: {e}")

    def change_order(self, account_id: str, order_id: str, order_type: Optional[str] = None,
                    price: Optional[float] = None, stop: Optional[float] = None,
                    duration: Optional[str] = None, quantity: Optional[float] = None) -> Dict[str, Any]:
        """
        Modify an existing order.

        Args:
            account_id: Account hash
            order_id: Order ID to modify
            order_type: New order type (optional)
            price: New price (optional)
            stop: New stop price (optional)
            duration: New duration (optional)
            quantity: New quantity (optional)

        Returns:
            Modification response dictionary
        """
        self._check_token_refresh()

        try:
            headers = {
                "Authorization": f"Bearer {self.access_token}",
                "Accept": "application/json",
                "Content-Type": "application/json"
            }
            
            # Get the current order by fetching all orders and finding the specific one
            # Schwab API doesn't support fetching individual orders by ID directly
            logger.info(f"Fetching orders to find order {order_id}")
            orders = self.get_orders(account_id, include_filled=True)
            
            # Debug: Log all order IDs to help with troubleshooting
            logger.info(f"Found {len(orders)} orders in account")
            order_ids = [order.get('orderId') for order in orders if order.get('orderId')]
            logger.info(f"Order IDs found: {order_ids}")
            
            current_order = None
            for order in orders:
                order_id_from_api = order.get('orderId')
                logger.info(f"Comparing order ID: '{order_id_from_api}' (type: {type(order_id_from_api)}) with target: '{order_id}' (type: {type(order_id)})")
                
                # Handle both string and integer comparisons
                if (order_id_from_api == order_id or 
                    str(order_id_from_api) == str(order_id) or
                    order_id_from_api == int(order_id) if str(order_id).isdigit() else False):
                    current_order = order
                    break
            
            if not current_order:
                # Try alternative ID fields that Schwab might use
                for order in orders:
                    # Check if the ID might be in a different field
                    for key in ['orderId', 'id', 'order_id', 'orderNumber']:
                        if order.get(key) == order_id:
                            current_order = order
                            logger.info(f"Found order using field '{key}': {order_id}")
                            break
                    if current_order:
                        break
                
                if not current_order:
                    raise Exception(f"Order {order_id} not found in account orders. Available order IDs: {order_ids}")
            
            logger.info(f"Successfully found order {order_id}: {json.dumps(current_order, indent=2)}")
            
            # Build modification payload with required fields from Schwab API spec
            modification_payload = {
                "session": current_order.get('session'),
                "duration": current_order.get('duration'),
                "orderType": current_order.get('orderType'),
                "quantity": current_order.get('quantity'),
                "filledQuantity": current_order.get('filledQuantity'),
                "remainingQuantity": current_order.get('remainingQuantity'),
                "orderStrategyType": current_order.get('orderStrategyType'),
                "orderLegCollection": current_order.get('orderLegCollection', []).copy()
            }
            
            # Add price if it exists in the original order
            if 'price' in current_order:
                modification_payload['price'] = current_order['price']
            
            # Add complex order strategy type if it exists
            if 'complexOrderStrategyType' in current_order:
                modification_payload['complexOrderStrategyType'] = current_order['complexOrderStrategyType']
            
            # Update fields if provided
            if order_type is not None:
                modification_payload['orderType'] = order_type.upper()
            if price is not None:
                modification_payload['price'] = price
            if stop is not None:
                modification_payload['stopPrice'] = stop
            if duration is not None:
                modification_payload['duration'] = duration.upper()
            if quantity is not None:
                # Update quantity at both order level and leg level
                modification_payload['quantity'] = int(quantity)
                modification_payload['remainingQuantity'] = int(quantity) - modification_payload.get('filledQuantity', 0)
                for leg in modification_payload['orderLegCollection']:
                    leg['quantity'] = int(quantity)
            
            # Replace the order
            replace_url = f"https://api.schwabapi.com/trader/v1/accounts/{account_id}/orders/{order_id}"
            logger.info(f"Modifying order at: {replace_url}")
            logger.info(f"Modification payload: {json.dumps(modification_payload, indent=2)}")
            
            response = self.http_client.put(replace_url, headers=headers, json=modification_payload)
            
            if response.status_code not in [200, 201]:
                logger.error(f"Failed to modify order {order_id}: {response.status_code} - {response.text}")
                raise Exception(f"Failed to modify order {order_id}: {response.status_code} - {response.text}")
            
            logger.info(f"Successfully modified order {order_id}")
            
            # Handle empty response body (common for successful order modifications)
            if not response.text.strip():
                logger.info(f"Order modified successfully with status {response.status_code} (empty response body)")
                return {"status": "success", "message": "Order modified successfully"}
            
            return response.json()

        except Exception as e:
            logger.error(f"Failed to modify order {order_id}: {e}")
            raise Exception(f"Order modification failed: {e}")

