"""
Schwab API Client
Handles all API interactions with the Schwab trading platform using schwab-py library.
"""

import os
import json
import logging
from typing import Dict, List, Optional, Any
from datetime import datetime, timedelta, timezone
from schwab.auth import client_from_access_functions
from schwab.orders.generic import OrderBuilder
from schwab.orders.common import OrderType, Duration, Session, OrderStrategyType
from schwab.orders.common import OptionInstruction
from schwab.client.base import BaseClient
from trading_platform_interface import TradingPlatformInterface
from option_symbol_utils import convert_occ_to_schwab_format

logger = logging.getLogger("schwab_client")



class SchwabClient(TradingPlatformInterface):
    """Client for interacting with the Schwab API."""

    def __init__(self, access_token: str, refresh_token: str, account_hash: str,
                 app_key: Optional[str] = None, app_secret: Optional[str] = None,
                 token_expires_at: Optional[datetime] = None, token_path: Optional[str] = None):
        """
        Initialize the Schwab client using the schwab-py library with custom token management.

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
        if not account_hash:
            raise ValueError("account_hash is required")
        
        # Initialize schwab-py client with custom token management
        self.schwab_client = client_from_access_functions(
            api_key=self.app_key,
            app_secret=self.app_secret,
            token_read_func=self._read_token,
            token_write_func=self._write_token
        )
        
        logger.info(f"Initialized SchwabClient for account hash: {account_hash[:8]}...")

    def _read_token(self) -> Dict[str, Any]:
        """
        Read token for schwab-py client.
        
        Returns:
            Token dictionary in the format expected by schwab-py
        """
        # Calculate when the token was created (assuming 30 minute lifetime)
        current_time = datetime.now(timezone.utc)
        
        # If we have expiration time, calculate creation time from that
        if self.token_expires_at:
            expires_at = self.token_expires_at
            if expires_at.tzinfo is None:
                expires_at = expires_at.replace(tzinfo=timezone.utc)
            
            # Token lifetime is typically 30 minutes (1800 seconds)
            token_lifetime = 1800
            creation_time = expires_at - timedelta(seconds=token_lifetime)
            creation_timestamp = int(creation_time.timestamp())
        else:
            # If no expiration time, assume token was created recently
            creation_timestamp = int(current_time.timestamp())
        
        # Return token in the format expected by schwab-py
        return {
            "token": {
                "access_token": self.access_token,
                "refresh_token": self.refresh_token,
                "token_type": "Bearer",
                "expires_in": 1800,  # 30 minutes default
                "scope": "trading"
            },
            "creation_timestamp": creation_timestamp
        }

    def _write_token(self, token: Dict[str, Any], *args, **kwargs) -> None:
        """
        Write token for schwab-py client.
        
        Args:
            token: Updated token dictionary from schwab-py
        """
        # Update our internal token state
        if "access_token" in token:
            self.access_token = token["access_token"]
        if "refresh_token" in token:
            self.refresh_token = token["refresh_token"]
        
        # Update expiration time if provided
        if "expires_in" in token:
            expires_in = token["expires_in"]
            self.token_expires_at = datetime.now(timezone.utc) + timedelta(seconds=expires_in)
        
        logger.info("Token updated by schwab-py client")

    def _resolve_account_id(self, account_id: Optional[str]) -> str:
        """Resolve account ID, using default if not provided."""
        return account_id or self.account_hash



    def get_account_info(self, account_id: Optional[str] = None) -> Dict[str, Any]:
        """
        Get account information.

        Args:
            account_id: Specific account hash (optional, uses default if not provided)

        Returns:
            Account information dictionary
        """
        account_to_use = self._resolve_account_id(account_id)

        try:
            # Use schwab-py client high-level method to get account info
            response = self.schwab_client.get_account(account_to_use)
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
            raise

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
        account_to_use = self._resolve_account_id(account_id)

        try:
            # Use schwab-py client high-level method to get account with positions
            response = self.schwab_client.get_account(account_to_use, fields=BaseClient.Account.Fields.POSITIONS)
            
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
            raise

    def get_quote(self, symbol: str) -> Dict[str, Any]:
        """
        Get quote information for a stock symbol.

        Args:
            symbol: Stock symbol (e.g., 'AAPL')

        Returns:
            Quote information dictionary
        """
        try:
            # Use schwab-py client high-level method to get quote
            response = self.schwab_client.get_quote(symbol)
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
            raise

    def get_balance(self, account_id: Optional[str] = None) -> Dict[str, Any]:
        """
        Get account balance information.

        Args:
            account_id: Specific account hash (optional)

        Returns:
            Balance information dictionary
        """
        account_to_use = self._resolve_account_id(account_id)

        try:
            # Use schwab-py client high-level method to get account balance
            response = self.schwab_client.get_account(account_to_use)
            data = response.json()

            if 'securitiesAccount' in data:
                balances = data['securitiesAccount'].get('currentBalances', {})

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
            raise

    def get_orders(self, account_id: Optional[str] = None, include_filled: bool = True) -> List[Dict[str, Any]]:
        """
        Get orders for an account.

        Args:
            account_id: Specific account hash (optional)
            include_filled: Whether to include filled orders (default: True)

        Returns:
            List of order dictionaries
        """
        account_to_use = self._resolve_account_id(account_id)

        try:
            # Use schwab-py client high-level method to get orders
            from_date = datetime.now() - timedelta(days=90)
            to_date = datetime.now()
            
            response = self.schwab_client.get_orders_for_account(
                account_to_use,
                from_entered_datetime=from_date,
                to_entered_datetime=to_date,
                max_results=500
            )
            
            data = response.json()

            if isinstance(data, list):
                return data
            else:
                logger.warning(f"Unexpected response format: {type(data)} - {data}")
                return []

        except Exception as e:
            logger.error(f"Failed to get orders: {e}")
            raise

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
            if order_type == 'market':
                order.set_order_type(OrderType.MARKET)
            elif order_type == 'limit':
                if price is None or price == 0:
                    raise ValueError("Limit order requires a price")
                if price > 0:
                    order.set_order_type(OrderType.NET_DEBIT)
                if price < 0:
                    order.set_order_type(OrderType.NET_CREDIT)

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
            raise

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
            raise

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
        try:
            # Build the order payload
            order_payload = order.build()
            
            if preview:
                # Use schwab-py client high-level method to preview order
                response = self.schwab_client.preview_order(account_id, order_payload)
            else:
                # Use schwab-py client high-level method to place order
                response = self.schwab_client.place_order(account_id, order_payload)
            
            # Log response details for debugging
            if response.status_code not in [200, 201]:
                logger.error(f"Schwab API error: {response.status_code} - {response.text}")
            
            response.raise_for_status()
            
            # Handle empty response body (common for successful order creation)
            if not response.text.strip():
                logger.info(f"Order created successfully with status {response.status_code} (empty response body)")
                return {"status": "success", "message": "Order created successfully"}
            
            return response.json()

        except Exception as e:
            logger.error(f"Failed to place multi-leg option order: {e}")
            raise


    def cancel_order(self, account_id: str, order_id: str) -> Dict[str, Any]:
        """
        Cancel an existing order.

        Args:
            account_id: Account hash
            order_id: Order ID to cancel

        Returns:
            Cancel order response dictionary
        """
        try:
            # Use schwab-py client high-level method to cancel order
            response = self.schwab_client.cancel_order(order_id, account_id)
            response.raise_for_status()
            return {"status": "success", "message": f"Order {order_id} cancelled"}

        except Exception as e:
            logger.error(f"Failed to cancel order: {e}")
            raise

    def get_order(self, account_id: str, order_id: str) -> Dict[str, Any]:
        """
        Get a specific order by ID.

        Args:
            account_id: Account hash
            order_id: Order ID to retrieve

        Returns:
            Order dictionary
        """
        try:
            # Use schwab-py client high-level method to get specific order
            response = self.schwab_client.get_order(account_id, order_id)
            response.raise_for_status()
            
            return response.json()

        except Exception as e:
            logger.error(f"Failed to get order {order_id}: {e}")
            raise

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
        try:
            account_to_use = self._resolve_account_id(account_id)
            
            # Use schwab-py client high-level method to get account history
            response = self.schwab_client.get_transactions(
                account_to_use,
                max_results=limit,
                start_date=start_date,
                end_date=end_date
            )
            response.raise_for_status()
            
            data = response.json()
            return data.get('transactions', [])

        except Exception as e:
            logger.error(f"Failed to get account history: {e}")
            raise

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
        try:
            # Get the current order using schwab-py client
            current_order = self.get_order(account_id, order_id)
            
            # Check if order is filled
            if current_order.get('status') == 'FILLED':
                raise Exception(f"Order modification failed: Order {order_id} is already filled")
            
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
            
            # Use schwab-py client high-level method to replace the order
            response = self.schwab_client.replace_order(account_id, order_id, modification_payload)
            
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
            raise

