"""
Tradier API Client
Handles all API interactions with the Tradier trading platform.
"""

import requests
import json
from typing import Dict, List, Optional, Any
from trading_platform_interface import TradingPlatformInterface


class TradierClient(TradingPlatformInterface):
    """Client for interacting with the Tradier API."""
    
    def __init__(self, access_token: str, sandbox: bool = True):
        """
        Initialize the Tradier client.
        
        Args:
            access_token: Your Tradier API access token
            sandbox: Whether to use sandbox environment (default: True)
        """
        self.access_token = access_token
        self.sandbox = sandbox
        
        if sandbox:
            self.base_url = "https://sandbox.tradier.com"
        else:
            self.base_url = "https://api.tradier.com"
        
        
        self.headers = {
            'Authorization': f'Bearer {access_token}',
            'Accept': 'application/json'
        }
    
    def _make_request(self, endpoint: str, params: Optional[Dict] = None) -> Dict[str, Any]:
        """
        Make a request to the Tradier API.
        
        Args:
            endpoint: API endpoint to call
            params: Query parameters
            
        Returns:
            API response as dictionary
            
        Raises:
            requests.RequestException: If the API request fails
        """
        url = f"{self.base_url}{endpoint}"
        
        try:
            response = requests.get(url, headers=self.headers, params=params)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            raise Exception(f"API request failed: {e}")
    
    def get_account_info(self, account_id: Optional[str] = None) -> Dict[str, Any]:
        """
        Get account information using user profile endpoint.
        
        Args:
            account_id: Specific account ID (optional, not used in this implementation)
            
        Returns:
            Account information dictionary
        """
        # Use user profile endpoint which works in sandbox
        response = self._make_request("/v1/user/profile")
        
        if 'profile' in response and 'account' in response['profile']:
            account = response['profile']['account']
            profile = response['profile']
            
            return {
                'profile_id': profile.get('id', 'N/A'),
                'profile_name': profile.get('name', 'N/A'),
                'account_number': account.get('account_number', 'N/A'),
                'account_type': account.get('type', 'N/A'),
                'classification': account.get('classification', 'N/A'),
                'day_trader': account.get('day_trader', 'N/A'),
                'option_level': account.get('option_level', 'N/A'),
                'status': account.get('status', 'N/A'),
                'date_created': account.get('date_created', 'N/A'),
                'last_update_date': account.get('last_update_date', 'N/A')
            }
        else:
            raise Exception("No account information found")
    
    def get_account_number(self) -> str:
        """
        Get the account number from the user profile.
        
        Returns:
            Account number string
        """
        account_info = self.get_account_info()
        return account_info.get('account_number', 'N/A')
    
    def get_positions(self, account_id: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        Get current positions.
        
        Args:
            account_id: Specific account ID (optional)
            
        Returns:
            List of position dictionaries
        """
        endpoint = "/v1/accounts/positions"
        if account_id:
            endpoint = f"/v1/accounts/{account_id}/positions"
        
        response = self._make_request(endpoint)
        
        if 'positions' in response and response['positions'] is not None and response['positions'] != 'null':
            positions = response['positions']['position']
            if not isinstance(positions, list):
                positions = [positions]
            return positions
        else:
            return []
    
    def get_quote(self, symbol: str) -> Dict[str, Any]:
        """
        Get quote information for a stock symbol.
        
        Args:
            symbol: Stock symbol (e.g., 'AAPL')
            
        Returns:
            Quote information dictionary
        """
        params = {'symbols': symbol}
        response = self._make_request("/v1/markets/quotes", params)
        
        if 'quotes' in response and 'quote' in response['quotes']:
            quote = response['quotes']['quote']
            if isinstance(quote, list):
                quote = quote[0]  # Use first quote if multiple
            
            return {
                'symbol': quote.get('symbol', 'N/A'),
                'description': quote.get('description', 'N/A'),
                'last': quote.get('last', 'N/A'),
                'bid': quote.get('bid', 'N/A'),
                'ask': quote.get('ask', 'N/A'),
                'volume': quote.get('volume', 'N/A'),
                'high': quote.get('high', 'N/A'),
                'low': quote.get('low', 'N/A'),
                'open': quote.get('open', 'N/A'),
                'previous_close': quote.get('prevclose', 'N/A'),
                'change': quote.get('change', 'N/A'),
                'change_percentage': quote.get('change_percentage', 'N/A'),
                'bid_size': quote.get('bidsize', 'N/A'),
                'ask_size': quote.get('asksize', 'N/A')
            }
        else:
            raise Exception(f"No quote data found for symbol: {symbol}")
    
    def get_option_chain(self, symbol: str, expiration: Optional[str] = None, 
                        strike: Optional[float] = None) -> Dict[str, Any]:
        """
        Get option chain information for a stock symbol.
        
        Args:
            symbol: Stock symbol (e.g., 'AAPL')
            expiration: Expiration date in YYYY-MM-DD format (optional)
            strike: Strike price (optional)
            
        Returns:
            Option chain information dictionary
        """
        params = {'symbol': symbol}
        if expiration:
            params['expiration'] = expiration
        if strike:
            params['strike'] = strike
        
        response = self._make_request("/v1/markets/options/chains", params)
        
        if 'options' in response:
            return response
        else:
            raise Exception(f"No option chain data found for symbol: {symbol}")
    
    def get_option_expirations(self, symbol: str) -> List[str]:
        """
        Get available expiration dates for options on a symbol.
        
        Args:
            symbol: Stock symbol
            
        Returns:
            List of expiration dates
        """
        params = {'symbol': symbol}
        response = self._make_request("/v1/markets/options/expirations", params)
        
        if 'expirations' in response and response['expirations'] is not None:
            expirations = response['expirations']['date']
            if not isinstance(expirations, list):
                expirations = [expirations]
            return expirations
        else:
            return []
    
    def get_option_strikes(self, symbol: str, expiration: str) -> List[float]:
        """
        Get available strike prices for options on a symbol and expiration.
        
        Args:
            symbol: Stock symbol
            expiration: Expiration date in YYYY-MM-DD format
            
        Returns:
            List of strike prices
        """
        params = {'symbol': symbol, 'expiration': expiration}
        response = self._make_request("/v1/markets/options/strikes", params)
        
        if 'strikes' in response and response['strikes'] is not None:
            strikes = response['strikes']['strike']
            if not isinstance(strikes, list):
                strikes = [strikes]
            return [float(strike) for strike in strikes]
        else:
            return []
    
    def get_historical_pricing(self, symbol: str, start_date: Optional[str] = None, 
                              end_date: Optional[str] = None, interval: str = 'daily') -> Dict[str, Any]:
        """
        Get historical pricing for a security (stocks or options).
        
        Args:
            symbol: Stock symbol (e.g., 'AAPL') or OCC option symbol (e.g., 'AAPL220617C00270000')
            start_date: Start date in YYYY-MM-DD format (optional)
            end_date: End date in YYYY-MM-DD format (optional)
            interval: Data interval ('daily', 'weekly', 'monthly') - default is 'daily'
            
        Returns:
            Historical pricing information dictionary
        """
        params = {'symbol': symbol, 'interval': interval}
        if start_date:
            params['start'] = start_date
        if end_date:
            params['end'] = end_date
        
        response = self._make_request("/v1/markets/history", params)
        
        if 'history' in response and response['history'] is not None:
            history_data = response['history']
            
            # Extract the day data
            if 'day' in history_data:
                days = history_data['day']
                if not isinstance(days, list):
                    days = [days]
                
                # Process and format the historical data
                formatted_days = []
                for day in days:
                    formatted_day = {
                        'date': day.get('date', 'N/A'),
                        'open': float(day.get('open', 0)) if day.get('open') else None,
                        'high': float(day.get('high', 0)) if day.get('high') else None,
                        'low': float(day.get('low', 0)) if day.get('low') else None,
                        'close': float(day.get('close', 0)) if day.get('close') else None,
                        'volume': int(day.get('volume', 0)) if day.get('volume') else None
                    }
                    formatted_days.append(formatted_day)
                
                return {
                    'symbol': symbol,
                    'interval': interval,
                    'start_date': start_date,
                    'end_date': end_date,
                    'days': formatted_days,
                    'total_days': len(formatted_days)
                }
            else:
                raise Exception(f"No historical data found for symbol: {symbol}")
        else:
            raise Exception(f"No historical data found for symbol: {symbol}")

    def get_balance(self, account_id: Optional[str] = None) -> Dict[str, Any]:
        """
        Get account balance information.
        
        Args:
            account_id: Specific account ID (optional)
            
        Returns:
            Balance information dictionary
        """
        endpoint = "/v1/accounts/balances"
        if account_id:
            endpoint = f"/v1/accounts/{account_id}/balances"
        
        response = self._make_request(endpoint)
        
        
        # The response structure might be different - check for various possible keys
        balance_data = None
        if 'balances' in response and response['balances']:
            balance_data = response['balances']
        elif 'balance' in response and response['balance']:
            balance_data = response['balance']
        else:
            
            # Try to use the response directly if it contains balance-like data
            if any(key in str(response).lower() for key in ['cash', 'equity', 'buying_power']):
                balance_data = response
            else:
                raise Exception(f"No balance information found. Response keys: {list(response.keys())}")
        
        # Handle the balance data structure
        if isinstance(balance_data, dict):
            balance = balance_data
        elif isinstance(balance_data, list) and len(balance_data) > 0:
            balance = balance_data[0]  # Use first balance if it's a list
        else:
            raise Exception(f"Unexpected balance data format: {type(balance_data)}")
        
        return {
            'total_cash': float(balance.get('total_cash', 0)),
            'cash_cash': float(balance.get('cash.cash', 0)),
            'cash_margin': float(balance.get('cash.margin', 0)),
            'cash_short': float(balance.get('cash.short', 0)),
            'total_equity': float(balance.get('total_equity', 0)),
            'long_market_value': float(balance.get('long_market_value', 0)),
            'short_market_value': float(balance.get('short_market_value', 0)),
            'buying_power': float(balance.get('buying_power', 0)),
            'day_trade_buying_power': float(balance.get('day_trade_buying_power', 0)),
            'overnight_buying_power': float(balance.get('overnight_buying_power', 0)),
            'pattern_day_trader': balance.get('pattern_day_trader', False),
            'pending_orders_count': int(balance.get('pending_orders_count', 0)),
            'cash_available': float(balance.get('cash.available', 0)),
            'cash_unsettled': float(balance.get('cash.unsettled', 0))
        }
    
    def place_option_order(self, account_id: str, option_symbol: str, side: str, 
                          quantity: float, order_type: str = 'market', 
                          price: Optional[float] = None, duration: str = 'day',
                          preview: bool = False) -> Dict[str, Any]:
        """
        Place a single option order.
        
        Args:
            account_id: Account ID
            option_symbol: OCC option symbol
            side: Order side ('buy_to_open', 'sell_to_open', 'buy_to_close', 'sell_to_close')
            quantity: Number of contracts
            order_type: Order type ('market', 'limit')
            price: Limit price (required for limit orders)
            duration: Order duration ('day', 'gtc', etc.)
            preview: If True, preview the order without executing
            
        Returns:
            Order response dictionary
        """
        endpoint = f"/v1/accounts/{account_id}/orders"
        
        # Build form parameters
        params = {
            'class': 'option',
            'option_symbol': option_symbol,
            'side': side,
            'quantity': quantity,
            'type': order_type,
            'duration': duration
        }
        
        # Add price for limit orders
        if order_type == 'limit' and price is not None:
            params['price'] = price
        
        # Add preview parameter if requested
        if preview:
            params['preview'] = 'true'
        
        # Make POST request
        url = f"{self.base_url}{endpoint}"
        
        try:
            response = requests.post(url, headers=self.headers, data=params)
            
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            # Include response body in error message for better debugging
            error_msg = f"Option order failed: {e}"
            if hasattr(e, 'response') and e.response is not None:
                try:
                    response_text = e.response.text
                    error_msg += f" | Response: {response_text}"
                except Exception:
                    pass  # Response text not available
            raise Exception(error_msg)

    def place_multileg_order(self, account_id: str, symbol: str, legs: list, 
                           order_type: str = 'market', duration: str = 'day', 
                           preview: bool = False, price: Optional[float] = None) -> Dict[str, Any]:
        """
        Place a multileg order (spread trade) or preview it.
        
        Args:
            account_id: Account ID
            symbol: Underlying symbol
            legs: List of leg dictionaries with 'side', 'quantity', 'option_symbol'
            order_type: Order type ('market', 'credit', 'debit', 'even', 'limit')
            duration: Order duration ('day', 'gtc', etc.)
            preview: If True, preview the order without executing
            price: Net price for limit orders (required for 'limit' order_type)
            
        Returns:
            Order response dictionary
        """
        endpoint = f"/v1/accounts/{account_id}/orders"
                
        # Build form parameters with indexed notation
        params = {
            'class': 'multileg',
            'symbol': symbol,
            'type': order_type,
            'duration': duration,
            'price': price
        }
                
        # Add preview parameter if requested
        if preview:
            params['preview'] = 'true'
        
        # Add leg parameters using indexed notation (side[0], quantity[0], etc.)
        for i, leg in enumerate(legs):
            params[f'side[{i}]'] = leg['side']
            params[f'quantity[{i}]'] = leg['quantity']
            params[f'option_symbol[{i}]'] = leg['option_symbol']
        
        # Make POST request
        url = f"{self.base_url}{endpoint}"
        
        try:
            response = requests.post(url, headers=self.headers, data=params)
            
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            # Include response body in error message for better debugging
            error_msg = f"Multileg order failed: {e}"
            if hasattr(e, 'response') and e.response is not None:
                try:
                    response_text = e.response.text
                    error_msg += f" | Response: {response_text}"
                except Exception:
                    pass  # Response text not available
            raise Exception(error_msg)
    
    def validate_option_symbol(self, option_symbol: str) -> bool:
        """
        Validate that an option symbol exists and is tradeable.
        
        Args:
            option_symbol: OCC option symbol to validate
            
        Returns:
            True if symbol is valid, False otherwise
        """
        try:
            # Try to get a quote for the symbol
            quote = self.get_option_quote(option_symbol)
            return quote.get('symbol') == option_symbol
        except Exception:
            return False  # Symbol doesn't exist or API error
    
    def get_option_quote(self, option_symbol: str) -> Dict[str, Any]:
        """
        Get quote information for an option symbol.
        
        Args:
            option_symbol: OCC option symbol (e.g., 'AAPL251003C00250000')
            
        Returns:
            Option quote information dictionary
        """
        params = {'symbols': option_symbol}
        response = self._make_request("/v1/markets/quotes", params)
        
        if 'quotes' in response and 'quote' in response['quotes']:
            quote = response['quotes']['quote']
            if isinstance(quote, list):
                quote = quote[0]  # Use first quote if multiple
            
            return {
                'symbol': quote.get('symbol', 'N/A'),
                'description': quote.get('description', 'N/A'),
                'last': quote.get('last', 'N/A'),
                'bid': quote.get('bid', 'N/A'),
                'ask': quote.get('ask', 'N/A'),
                'volume': quote.get('volume', 'N/A'),
                'high': quote.get('high', 'N/A'),
                'low': quote.get('low', 'N/A'),
                'open': quote.get('open', 'N/A'),
                'previous_close': quote.get('prevclose', 'N/A'),
                'change': quote.get('change', 'N/A'),
                'change_percentage': quote.get('change_percentage', 'N/A'),
                'bid_size': quote.get('bidsize', 'N/A'),
                'ask_size': quote.get('asksize', 'N/A')
            }
        else:
            raise Exception(f"No quote data found for option symbol: {option_symbol}")
    
    def get_orders(self, account_id: Optional[str] = None, include_filled: bool = True) -> List[Dict[str, Any]]:
        """
        Get orders for an account.
        
        Args:
            account_id: Specific account ID (optional)
            include_filled: Whether to include filled orders (default: True)
            
        Returns:
            List of order dictionaries
        """
        endpoint = "/v1/accounts/orders"
        if account_id:
            endpoint = f"/v1/accounts/{account_id}/orders"
        
        params = {}
        if include_filled:
            params['includeTags'] = 'true'
        
        response = self._make_request(endpoint, params)
        
        if 'orders' in response and response['orders'] is not None and response['orders'] != 'null':
            orders = response['orders']['order']
            if not isinstance(orders, list):
                orders = [orders]
            return orders
        else:
            return []

    def cancel_order(self, account_id: str, order_id: str) -> Dict[str, Any]:
        """
        Cancel an existing order.
        
        Args:
            account_id: Account ID
            order_id: Order ID to cancel
            
        Returns:
            Cancel order response dictionary
        """
        endpoint = f"/v1/accounts/{account_id}/orders/{order_id}"
        
        # Make DELETE request
        url = f"{self.base_url}{endpoint}"
        
        try:
            response = requests.delete(url, headers=self.headers)
            
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            # Include response body in error message for better debugging
            error_msg = f"Cancel order failed: {e}"
            if hasattr(e, 'response') and e.response is not None:
                try:
                    response_text = e.response.text
                    error_msg += f" | Response: {response_text}"
                except Exception:
                    pass  # Response text not available
            raise Exception(error_msg)

    def change_order(self, account_id: str, order_id: str, order_type: Optional[str] = None,
                    price: Optional[float] = None, stop: Optional[float] = None,
                    duration: Optional[str] = None, quantity: Optional[float] = None) -> Dict[str, Any]:
        """
        Change/modify an existing order.
        
        Args:
            account_id: Account ID
            order_id: Order ID to change
            order_type: New order type ('market', 'limit', 'stop', 'stop_limit')
            price: New limit price (required for limit orders)
            stop: New stop price (required for stop orders)
            duration: New order duration ('day', 'gtc', 'pre', 'post')
            quantity: New quantity
            
        Returns:
            Change order response dictionary
        """
        endpoint = f"/v1/accounts/{account_id}/orders/{order_id}"
        
        # Build form parameters for the change
        params = {}
        if order_type is not None:
            params['type'] = order_type
        if price is not None:
            params['price'] = price
        if stop is not None:
            params['stop'] = stop
        if duration is not None:
            params['duration'] = duration
        if quantity is not None:
            params['quantity'] = quantity
        
        # Make PUT request
        url = f"{self.base_url}{endpoint}"
        
        try:
            response = requests.put(url, headers=self.headers, data=params)
            
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            # Include response body in error message for better debugging
            error_msg = f"Change order failed: {e}"
            if hasattr(e, 'response') and e.response is not None:
                try:
                    response_text = e.response.text
                    error_msg += f" | Response: {response_text}"
                except Exception:
                    pass  # Response text not available
            raise Exception(error_msg)

    def get_account_history(self, account_id: Optional[str] = None, limit: Optional[int] = None, 
                           page: Optional[int] = None, start_date: Optional[str] = None, 
                           end_date: Optional[str] = None, type_filter: Optional[str] = None) -> Dict[str, Any]:
        """
        Get historical activity for an account.
        
        Args:
            account_id: Specific account ID (optional)
            limit: Number of records to return (optional)
            page: Page number for pagination (optional)
            start_date: Start date in YYYY-MM-DD format (optional)
            end_date: End date in YYYY-MM-DD format (optional)
            type_filter: Filter by transaction type (optional)
            
        Returns:
            Account history information dictionary
        """
        endpoint = "/v1/accounts/history"
        if account_id:
            endpoint = f"/v1/accounts/{account_id}/history"
        
        # Build query parameters
        params = {}
        if limit is not None:
            params['limit'] = limit
        if page is not None:
            params['page'] = page
        if start_date is not None:
            params['start'] = start_date
        if end_date is not None:
            params['end'] = end_date
        if type_filter is not None:
            params['type'] = type_filter
        
        response = self._make_request(endpoint, params)
        
        # Process the response to extract history data
        if 'history' in response and response['history'] is not None:
            history_data = response['history']
            
            # Extract events if they exist
            events = []
            if 'event' in history_data:
                event_list = history_data['event']
                if not isinstance(event_list, list):
                    event_list = [event_list]
                
                # Process and format the historical events
                for event in event_list:
                    formatted_event = {
                        'date': event.get('date', 'N/A'),
                        'type': event.get('type', 'N/A'),
                        'amount': float(event.get('amount', 0)) if event.get('amount') else None,
                        'quantity': float(event.get('quantity', 0)) if event.get('quantity') else None,
                        'price': float(event.get('price', 0)) if event.get('price') else None,
                        'symbol': event.get('symbol', 'N/A'),
                        'description': event.get('description', 'N/A'),
                        'transaction_date': event.get('transaction_date', 'N/A'),
                        'trade_date': event.get('trade_date', 'N/A'),
                        'settlement_date': event.get('settlement_date', 'N/A'),
                        'commission': float(event.get('commission', 0)) if event.get('commission') else None,
                        'fees': float(event.get('fees', 0)) if event.get('fees') else None
                    }
                    events.append(formatted_event)
            
            return {
                'account_id': account_id,
                'start_date': start_date,
                'end_date': end_date,
                'type_filter': type_filter,
                'events': events,
                'total_events': len(events),
                'raw_response': history_data
            }
        else:
            return {
                'account_id': account_id,
                'start_date': start_date,
                'end_date': end_date,
                'type_filter': type_filter,
                'events': [],
                'total_events': 0,
                'raw_response': {}
            }