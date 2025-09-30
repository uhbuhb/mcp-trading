#!/usr/bin/env python3
"""
Simple debug script for testing place_multileg_order function.
Minimal example with a two-leg vertical call spread.
"""

import os
from dotenv import load_dotenv
from tradier_client import TradierClient

# Load environment variables from .env file
load_dotenv()


def simple_multileg_test():
    """
    Simple test of place_multileg_order with a vertical call spread.
    """
    # Get credentials from .env file
    access_token = os.getenv('TRADIER_SANDBOX_ACCESS_TOKEN')
    if not access_token:
        print("Set TRADIER_SANDBOX_ACCESS_TOKEN environment variable in .env file")
        return
    
    # Initialize client
    client = TradierClient(access_token=access_token, sandbox=True)
    
    # Get account number
    account_number = client.get_account_number()
    print(f"Account: {account_number}")
    
    # Define a simple vertical call spread
    symbol = 'AAPL'
    legs = [
        {
            'side': 'buy_to_open',
            'quantity': 1,
            'option_symbol': 'AAPL251003C00200000'  # AAPL Jan 17, 2025 $200 Call
        },
        {
            'side': 'sell_to_open',
            'quantity': 1, 
            'option_symbol': 'AAPL251003C00205000'  # AAPL Jan 17, 2025 $205 Call
        }
    ]
    
    print(f"Placing vertical call spread on {symbol}")
    print("Legs:")
    for i, leg in enumerate(legs, 1):
        print(f"  {i}. {leg['side']} {leg['quantity']} {leg['option_symbol']}")
    
    try:
        # Test limit order (debit spread - paying premium)
        print("\nPreviewing limit order (debit spread)...")
        response = client.place_multileg_order(
            account_id=account_number,
            symbol=symbol,
            legs=legs,
            order_type='debit',
            duration='day',
            preview=True,
            price=2.50  # Pay $2.50 for the spread
        )
        
        print("Limit order preview response:")
        print(f"  Status: {response.get('status', 'Unknown')}")
        if 'order' in response:
            order_info = response['order']
            print(f"  Order ID: {order_info.get('id', 'N/A')}")
            print(f"  Commission: ${order_info.get('commission', 'N/A')}")
            print(f"  Cost: ${order_info.get('cost', 'N/A')}")
        
    except Exception as e:
        print(f"Error: {e}")


if __name__ == "__main__":
    simple_multileg_test()
