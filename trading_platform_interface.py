"""
Abstract base class defining the interface for trading platform clients.

This interface ensures that all trading platform implementations (Tradier, Schwab, etc.)
provide the same set of methods with consistent signatures.
"""

from abc import ABC, abstractmethod
from typing import Dict, List, Any, Optional


class TradingPlatformInterface(ABC):
    """Abstract base class for trading platform clients."""
    
    @abstractmethod
    def get_account_info(self, account_id: Optional[str] = None) -> Dict[str, Any]:
        """
        Get account information.
        
        Args:
            account_id: Optional account ID override
            
        Returns:
            Account information dictionary
        """
        pass
    
    @abstractmethod
    def get_account_number(self) -> str:
        """
        Get the primary account number.
        
        Returns:
            Account number as string
        """
        pass
    
    @abstractmethod
    def get_positions(self, account_id: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        Get current positions.
        
        Args:
            account_id: Optional account ID override
            
        Returns:
            List of position dictionaries
        """
        pass
    
    @abstractmethod
    def get_quote(self, symbol: str) -> Dict[str, Any]:
        """
        Get quote for a symbol.
        
        Args:
            symbol: Symbol to get quote for
            
        Returns:
            Quote information dictionary
        """
        pass
    
    @abstractmethod
    def get_balance(self, account_id: Optional[str] = None) -> Dict[str, Any]:
        """
        Get account balance information.
        
        Args:
            account_id: Optional account ID override
            
        Returns:
            Balance information dictionary
        """
        pass
    
    @abstractmethod
    def get_orders(self, account_id: Optional[str] = None, include_filled: bool = True) -> List[Dict[str, Any]]:
        """
        Get orders for the account.
        
        Args:
            account_id: Optional account ID override
            include_filled: Whether to include filled orders
            
        Returns:
            List of order dictionaries
        """
        pass
    
    @abstractmethod
    def cancel_order(self, account_id: str, order_id: str) -> Dict[str, Any]:
        """
        Cancel an order.
        
        Args:
            account_id: Account ID
            order_id: Order ID to cancel
            
        Returns:
            Cancellation response dictionary
        """
        pass
    
    @abstractmethod
    def change_order(self, account_id: str, order_id: str, order_type: Optional[str] = None,
                    price: Optional[float] = None, duration: Optional[str] = None) -> Dict[str, Any]:
        """
        Modify an existing order.
        
        Args:
            account_id: Account ID
            order_id: Order ID to modify
            order_type: New order type (optional)
            price: New price (optional)
            duration: New duration (optional)
            
        Returns:
            Modification response dictionary
        """
        pass
    
    @abstractmethod
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
        pass
    
    @abstractmethod
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
        pass


# Optional methods that some platforms may support
class ExtendedTradingPlatformInterface(TradingPlatformInterface):
    """Extended interface with optional methods for advanced features."""
    
    @abstractmethod
    def get_option_chain(self, symbol: str, expiration: Optional[str] = None, 
                        greeks: bool = False) -> Dict[str, Any]:
        """
        Get option chain for a symbol.
        
        Args:
            symbol: Underlying symbol
            expiration: Specific expiration date (optional)
            greeks: Whether to include Greeks data
            
        Returns:
            Option chain dictionary
        """
        pass
    
    @abstractmethod
    def get_option_expirations(self, symbol: str) -> List[str]:
        """
        Get available expiration dates for a symbol.
        
        Args:
            symbol: Underlying symbol
            
        Returns:
            List of expiration dates
        """
        pass
    
    @abstractmethod
    def get_option_strikes(self, symbol: str, expiration: str) -> List[float]:
        """
        Get available strike prices for a symbol and expiration.
        
        Args:
            symbol: Underlying symbol
            expiration: Expiration date
            
        Returns:
            List of strike prices
        """
        pass
    
    @abstractmethod
    def get_historical_pricing(self, symbol: str, start_date: Optional[str] = None, 
                              end_date: Optional[str] = None, interval: str = 'daily') -> List[Dict[str, Any]]:
        """
        Get historical pricing data.
        
        Args:
            symbol: Symbol to get data for
            start_date: Start date (YYYY-MM-DD)
            end_date: End date (YYYY-MM-DD)
            interval: Data interval ('daily', 'weekly', 'monthly')
            
        Returns:
            List of price data dictionaries
        """
        pass
    
    @abstractmethod
    def place_option_order(self, account_id: str, option_symbol: str, side: str, 
                          quantity: int, order_type: str = 'market', 
                          price: Optional[float] = None, duration: str = 'day') -> Dict[str, Any]:
        """
        Place a single option order.
        
        Args:
            account_id: Account ID
            option_symbol: Option symbol
            side: 'buy_to_open', 'sell_to_open', 'buy_to_close', 'sell_to_close'
            quantity: Number of contracts
            order_type: Order type ('market', 'limit', 'stop', 'stop_limit')
            price: Limit price (required for limit orders)
            duration: Order duration ('day', 'gtc')
            
        Returns:
            Order response dictionary
        """
        pass
    
    @abstractmethod
    def validate_option_symbol(self, option_symbol: str) -> bool:
        """
        Validate an option symbol format.
        
        Args:
            option_symbol: Option symbol to validate
            
        Returns:
            True if valid, False otherwise
        """
        pass
    
    @abstractmethod
    def get_option_quote(self, option_symbol: str) -> Dict[str, Any]:
        """
        Get quote for an option symbol.
        
        Args:
            option_symbol: Option symbol
            
        Returns:
            Option quote dictionary
        """
        pass
