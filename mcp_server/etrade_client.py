"""
E*TRADE API Client
Handles all API interactions with the E*TRADE trading platform.
"""

import os
import json
import logging
import random
from typing import Dict, List, Optional, Any
from rauth import OAuth1Service
from mcp_server.trading_platform_interface import TradingPlatformInterface
from mcp_server.error_handling import TradingError, ErrorCode

logger = logging.getLogger("etrade_client")


class EtradeClient(TradingPlatformInterface):
    """Client for interacting with the E*TRADE API."""
    
    def __init__(self, consumer_key: str, consumer_secret: str, 
                 access_token: str, access_token_secret: str,
                 base_url: str = "https://api.etrade.com"):
        """
        Initialize the E*TRADE client.
        
        Args:
            consumer_key: E*TRADE consumer key
            consumer_secret: E*TRADE consumer secret
            access_token: OAuth access token
            access_token_secret: OAuth access token secret
            base_url: Base URL for the API (e.g., 'https://api.etrade.com' or 'https://apisb.etrade.com')
        """
        self.consumer_key = consumer_key
        self.consumer_secret = consumer_secret
        self.access_token = access_token
        self.access_token_secret = access_token_secret
        self.base_url = base_url
        self._session = None
        self._accounts_cache: Optional[List[Dict[str, Any]]] = None
        
        logger.info(f"Initialized EtradeClient with base_url: {base_url}")

    def _create_session(self):
        """Create OAuth1 session for E*TRADE"""
        if self._session is None:
            logger.debug(f"Creating OAuth1 session with base_url: {self.base_url}")
            logger.debug(f"Consumer key: {self.consumer_key[:10]}...")
            logger.debug(f"Access token: {self.access_token[:10]}...")
            
            etrade = OAuth1Service(
                name="etrade",
                consumer_key=self.consumer_key,
                consumer_secret=self.consumer_secret,
                request_token_url=f"{self.base_url}/oauth/request_token",
                access_token_url=f"{self.base_url}/oauth/access_token",
                authorize_url="https://us.etrade.com/e/t/etws/authorize?key={}&token={}",
                base_url=self.base_url
            )
            
            # Create session with existing access tokens
            self._session = etrade.get_session(
                (self.access_token, self.access_token_secret)
            )
            
            logger.debug(f"Successfully created E*TRADE OAuth1 session")
        return self._session

    def _make_request(self, endpoint: str, method: str = 'GET', 
                      params: Optional[Dict] = None, 
                      data: Optional[str] = None,
                      headers: Optional[Dict] = None) -> Dict[str, Any]:
        """Make authenticated API request to E*TRADE"""
        session = self._create_session()
        url = f"{self.base_url}{endpoint}"
        
        # Use existing E*TRADE header patterns (as per original client)
        request_headers = {"consumerkey": self.consumer_key}
        if headers:
            request_headers.update(headers)
        
        logger.debug(f"Making {method} request to {url} with headers: {request_headers}")
        
        try:
            if method.upper() == 'GET':
                # Only pass params if they exist (rauth doesn't like None)
                if params:
                    response = session.get(url, header_auth=True, params=params, headers=request_headers)
                else:
                    response = session.get(url, header_auth=True, headers=request_headers)
            elif method.upper() == 'POST':
                response = session.post(url, header_auth=True, data=data, headers=request_headers)
            elif method.upper() == 'PUT':
                response = session.put(url, header_auth=True, data=data, headers=request_headers)
            elif method.upper() == 'DELETE':
                response = session.delete(url, header_auth=True, headers=request_headers)
            else:
                raise ValueError(f"Unsupported HTTP method: {method}")
            
            # Handle response using existing E*TRADE patterns
            if response.status_code == 200:
                logger.debug(f"E*TRADE API success - Status: {response.status_code}")
                logger.debug(f"Response headers: {dict(response.headers)}")
                logger.debug(f"Response text (first 500 chars): {response.text[:500]}")
                
                try:
                    json_response = response.json()
                    logger.debug(f"Parsed JSON response: {json_response}")
                    return json_response
                except json.JSONDecodeError as e:
                    logger.error(f"Failed to parse JSON response: {e}")
                    logger.error(f"Full response text: {response.text}")
                    raise TradingError(
                        f"E*TRADE API returned invalid JSON: {str(e)}",
                        ErrorCode.TRADING_PLATFORM_ERROR,
                        details={"response_text": response.text}
                    )
            elif response.status_code == 204:
                return {}  # No content
            else:
                # Log the full response for debugging
                logger.error(f"E*TRADE API error - Status: {response.status_code}, Headers: {dict(response.headers)}")
                logger.error(f"Response text: {response.text}")
                
                # Handle errors using existing E*TRADE patterns
                if response.headers.get('Content-Type') == 'application/json':
                    try:
                        error_data = response.json()
                        if 'Error' in error_data and 'message' in error_data['Error']:
                            raise TradingError(
                                f"E*TRADE API error: {error_data['Error']['message']}",
                                ErrorCode.TRADING_PLATFORM_ERROR,
                                details={"status_code": response.status_code, "response": error_data}
                            )
                    except json.JSONDecodeError:
                        pass
                
                raise TradingError(
                    f"E*TRADE API request failed with status {response.status_code}: {response.text}",
                    ErrorCode.TRADING_PLATFORM_ERROR,
                    details={"status_code": response.status_code, "response_text": response.text}
                )
                
        except TradingError:
            raise
        except Exception as e:
            logger.error(f"E*TRADE API request failed: {e}")
            raise TradingError(
                f"E*TRADE API request failed: {str(e)}",
                ErrorCode.TRADING_PLATFORM_ERROR,
                details={"error": str(e)}
            )

    def _resolve_account_id(self, account_id: str) -> str:
        """
        Resolve and validate account ID, supporting both accountId and accountIdKey.
        
        Args:
            account_id: Account ID (required - either accountId or accountIdKey)
        
        Returns:
            accountIdKey (the key used for API calls)
        
        Raises:
            ValueError: If account_id is not found
        """
        logger.debug(f"Resolving account_id: {account_id}")
        
        # Validate account exists and return accountIdKey
        accounts = self.list_all_accounts()
        for account in accounts:
            # Support both accountId and accountIdKey for user convenience
            if account['accountId'] == account_id or account['accountIdKey'] == account_id:
                logger.debug(f"Found matching account: {account['accountId']} ({account['accountDesc']})")
                return account['accountIdKey']  # Always use accountIdKey for API calls
        
        # Account not found
        available_ids = [acc['accountId'] for acc in accounts]
        raise ValueError(f"Account ID '{account_id}' not found. Available account IDs: {available_ids}")


    def get_account_info(self, account_id: str) -> Dict[str, Any]:
        """
        Get account information from E*TRADE.
        
        Args:
            account_id: Account ID (required - either accountId or accountIdKey)
        
        Returns:
            Account information dictionary
        """
        try:
            logger.info(f"Getting account info for account_id: {account_id}")
            
            # Get all accounts
            accounts = self.list_all_accounts()
            if not accounts:
                logger.warning("No accounts found in E*TRADE")
                raise ValueError("No accounts found in E*TRADE")
            
            # Find the specific account
            for account in accounts:
                if account['accountId'] == account_id or account['accountIdKey'] == account_id:
                    logger.info(f"Found requested account: {account['accountId']} ({account['accountDesc']})")
                    return self._format_account_info(account)
            
            # Account not found
            available_ids = [acc['accountId'] for acc in accounts]
            raise ValueError(f"Account ID '{account_id}' not found. Available account IDs: {available_ids}")
            
        except TradingError:
            raise
        except Exception as e:
            logger.error(f"Failed to get account info from E*TRADE: {e}")
            raise TradingError(
                f"Failed to get account info from E*TRADE: {str(e)}",
                ErrorCode.TRADING_PLATFORM_ERROR,
                details={"error": str(e)}
            )

    @property
    def accounts(self) -> List[Dict[str, Any]]:
        """
        Get list of available accounts (lazy-loaded and cached).
        
        Returns:
            List of account dictionaries with standardized format
        """
        if self._accounts_cache is None:
            logger.debug("Lazy-loading accounts (first access)")
            self._accounts_cache = self.list_accounts()
        return self._accounts_cache
    
    def get_account_number(self) -> str:
        """Get the primary account number (first active brokerage account)"""
        try:
            accounts = self.list_all_accounts()
            if not accounts:
                return 'N/A'
            
            # Find first active brokerage account
            for account in accounts:
                if (account.get('institutionType') == 'BROKERAGE' and 
                    account.get('accountStatus') != 'CLOSED'):
                    return account.get('accountIdKey', 'N/A')
            
            # If no brokerage account, return first account
            return accounts[0].get('accountIdKey', 'N/A')
            
        except Exception as e:
            logger.error(f"Failed to get account number: {e}")
            return 'N/A'

    def list_accounts(self) -> List[Dict[str, Any]]:
        """
        List all available accounts for the authenticated user.
        
        Returns:
            List of account dictionaries with standardized format
        """
        raw_accounts = self.list_all_accounts()
        
        # Convert to standardized format
        standardized_accounts = []
        for account in raw_accounts:
            standardized_accounts.append({
                'account_id': account.get('accountId', 'N/A'),
                'account_number': account.get('accountIdKey', 'N/A'),
                'description': account.get('accountDesc', 'N/A'),
                'type': account.get('accountType', 'N/A'),
                'status': account.get('accountStatus', 'N/A'),
                'institution_type': account.get('institutionType', 'N/A'),
                'account_mode': account.get('accountMode', 'N/A')
            })
        
        return standardized_accounts
    
    def list_all_accounts(self) -> List[Dict[str, Any]]:
        """List all available accounts with their details (E*TRADE raw format)"""
        try:
            logger.info("Fetching all accounts from E*TRADE")
            response = self._make_request("/v1/accounts/list.json")
            
            if not response:
                logger.warning("E*TRADE API returned empty response for account list")
                return []
            
            accounts = []
            if isinstance(response, dict) and "AccountListResponse" in response:
                account_list_response = response["AccountListResponse"]
                if isinstance(account_list_response, dict) and "Accounts" in account_list_response:
                    accounts_data = account_list_response["Accounts"]
                    if isinstance(accounts_data, dict) and "Account" in accounts_data:
                        account_list = accounts_data["Account"]
                        if not isinstance(account_list, list):
                            account_list = [account_list]
                        
                        for account in account_list:
                            if isinstance(account, dict):
                                accounts.append({
                                    'accountId': account.get('accountId', 'N/A'),
                                    'accountIdKey': account.get('accountIdKey', 'N/A'),
                                    'accountDesc': account.get('accountDesc', 'N/A'),
                                    'accountType': account.get('accountType', 'N/A'),
                                    'institutionType': account.get('institutionType', 'N/A'),
                                    'accountStatus': account.get('accountStatus', 'N/A'),
                                    'accountMode': account.get('accountMode', 'N/A')
                                })
            
            logger.info(f"Found {len(accounts)} accounts")
            return accounts
            
        except Exception as e:
            logger.error(f"Failed to list accounts from E*TRADE: {e}")
            raise TradingError(
                f"Failed to list accounts from E*TRADE: {str(e)}",
                ErrorCode.TRADING_PLATFORM_ERROR,
                details={"error": str(e)}
            )

    def get_positions(self, account_id: str, **options) -> Any:
        """
        Get positions from E*TRADE with full API support.
        
        E*TRADE API documentation: https://apisb.etrade.com/docs/api/account/api-portfolio-v1.html
        
        Args:
            account_id: Account ID (required - either accountId or accountIdKey)
            **options: E*TRADE-specific options:
                - count (int): Number of positions to return (default: 50, E*TRADE API default)
                - view (str): Detail level for position data:
                    * 'QUICK': Basic position info with quick view data (default)
                    * 'PERFORMANCE': Performance metrics and gains
                    * 'FUNDAMENTAL': Fundamental data (P/E, EPS, dividends, market cap)
                    * 'OPTIONSWATCH': Options data with Greeks (delta, gamma, theta, vega, rho, IV)
                    * 'COMPLETE': All available data
                - sort_by (str): Field to sort positions by. Supported values:
                    * 'SYMBOL', 'TYPE_NAME', 'EXCHANGE_NAME', 'QUANTITY', 'MARKET_VALUE',
                    * 'TOTAL_GAIN', 'TOTAL_GAIN_PCT', 'PRICE_CHANGE', 'VOLUME', etc.
                    * See E*TRADE API docs for complete list
                - sort_order (str): Sort direction - 'ASC' or 'DESC' (default: 'DESC')
                - page_number (int): Specific page number for pagination (default: 1)
                - market_session (str): Market session - 'REGULAR' or 'EXTENDED' (default: 'REGULAR')
                - totals_required (bool): Include portfolio totals summary (default: False)
                - lots_required (bool): Include detailed position lots (default: False)
        
        Returns:
            - If totals_required=False and no pagination: List[Dict] of positions
            - If totals_required=True or pagination: Dict with 'positions', 'totals', 'pagination'
        
        Examples:
            # Basic positions
            positions = client.get_positions(account_id="12345")
            
            # Options with Greeks
            positions = client.get_positions(account_id="12345", view="OPTIONSWATCH", count=100)
            
            # Complete portfolio analysis
            result = client.get_positions(
                account_id="12345",
                view="COMPLETE",
                totals_required=True,
                sort_by="MARKET_VALUE",
                sort_order="DESC"
            )
        """
        try:
            logger.info(f"Getting positions for account_id: {account_id}")
            account_to_use = self._resolve_account_id(account_id)
            logger.info(f"Resolved account_id to: {account_to_use}")
            
            # Extract options with defaults
            count = options.get('count')
            view = options.get('view')
            sort_by = options.get('sort_by')
            sort_order = options.get('sort_order')
            page_number = options.get('page_number')
            market_session = options.get('market_session')
            totals_required = options.get('totals_required', False)
            lots_required = options.get('lots_required', False)
            
            # Build query parameters according to E*TRADE API spec
            params = {}
            if count is not None:
                params['count'] = count
            if sort_by:
                params['sortBy'] = sort_by
            if sort_order:
                params['sortOrder'] = sort_order
            if page_number is not None:
                params['pageNumber'] = page_number
            if market_session:
                params['marketSession'] = market_session
            if totals_required:
                params['totalsRequired'] = 'true'
            if lots_required:
                params['lotsRequired'] = 'true'
            if view:
                # Validate view parameter
                valid_views = ['PERFORMANCE', 'FUNDAMENTAL', 'OPTIONSWATCH', 'QUICK', 'COMPLETE']
                if view.upper() in valid_views:
                    params['view'] = view.upper()
                else:
                    logger.warning(f"Invalid view '{view}', must be one of {valid_views}. Using default.")
            
            # Use portfolio endpoint with parameters
            endpoint = f"/v1/accounts/{account_to_use}/portfolio.json"
            logger.info(f"Making request to endpoint: {endpoint} with params: {params}")
            response = self._make_request(endpoint, params=params)
            
            # Add null checking and better error handling
            if not response:
                logger.warning("E*TRADE API returned empty response for positions")
                return []
            
            logger.debug(f"E*TRADE positions response: {response}")
            
            result = {
                'positions': [],
                'totals': None,
                'pagination': None
            }
            
            if isinstance(response, dict) and "PortfolioResponse" in response:
                portfolio_response = response["PortfolioResponse"]
                if isinstance(portfolio_response, dict) and "AccountPortfolio" in portfolio_response:
                    account_portfolio = portfolio_response["AccountPortfolio"]
                    
                    # Handle both single account and multiple accounts
                    if isinstance(account_portfolio, list):
                        portfolio_list = account_portfolio
                    else:
                        portfolio_list = [account_portfolio]
                    
                    for acct_portfolio in portfolio_list:
                        if isinstance(acct_portfolio, dict):
                            # Extract positions
                            if "Position" in acct_portfolio:
                                position_data = acct_portfolio["Position"]
                                # Handle both single position and multiple positions
                                if isinstance(position_data, list):
                                    position_list = position_data
                                else:
                                    position_list = [position_data]
                                
                                for position in position_list:
                                    if isinstance(position, dict):
                                        formatted_position = self._format_position_response(position, view)
                                        result['positions'].append(formatted_position)
                            
                            # Extract totals if requested
                            if totals_required and "Totals" in acct_portfolio:
                                result['totals'] = self._format_totals_response(acct_portfolio["Totals"])
                            
                            # Extract pagination info
                            if "totalPages" in acct_portfolio:
                                result['pagination'] = {
                                    'total_pages': acct_portfolio.get('totalPages', 1),
                                    'current_page': page_number or 1
                                }
                    
                    # For backwards compatibility, return just positions list if no special features requested
                    if not totals_required and not result['pagination']:
                        return result['positions']
                    
                    # Otherwise return full result with metadata
                    return result
            
            logger.warning(f"Unexpected E*TRADE positions response structure: {response}")
            return []
            
        except TradingError:
            raise
        except Exception as e:
            logger.error(f"Failed to get positions from E*TRADE: {e}")
            raise TradingError(
                f"Failed to get positions from E*TRADE: {str(e)}",
                ErrorCode.TRADING_PLATFORM_ERROR,
                details={"error": str(e)}
            )

    def get_quote(self, symbol: str) -> Dict[str, Any]:
        """Get quote from E*TRADE"""
        try:
            # Use existing quotes endpoint
            response = self._make_request(f"/v1/market/quote/{symbol}.json")
            
            if "QuoteResponse" in response and "QuoteData" in response["QuoteResponse"]:
                quote_data = response["QuoteResponse"]["QuoteData"]
                if isinstance(quote_data, list):
                    quote_data = quote_data[0]
                return self._format_quote_response(quote_data)
            
            raise Exception(f"No quote data found for symbol: {symbol}")
            
        except Exception as e:
            logger.error(f"Failed to get quote from E*TRADE: {e}")
            raise

    def get_balance(self, account_id: str) -> Dict[str, Any]:
        """
        Get account balance from E*TRADE.
        
        Args:
            account_id: Account ID (required - either accountId or accountIdKey)
        
        Returns:
            Account balance dictionary
        """
        try:
            account_to_use = self._resolve_account_id(account_id)
            
            # Use existing balance endpoint with existing parameters
            params = {"instType": "BROKERAGE", "realTimeNAV": "true"}
            response = self._make_request(f"/v1/accounts/{account_to_use}/balance.json", params=params)
            
            if "BalanceResponse" in response:
                return self._format_balance_response(response["BalanceResponse"])
            
            return {}
            
        except TradingError:
            raise
        except Exception as e:
            logger.error(f"Failed to get balance from E*TRADE: {e}")
            raise TradingError(
                f"Failed to get balance from E*TRADE: {str(e)}",
                ErrorCode.TRADING_PLATFORM_ERROR,
                details={"error": str(e)}
            )

    def get_orders(self, account_id: Optional[str] = None, include_filled: bool = True) -> List[Dict[str, Any]]:
        """Get orders from E*TRADE"""
        try:
            account_to_use = self._resolve_account_id(account_id)
            
            # Use existing orders endpoint with existing status patterns
            all_orders = []
            statuses = ["OPEN", "EXECUTED", "INDIVIDUAL_FILLS", "CANCELLED", "REJECTED", "EXPIRED"]
            
            for status in statuses:
                if not include_filled and status in ["EXECUTED", "INDIVIDUAL_FILLS"]:
                    continue
                    
                params = {"status": status}
                response = self._make_request(f"/v1/accounts/{account_to_use}/orders.json", params=params)
                
                if "OrdersResponse" in response and "Order" in response["OrdersResponse"]:
                    orders = response["OrdersResponse"]["Order"]
                    if not isinstance(orders, list):
                        orders = [orders]
                    
                    for order in orders:
                        formatted_order = self._format_order_response(order, status)
                        all_orders.append(formatted_order)
            
            return all_orders
            
        except TradingError:
            raise
        except Exception as e:
            logger.error(f"Failed to get orders from E*TRADE: {e}")
            raise TradingError(
                f"Failed to get orders from E*TRADE: {str(e)}",
                ErrorCode.TRADING_PLATFORM_ERROR,
                details={"error": str(e)}
            )

    def cancel_order(self, account_id: str, order_id: str) -> Dict[str, Any]:
        """Cancel order using existing E*TRADE patterns"""
        try:
            # Use existing cancel order endpoint with existing XML pattern
            url = f"/v1/accounts/{account_id}/orders/cancel.json"
            headers = {"Content-Type": "application/xml"}
            
            # Use existing XML payload pattern
            xml_payload = f"""<CancelOrderRequest>
                                <orderId>{order_id}</orderId>
                            </CancelOrderRequest>"""
            
            response = self._make_request(url, method='PUT', data=xml_payload, headers=headers)
            
            if "CancelOrderResponse" in response and "orderId" in response["CancelOrderResponse"]:
                return {"status": "success", "message": f"Order {order_id} cancelled"}
            
            return {"status": "error", "message": "Failed to cancel order"}
            
        except TradingError:
            raise
        except Exception as e:
            logger.error(f"Failed to cancel order from E*TRADE: {e}")
            raise TradingError(
                f"Failed to cancel order from E*TRADE: {str(e)}",
                ErrorCode.TRADING_PLATFORM_ERROR,
                details={"error": str(e)}
            )

    def change_order(self, account_id: str, order_id: str, order_type: Optional[str] = None,
                    price: Optional[float] = None, stop: Optional[float] = None,
                    duration: Optional[str] = None, quantity: Optional[float] = None) -> Dict[str, Any]:
        """Modify an existing order"""
        try:
            # E*TRADE doesn't support order modification directly
            # This would need to be implemented by canceling and recreating
            raise TradingError(
                "E*TRADE does not support order modification. Please cancel and recreate the order.",
                ErrorCode.TRADING_PLATFORM_ERROR,
                details={"platform": "etrade", "operation": "change_order"}
            )
        except TradingError:
            raise
        except Exception as e:
            logger.error(f"Failed to change order from E*TRADE: {e}")
            raise TradingError(
                f"Failed to change order from E*TRADE: {str(e)}",
                ErrorCode.TRADING_PLATFORM_ERROR,
                details={"error": str(e)}
            )

    def get_account_history(self, account_id: Optional[str] = None, limit: Optional[int] = None,
                           start_date: Optional[str] = None, end_date: Optional[str] = None) -> List[Dict[str, Any]]:
        """Get account transaction history from E*TRADE"""
        try:
            account_to_use = self._resolve_account_id(account_id)
            
            # Use existing transactions endpoint
            params = {}
            if limit:
                params["count"] = limit
            if start_date:
                params["startDate"] = start_date
            if end_date:
                params["endDate"] = end_date
            
            response = self._make_request(f"/v1/accounts/{account_to_use}/transactions.json", params=params)
            
            if "TransactionListResponse" in response and "Transaction" in response["TransactionListResponse"]:
                transactions = response["TransactionListResponse"]["Transaction"]
                if not isinstance(transactions, list):
                    transactions = [transactions]
                
                formatted_transactions = []
                for transaction in transactions:
                    formatted_transaction = self._format_transaction_response(transaction)
                    formatted_transactions.append(formatted_transaction)
                
                return formatted_transactions
            
            return []
            
        except TradingError:
            raise
        except Exception as e:
            logger.error(f"Failed to get account history from E*TRADE: {e}")
            raise TradingError(
                f"Failed to get account history from E*TRADE: {str(e)}",
                ErrorCode.TRADING_PLATFORM_ERROR,
                details={"error": str(e)}
            )

    def place_multileg_order(self, account_id: str, symbol: str, legs: list, 
                           order_type: str = 'market', duration: str = 'day', session: str = 'normal',
                           preview: bool = False, price: Optional[float] = None) -> Dict[str, Any]:
        """Place multileg order using existing E*TRADE patterns"""
        try:
            # Use existing preview/place endpoint pattern
            if preview:
                url = f"/v1/accounts/{account_id}/orders/preview.json"
            else:
                url = f"/v1/accounts/{account_id}/orders/place.json"
            
            headers = {"Content-Type": "application/xml"}
            
            # Build XML payload using existing pattern but extend for multileg
            xml_payload = self._build_multileg_xml_payload(legs, order_type, duration, price)
            
            response = self._make_request(url, method='POST', data=xml_payload, headers=headers)
            return response
            
        except TradingError:
            raise
        except Exception as e:
            logger.error(f"Failed to place multileg order from E*TRADE: {e}")
            raise TradingError(
                f"Failed to place multileg order from E*TRADE: {str(e)}",
                ErrorCode.TRADING_PLATFORM_ERROR,
                details={"error": str(e)}
            )

    def _build_multileg_xml_payload(self, legs: list, order_type: str, 
                                    duration: str, price: Optional[float]) -> str:
        """Build XML payload for multileg orders using existing pattern"""
        # Extend existing XML template pattern
        xml_template = """<PreviewOrderRequest>
            <orderType>MULTILEG</orderType>
            <clientOrderId>{client_order_id}</clientOrderId>
            <Order>
                <allOrNone>false</allOrNone>
                <priceType>{price_type}</priceType>
                <orderTerm>{duration}</orderTerm>
                <marketSession>REGULAR</marketSession>
                <stopPrice></stopPrice>
                <limitPrice>{limit_price}</limitPrice>
                {instruments}
            </Order>
        </PreviewOrderRequest>"""
        
        # Build instruments section
        instruments_xml = ""
        for leg in legs:
            instruments_xml += f"""
            <Instrument>
                <Product>
                    <securityType>OPTN</securityType>
                    <symbol>{leg['option_symbol']}</symbol>
                </Product>
                <orderAction>{leg['side']}</orderAction>
                <quantityType>QUANTITY</quantityType>
                <quantity>{leg['quantity']}</quantity>
            </Instrument>"""
        
        return xml_template.format(
            client_order_id=random.randint(1000000000, 9999999999),
            price_type=order_type,
            duration=duration,
            limit_price=price or "",
            instruments=instruments_xml
        )

    # Response formatting methods
    def _format_account_info(self, account: Dict[str, Any]) -> Dict[str, Any]:
        """Format E*TRADE account response to standard format"""
        return {
            'account_id': account.get('accountId', 'N/A'),
            'account_number': account.get('accountIdKey', 'N/A'),
            'type': account.get('institutionType', 'N/A'),
            'is_day_trader': account.get('dayTrader', False),
            'is_closing_only': account.get('closingOnly', False),
            'status': account.get('accountStatus', 'N/A'),
            'description': account.get('accountDesc', 'N/A')
        }

    def _format_balance_response(self, balance_data: Dict[str, Any]) -> Dict[str, Any]:
        """Format E*TRADE balance response to standard format"""
        computed = balance_data.get("Computed", {})
        real_time = computed.get("RealTimeValues", {})
        
        return {
            'total_cash': float(real_time.get('totalAccountValue', 0)),
            'cash_available': float(computed.get('cashBuyingPower', 0)),
            'cash_unsettled': float(computed.get('unsettledCash', 0)),
            'total_equity': float(real_time.get('totalAccountValue', 0)),
            'long_market_value': float(computed.get('longMarketValue', 0)),
            'short_market_value': float(computed.get('shortMarketValue', 0)),
            'buying_power': float(computed.get('marginBuyingPower', 0)),
            'day_trade_buying_power': float(computed.get('dayTradingBuyingPower', 0)),
            'maintenance_requirement': float(computed.get('maintenanceRequirement', 0))
        }

    def _format_quote_response(self, quote: Dict[str, Any]) -> Dict[str, Any]:
        """Format E*TRADE quote response to standard format"""
        product = quote.get("Product", {})
        all_data = quote.get("All", {})
        
        return {
            'symbol': product.get('symbol', 'N/A'),
            'description': product.get('companyName', 'N/A'),
            'last': all_data.get('lastTrade', 'N/A'),
            'bid': all_data.get('bid', 'N/A'),
            'ask': all_data.get('ask', 'N/A'),
            'volume': all_data.get('totalVolume', 'N/A'),
            'high': all_data.get('high', 'N/A'),
            'low': all_data.get('low', 'N/A'),
            'open': all_data.get('open', 'N/A'),
            'previous_close': all_data.get('previousClose', 'N/A'),
            'change': all_data.get('changeClose', 'N/A'),
            'change_percentage': all_data.get('changeClosePercentage', 'N/A'),
            'bid_size': all_data.get('bidSize', 'N/A'),
            'ask_size': all_data.get('askSize', 'N/A')
        }

    def _format_position_response(self, position: Dict[str, Any], view: Optional[str] = None) -> Dict[str, Any]:
        """
        Format E*TRADE position response to standard format.
        
        Supports different views as per E*TRADE API:
        - QUICK: Basic position info with quick view data
        - PERFORMANCE: Performance metrics
        - FUNDAMENTAL: Fundamental data
        - OPTIONSWATCH: Options-specific data (Greeks, etc.)
        - COMPLETE: All available data
        """
        # Base position data (always included)
        product = position.get('Product', {})
        formatted = {
            'position_id': position.get('positionId', 'N/A'),
            'symbol': position.get('symbolDescription', 'N/A'),
            'description': position.get('symbolDescription', 'N/A'),
            'quantity': position.get('quantity', 0),
            'position_type': position.get('positionType', 'N/A'),  # LONG or SHORT
            'date_acquired': position.get('dateAcquired', 'N/A'),
            'price_paid': position.get('pricePaid', 0),
            'commissions': position.get('commissions', 0),
            'other_fees': position.get('otherFees', 0),
            'market_value': position.get('marketValue', 0),
            'total_cost': position.get('totalCost', 0),
            'total_gain': position.get('totalGain', 0),
            'total_gain_pct': position.get('totalGainPct', 0),
            'days_gain': position.get('daysGain', 0),
            'days_gain_pct': position.get('daysGainPct', 0),
            'pct_of_portfolio': position.get('pctOfPortfolio', 0),
            'cost_per_share': position.get('costPerShare', 0),
        }
        
        # Add product details
        if product:
            formatted['product'] = {
                'symbol': product.get('symbol', 'N/A'),
                'security_type': product.get('securityType', 'N/A'),
                'security_sub_type': product.get('securitySubType', 'N/A'),
                'call_put': product.get('callPut', 'N/A'),
                'expiry_year': product.get('expiryYear', 0),
                'expiry_month': product.get('expiryMonth', 0),
                'expiry_day': product.get('expiryDay', 0),
                'strike_price': product.get('strikePrice', 0),
            }
        
        # Add Quick view data (basic quote info)
        if 'Quick' in position or 'quick' in position:
            quick = position.get('Quick', position.get('quick', {}))
            formatted['quick'] = {
                'last_trade': quick.get('lastTrade', 0),
                'last_trade_time': quick.get('lastTradeTime', 'N/A'),
                'change': quick.get('change', 0),
                'change_pct': quick.get('changePct', 0),
                'volume': quick.get('volume', 0),
                'quote_status': quick.get('quoteStatus', 'N/A'),
            }
            # Backwards compatibility
            formatted['last_price'] = quick.get('lastTrade', 0)
            formatted['cost_basis'] = position.get('pricePaid', 0)
            formatted['gain_loss'] = position.get('totalGain', 0)
            formatted['type'] = product.get('securityType', 'N/A')
        
        # Add Performance view data
        if 'Performance' in position or 'performance' in position:
            perf = position.get('Performance', position.get('performance', {}))
            formatted['performance'] = {
                'change': perf.get('change', 0),
                'change_pct': perf.get('changePct', 0),
                'last_trade': perf.get('lastTrade', 0),
                'days_gain': perf.get('daysGain', 0),
                'total_gain': perf.get('totalGain', 0),
                'total_gain_pct': perf.get('totalGainPct', 0),
                'market_value': perf.get('marketValue', 0),
                'quote_status': perf.get('quoteStatus', 'N/A'),
            }
        
        # Add Fundamental view data
        if 'Fundamental' in position or 'fundamental' in position:
            fund = position.get('Fundamental', position.get('fundamental', {}))
            formatted['fundamental'] = {
                'last_trade': fund.get('lastTrade', 0),
                'last_trade_time': fund.get('lastTradeTime', 'N/A'),
                'change': fund.get('change', 0),
                'change_pct': fund.get('changePct', 0),
                'pe_ratio': fund.get('peRatio', 0),
                'eps': fund.get('eps', 0),
                'dividend': fund.get('dividend', 0),
                'div_yield': fund.get('divYield', 0),
                'market_cap': fund.get('marketCap', 0),
                'week_52_high': fund.get('week52High', 0),
                'week_52_low': fund.get('week52Low', 0),
                'quote_status': fund.get('quoteStatus', 'N/A'),
            }
        
        # Add OptionsWatch view data (important for options positions)
        if 'OptionsWatch' in position or 'optionsWatch' in position:
            opts = position.get('OptionsWatch', position.get('optionsWatch', {}))
            formatted['options_watch'] = {
                'last_trade': opts.get('lastTrade', 0),
                'bid': opts.get('bid', 0),
                'ask': opts.get('ask', 0),
                'bid_ask_spread': opts.get('bidAskSpread', 0),
                'intrinsic_value': opts.get('intrinsicValue', 0),
                'time_value': opts.get('timeValue', 0),
                'open_interest': opts.get('openInterest', 0),
                'volume': opts.get('volume', 0),
                # Greeks
                'delta': opts.get('delta', 0),
                'gamma': opts.get('gamma', 0),
                'theta': opts.get('theta', 0),
                'vega': opts.get('vega', 0),
                'rho': opts.get('rho', 0),
                'iv_pct': opts.get('ivPct', 0),  # Implied Volatility percentage
                'days_to_expiration': opts.get('daysToExpiration', 0),
                'quote_status': opts.get('quoteStatus', 'N/A'),
            }
        
        # Add Complete view data (all fields)
        if 'Complete' in position or 'complete' in position:
            comp = position.get('Complete', position.get('complete', {}))
            formatted['complete'] = comp  # Include all complete view data
        
        # Add position lots if available
        if 'positionLot' in position:
            lots = position.get('positionLot', [])
            if not isinstance(lots, list):
                lots = [lots]
            formatted['position_lots'] = []
            for lot in lots:
                formatted['position_lots'].append({
                    'position_lot_id': lot.get('positionLotId', 'N/A'),
                    'price': lot.get('price', 0),
                    'remaining_qty': lot.get('remainingQty', 0),
                    'available_qty': lot.get('availableQty', 0),
                    'original_qty': lot.get('originalQty', 0),
                    'acquired_date': lot.get('acquiredDate', 'N/A'),
                    'days_gain': lot.get('daysGain', 0),
                    'days_gain_pct': lot.get('daysGainPct', 0),
                    'market_value': lot.get('marketValue', 0),
                    'total_cost': lot.get('totalCost', 0),
                    'total_gain': lot.get('totalGain', 0),
                })
        
        return formatted
    
    def _format_totals_response(self, totals: Dict[str, Any]) -> Dict[str, Any]:
        """Format E*TRADE portfolio totals response"""
        return {
            'todays_gain_loss': totals.get('todaysGainLoss', 0),
            'todays_gain_loss_pct': totals.get('todaysGainLossPct', 0),
            'total_market_value': totals.get('totalMarketValue', 0),
            'total_gain_loss': totals.get('totalGainLoss', 0),
            'total_gain_loss_pct': totals.get('totalGainLossPct', 0),
            'total_price_paid': totals.get('totalPricePaid', 0),
            'cash_balance': totals.get('cashBalance', 0),
        }

    def _format_order_response(self, order: Dict[str, Any], status: str) -> Dict[str, Any]:
        """Format E*TRADE order response to standard format"""
        # Extract order details (reuse existing parsing logic)
        order_detail = order.get("OrderDetail", [])
        if not isinstance(order_detail, list):
            order_detail = [order_detail]
        
        formatted_orders = []
        for detail in order_detail:
            instruments = detail.get("Instrument", [])
            if not isinstance(instruments, list):
                instruments = [instruments]
                
            for instrument in instruments:
                product = instrument.get("Product", {})
                formatted_order = {
                    'order_id': order.get('orderId', 'N/A'),
                    'status': detail.get('status', status),
                    'symbol': product.get('symbol', 'N/A'),
                    'side': instrument.get('orderAction', 'N/A'),
                    'quantity': instrument.get('orderedQuantity', 0),
                    'filled_quantity': instrument.get('filledQuantity', 0),
                    'price': detail.get('limitPrice', 0),
                    'order_type': detail.get('priceType', 'N/A'),
                    'duration': detail.get('orderTerm', 'N/A'),
                    'created_time': order.get('orderTime', 'N/A')
                }
                formatted_orders.append(formatted_order)
        
        return formatted_orders[0] if formatted_orders else {}

    def _format_transaction_response(self, transaction: Dict[str, Any]) -> Dict[str, Any]:
        """Format E*TRADE transaction response to standard format"""
        return {
            'date': transaction.get('date', 'N/A'),
            'type': transaction.get('type', 'N/A'),
            'amount': float(transaction.get('amount', 0)),
            'quantity': float(transaction.get('quantity', 0)),
            'price': float(transaction.get('price', 0)),
            'symbol': transaction.get('symbol', 'N/A'),
            'description': transaction.get('description', 'N/A'),
            'transaction_date': transaction.get('transactionDate', 'N/A'),
            'trade_date': transaction.get('tradeDate', 'N/A'),
            'settlement_date': transaction.get('settlementDate', 'N/A'),
            'commission': float(transaction.get('commission', 0)),
            'fees': float(transaction.get('fees', 0))
        }
