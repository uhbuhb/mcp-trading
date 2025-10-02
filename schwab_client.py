"""
Schwab API Client
Handles all API interactions with the Schwab trading platform using schwab-py library.
"""

import os
import logging
from typing import Dict, List, Optional, Any
from datetime import datetime, timedelta, timezone
from schwab.auth import easy_client
from schwab.orders.equities import equity_buy_market, equity_sell_market
from schwab.orders.options import option_buy_to_open_market, option_sell_to_close_market
from schwab.orders.generic import OrderBuilder
from schwab.orders.common import OrderType, Duration, Session, OrderStrategyType
from schwab.orders.common import ComplexOrderStrategyType, OptionInstruction, EquityInstruction
from trading_platform_interface import TradingPlatformInterface

logger = logging.getLogger("schwab_client")


class SchwabClient(TradingPlatformInterface):
    """Client for interacting with the Schwab API."""

    def __init__(self, access_token: str, refresh_token: str, account_hash: str,
                 app_key: Optional[str] = None, app_secret: Optional[str] = None,
                 token_expires_at: Optional[datetime] = None, token_path: Optional[str] = None):
        """
        Initialize the Schwab client using easy_client for simplified authentication.

        Args:
            access_token: OAuth access token (for compatibility, but easy_client handles auth)
            refresh_token: OAuth refresh token (for compatibility, but easy_client handles auth)
            account_hash: Schwab account hash
            app_key: Schwab app key (defaults to env var)
            app_secret: Schwab app secret (defaults to env var)
            token_expires_at: When the access token expires (for compatibility)
            token_path: Path to store authentication tokens (defaults to /tmp/schwab_token.json)
        """
        self.account_hash = account_hash
        self.app_key = app_key or os.getenv("SCHWAB_APP_KEY")
        self.app_secret = app_secret or os.getenv("SCHWAB_APP_SECRET")
        
        # Set default token path if not provided
        if not token_path:
            token_path = os.path.join(os.path.expanduser("~"), ".schwab_token.json")
        
        # Validate required environment variables
        if not self.app_key:
            raise ValueError("SCHWAB_APP_KEY environment variable is required")
        if not self.app_secret:
            raise ValueError("SCHWAB_APP_SECRET environment variable is required")
        
        # Initialize Schwab client using easy_client
        # This handles authentication, token refresh, and session management automatically
        self.client = easy_client(
            api_key=self.app_key,
            app_secret=self.app_secret,
            callback_url='https://127.0.0.1:8080',
            token_path=token_path
        )

    def _check_token_refresh(self):
        """Token refresh is handled automatically by easy_client."""
        # easy_client handles token refresh automatically, so this method is now a no-op
        pass

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
            response = self.client.get_account(account_to_use)
            # easy_client returns httpx.Response objects, so we need to check status and get JSON
            if response.status_code != 200:
                raise Exception(f"API request failed with status {response.status_code}: {response.text}")
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
            # Import client here to avoid circular import issues
            from schwab import client
            response = self.client.get_account(account_to_use, fields=client.Client.Account.Fields.POSITIONS)
            # easy_client returns httpx.Response objects, so we need to check status and get JSON
            if response.status_code != 200:
                raise Exception(f"API request failed with status {response.status_code}: {response.text}")
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
            response = self.client.get_quote(symbol)
            # easy_client returns httpx.Response objects, so we need to check status and get JSON
            if response.status_code != 200:
                raise Exception(f"API request failed with status {response.status_code}: {response.text}")
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
            response = self.client.get_account(account_to_use)
            # easy_client returns httpx.Response objects, so we need to check status and get JSON
            if response.status_code != 200:
                raise Exception(f"API request failed with status {response.status_code}: {response.text}")
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
            # Get orders from last 60 days
            from_date = datetime.now() - timedelta(days=60)
            to_date = datetime.now()

            response = self.client.get_orders_for_account(
                account_to_use,
                from_entered_datetime=from_date,
                to_entered_datetime=to_date
            )
            # easy_client returns httpx.Response objects, so we need to check status and get JSON
            if response.status_code != 200:
                raise Exception(f"API request failed with status {response.status_code}: {response.text}")
            data = response.json()

            if isinstance(data, list):
                return data
            else:
                return []

        except Exception as e:
            logger.error(f"Failed to get orders: {e}")
            raise Exception(f"API request failed: {e}")

    def create_multi_leg_option_order(self, legs: List[Dict[str, Any]], 
                                    order_type: str = 'market',
                                    price: Optional[float] = None,
                                    duration: str = 'day',
                                    session: str = 'normal',
                                    complex_strategy_type: Optional[str] = None) -> OrderBuilder:
        """
        Create a multi-leg option order using OrderBuilder.

        Args:
            legs: List of leg dictionaries, each containing:
                - symbol: Option symbol (e.g., 'AAPL_011724C150')
                - instruction: 'BUY_TO_OPEN', 'SELL_TO_OPEN', 'BUY_TO_CLOSE', 'SELL_TO_CLOSE'
                - quantity: Number of contracts
            order_type: Order type ('market', 'limit', 'stop', 'stop_limit')
            price: Limit price (required for limit orders)
            duration: Order duration ('day', 'gtc', 'pre', 'post')
            session: Trading session ('normal', 'am', 'pm', 'seamless')
            complex_strategy_type: Complex strategy type for spreads (e.g., 'VERTICAL', 'STRADDLE')

        Returns:
            OrderBuilder object ready for placement
        """
        try:
            # Create OrderBuilder
            order = OrderBuilder()

            # Set order type
            if order_type == 'market':
                order.set_order_type(OrderType.MARKET)
            elif order_type == 'limit':
                order.set_order_type(OrderType.LIMIT)
                if price is None:
                    raise ValueError("Price is required for limit orders")
                order.set_price(price)
            elif order_type == 'stop':
                order.set_order_type(OrderType.STOP)
                if price is None:
                    raise ValueError("Stop price is required for stop orders")
                order.set_stop_price(price)
            elif order_type == 'stop_limit':
                order.set_order_type(OrderType.STOP_LIMIT)
                if price is None:
                    raise ValueError("Stop price is required for stop_limit orders")
                order.set_stop_price(price)
            else:
                raise ValueError(f"Unsupported order type: {order_type}")

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

            # Set complex strategy type if provided
            if complex_strategy_type:
                strategy_map = {
                    'VERTICAL': ComplexOrderStrategyType.VERTICAL,
                    'HORIZONTAL': ComplexOrderStrategyType.HORIZONTAL,
                    'DIAGONAL': ComplexOrderStrategyType.DIAGONAL,
                    'STRADDLE': ComplexOrderStrategyType.STRADDLE,
                    'STRANGLE': ComplexOrderStrategyType.STRANGLE,
                    'BUTTERFLY': ComplexOrderStrategyType.BUTTERFLY,
                    'CONDOR': ComplexOrderStrategyType.CONDOR,
                    'IRON_CONDOR': ComplexOrderStrategyType.IRON_CONDOR,
                    'COLLAR': ComplexOrderStrategyType.COLLAR_SYNTHETIC,
                    'CUSTOM': ComplexOrderStrategyType.CUSTOM
                }
                if complex_strategy_type.upper() in strategy_map:
                    order.set_complex_order_strategy_type(strategy_map[complex_strategy_type.upper()])

            # Add legs
            for leg in legs:
                symbol = leg.get('symbol')
                instruction = leg.get('instruction')
                quantity = leg.get('quantity')

                if not all([symbol, instruction, quantity]):
                    raise ValueError("Each leg must have 'symbol', 'instruction', and 'quantity'")

                # Map instruction strings to OptionInstruction enum
                instruction_map = {
                    'BUY_TO_OPEN': OptionInstruction.BUY_TO_OPEN,
                    'SELL_TO_OPEN': OptionInstruction.SELL_TO_OPEN,
                    'BUY_TO_CLOSE': OptionInstruction.BUY_TO_CLOSE,
                    'SELL_TO_CLOSE': OptionInstruction.SELL_TO_CLOSE
                }

                if instruction.upper() not in instruction_map:
                    raise ValueError(f"Unsupported instruction: {instruction}")

                order.add_option_leg(
                    symbol=symbol,
                    instruction=instruction_map[instruction.upper()],
                    quantity=int(quantity)
                )

            return order

        except Exception as e:
            logger.error(f"Failed to create multi-leg option order: {e}")
            raise Exception(f"Multi-leg order creation failed: {e}")

    def place_multileg_order(self, account_id: str, symbol: str, legs: list, 
                           order_type: str = 'market', duration: str = 'day', 
                           preview: bool = False, price: Optional[float] = None) -> Dict[str, Any]:
        """
        Place a multileg order (spread trade) or preview it.
        
        Args:
            account_id: Account hash
            symbol: Underlying symbol
            legs: List of leg dictionaries with 'side', 'quantity', 'option_symbol'
            order_type: Order type ('market', 'credit', 'debit', 'even', 'limit')
            duration: Order duration ('day', 'gtc', etc.)
            preview: If True, preview the order without executing
            price: Net price for limit orders (required for 'limit' order_type)
            
        Returns:
            Order response dictionary
        """
        self._check_token_refresh()

        try:
            # Create OrderBuilder from the parameters
            order_builder = self.create_multi_leg_option_order(
                legs=legs,
                order_type=order_type,
                duration=duration,
                price=price
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
            if preview:
                # Schwab doesn't have a preview endpoint in the same way
                return {
                    "status": "preview", 
                    "message": "Preview not supported, use with caution",
                    "order_spec": order.build()
                }
            else:
                response = self.client.place_order(account_id, order)
                # easy_client returns httpx.Response objects, so we need to check status and get JSON
                if response.status_code != 200:
                    raise Exception(f"Order placement failed with status {response.status_code}: {response.text}")
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
            response = self.client.replace_order(order_id, account_id, existing_order)
            # easy_client returns httpx.Response objects, so we need to check status and get JSON
            if response.status_code != 200:
                raise Exception(f"Order modification failed with status {response.status_code}: {response.text}")
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
            response = self.client.cancel_order(order_id, account_id)
            # easy_client returns httpx.Response objects, so we need to check status
            if response.status_code != 200:
                raise Exception(f"Order cancellation failed with status {response.status_code}: {response.text}")
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
                    price: Optional[float] = None, duration: Optional[str] = None) -> Dict[str, Any]:
        """
        Modify an existing order.

        Args:
            account_id: Account hash
            order_id: Order ID to modify
            order_type: New order type (optional)
            price: New price (optional)
            duration: New duration (optional)

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
            
            # First get the current order to understand its structure
            get_url = f"https://api.schwabapi.com/trader/v1/accounts/{account_id}/orders/{order_id}"
            get_response = self.http_client.get(get_url, headers=headers)
            get_response.raise_for_status()
            current_order = get_response.json()
            
            # Build modification payload
            modification_payload = current_order.copy()
            
            # Update fields if provided
            if order_type is not None:
                modification_payload['orderType'] = order_type.upper()
            if price is not None:
                modification_payload['price'] = price
            if duration is not None:
                modification_payload['duration'] = duration.upper()
            
            # Replace the order
            replace_url = f"https://api.schwabapi.com/trader/v1/accounts/{account_id}/orders/{order_id}"
            response = self.http_client.put(replace_url, headers=headers, json=modification_payload)
            response.raise_for_status()
            return response.json()

        except Exception as e:
            logger.error(f"Failed to modify order {order_id}: {e}")
            raise Exception(f"Order modification failed: {e}")
