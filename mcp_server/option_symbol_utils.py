"""
Option Symbol Utilities

This module provides utilities for parsing and validating OCC (Options Clearing Corporation) 
option symbols used by trading platforms like Schwab and Tradier.
"""

import re
from typing import Tuple, Optional
from schwab.orders.options import OptionSymbol


# Regex pattern for OCC option symbols: ^([A-Z.]{1,6})\s+(\d{6})(C|P)(\d{8})$
# This matches: [SYMBOL with optional spaces][YYMMDD][C/P][STRIKE padded to 8 digits]
OCC_SYMBOL_PATTERN = re.compile(r'^([A-Z.]{1,6})\s*(\d{6})(C|P)(\d{8})$')


def parse_occ_option_symbol(occ_symbol: str) -> Tuple[str, str, str, str]:
    """
    Parse an OCC option symbol using regex.
    
    Args:
        occ_symbol: OCC format option symbol (e.g., 'V251017C00340000')
        
    Returns:
        Tuple of (underlying_symbol, expiration_date, contract_type, strike_price)
        
    Raises:
        ValueError: If the symbol doesn't match the OCC format
        
    Examples:
        >>> parse_occ_option_symbol('V251017C00340000')
        ('V', '251017', 'C', '340')
        >>> parse_occ_option_symbol('AAPL   251017P00340000')
        ('AAPL', '251017', 'P', '340')
    """
    match = OCC_SYMBOL_PATTERN.match(occ_symbol)
    if not match:
        raise ValueError(f"Invalid OCC option symbol format: {occ_symbol}. Expected format: [SYMBOL][YYMMDD][C/P][STRIKE]")
    
    underlying_symbol = match.group(1).strip()  # Remove any trailing spaces
    expiration_date = match.group(2)  # YYMMDD
    contract_type = match.group(3)    # C or P
    strike_price = str(int(match.group(4)) / 1000)  # Convert to decimal string
    
    return underlying_symbol, expiration_date, contract_type, strike_price


def validate_occ_option_symbol(occ_symbol: str) -> bool:
    """
    Validate if a string matches the OCC option symbol format.
    
    Args:
        occ_symbol: String to validate
        
    Returns:
        True if the symbol matches OCC format, False otherwise
        
    Examples:
        >>> validate_occ_option_symbol('V251017C00340000')
        True
        >>> validate_occ_option_symbol('INVALID_SYMBOL')
        False
    """
    return bool(OCC_SYMBOL_PATTERN.match(occ_symbol))


def convert_occ_to_schwab_format(occ_symbol: str) -> str:
    """
    Convert OCC option symbol to Schwab format using schwab-py library.
    
    Args:
        occ_symbol: OCC format option symbol (e.g., 'V251017C00340000')
        
    Returns:
        Schwab format option symbol (e.g., 'V     251017C00340000')
        
    Raises:
        ValueError: If the symbol doesn't match the OCC format
        
    Examples:
        >>> convert_occ_to_schwab_format('V251017C00340000')
        'V     251017C00340000'
    """
    underlying_symbol, expiration_date, contract_type, strike_price = parse_occ_option_symbol(occ_symbol)
    
    # Create OptionSymbol object and build the Schwab format
    option_symbol_obj = OptionSymbol(underlying_symbol, expiration_date, contract_type, strike_price)
    return option_symbol_obj.build()


def format_occ_option_symbol(underlying: str, expiration_date: str, contract_type: str, strike_price: float) -> str:
    """
    Format option components into OCC option symbol format.
    
    Args:
        underlying: Underlying symbol (e.g., 'V', 'AAPL')
        expiration_date: Expiration date in YYMMDD format (e.g., '251017')
        contract_type: 'C' for call or 'P' for put
        strike_price: Strike price as float (e.g., 340.0)
        
    Returns:
        OCC format option symbol
        
    Examples:
        >>> format_occ_option_symbol('V', '251017', 'C', 340.0)
        'V251017C00340000'
    """
    # Validate inputs
    if contract_type not in ['C', 'P']:
        raise ValueError("Contract type must be 'C' or 'P'")
    
    if len(expiration_date) != 6:
        raise ValueError("Expiration date must be in YYMMDD format")
    
    # Format strike price to 8 digits
    strike_formatted = f"{int(strike_price * 1000):08d}"
    
    return f"{underlying}{expiration_date}{contract_type}{strike_formatted}"


def get_option_symbol_info(occ_symbol: str) -> dict:
    """
    Get detailed information about an OCC option symbol.
    
    Args:
        occ_symbol: OCC format option symbol
        
    Returns:
        Dictionary with parsed symbol information
        
    Raises:
        ValueError: If the symbol doesn't match the OCC format
        
    Examples:
        >>> get_option_symbol_info('V251017C00340000')
        {
            'underlying': 'V',
            'expiration_date': '251017',
            'expiration_year': 2025,
            'expiration_month': 10,
            'expiration_day': 17,
            'contract_type': 'C',
            'contract_type_name': 'Call',
            'strike_price': 340.0,
            'strike_formatted': '00340000'
        }
    """
    underlying_symbol, expiration_date, contract_type, strike_price = parse_occ_option_symbol(occ_symbol)
    
    # Parse expiration date
    year = 2000 + int(expiration_date[:2])
    month = int(expiration_date[2:4])
    day = int(expiration_date[4:6])
    
    return {
        'underlying': underlying_symbol,
        'expiration_date': expiration_date,
        'expiration_year': year,
        'expiration_month': month,
        'expiration_day': day,
        'contract_type': contract_type,
        'contract_type_name': 'Call' if contract_type == 'C' else 'Put',
        'strike_price': float(strike_price),
        'strike_formatted': f"{int(float(strike_price) * 1000):08d}"
    }

