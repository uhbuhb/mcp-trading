#!/usr/bin/env python3
"""
CLI tool for testing trading client functionality.
Supports multiple trading platforms.
"""

import os
import json
import click
from typing import Optional
from dotenv import load_dotenv
from tradier_client import TradierClient

# Load environment variables
load_dotenv()

def get_tradier_client(use_sandbox: bool = True) -> TradierClient:
    """
    Get a Tradier client instance.
    
    Args:
        use_sandbox: Whether to use sandbox environment
        
    Returns:
        TradierClient instance
        
    Raises:
        click.ClickException: If configuration is invalid
    """
    if use_sandbox:
        access_token = os.getenv("TRADIER_SANDBOX_ACCESS_TOKEN")
        if not access_token:
            raise click.ClickException("TRADIER_SANDBOX_ACCESS_TOKEN environment variable is required for paper trading mode")
    else:
        access_token = os.getenv("TRADIER_ACCESS_TOKEN")
        if not access_token:
            raise click.ClickException("TRADIER_ACCESS_TOKEN environment variable is required for production mode")
    
    return TradierClient(access_token=access_token, sandbox=use_sandbox)

def get_tradier_account_id(use_sandbox: bool = True) -> Optional[str]:
    """Get the Tradier account ID from environment variables."""
    if use_sandbox:
        return os.getenv("TRADIER_SANDBOX_ACCOUNT_NUMBER")
    else:
        return os.getenv("TRADIER_ACCOUNT_NUMBER")

def show_verbose_output(ctx, data, title="Raw API Response"):
    """Display verbose output if verbose flag is set."""
    if ctx.obj.get('verbose', False):
        click.echo(f"\n{'='*50}")
        click.echo(f"{title}")
        click.echo(f"{'='*50}")
        click.echo(json.dumps(data, indent=2))
        click.echo(f"{'='*50}\n")

@click.group()
@click.option('--verbose', '-v', is_flag=True, help='Show raw API responses')
@click.pass_context
def cli(ctx, verbose):
    """CLI tool for testing trading client functionality."""
    ctx.ensure_object(dict)
    ctx.obj['verbose'] = verbose

@cli.group()
@click.option('--production', is_flag=True, help='Use production environment (default: paper trading)')
@click.pass_context
def tradier(ctx, production):
    """Tradier trading platform commands."""
    ctx.ensure_object(dict)
    ctx.obj['sandbox'] = not production
    ctx.obj['environment'] = 'production' if production else 'paper trading'
    ctx.obj['platform'] = 'tradier'

@tradier.command()
@click.option('--account-id', help='Specific account ID (optional)')
@click.pass_context
def positions(ctx, account_id):
    """Get current trading positions."""
    try:
        client = get_tradier_client(use_sandbox=ctx.obj['sandbox'])
        
        # Use provided account ID or get from environment
        if not account_id:
            account_id = get_tradier_account_id(use_sandbox=ctx.obj['sandbox'])
        
        if not account_id:
            env_var = "TRADIER_ACCOUNT_NUMBER" if ctx.obj['sandbox'] == False else "TRADIER_SANDBOX_ACCOUNT_NUMBER"
            raise click.ClickException(f"No account ID provided. Set {env_var} or use --account-id")
        
        click.echo(f"Getting positions for account {account_id} ({ctx.obj['environment']})...")
        
        positions = client.get_positions(account_id)
        
        # Show verbose output if requested
        show_verbose_output(ctx, positions, "Raw Positions API Response")
        
        if not positions:
            click.echo("No positions found.")
            return
        
        # Format and display positions
        click.echo(f"\nFound {len(positions)} positions:\n")
        
        for i, position in enumerate(positions, 1):
            click.echo(f"Position {i}:")
            click.echo(f"  Symbol: {position.get('symbol', 'N/A')}")
            click.echo(f"  Description: {position.get('description', 'N/A')}")
            click.echo(f"  Quantity: {position.get('quantity', 'N/A')}")
            click.echo(f"  Cost Basis: ${position.get('cost_basis', 'N/A')}")
            click.echo(f"  Last Price: ${position.get('last_price', 'N/A')}")
            click.echo(f"  Market Value: ${position.get('market_value', 'N/A')}")
            click.echo(f"  Gain/Loss: ${position.get('gain_loss', 'N/A')} ({position.get('gain_loss_percent', 'N/A')}%)")
            click.echo(f"  Type: {position.get('type', 'N/A')}")
            click.echo(f"  Date Acquired: {position.get('date_acquired', 'N/A')}")
            click.echo()
        
    except Exception as e:
        raise click.ClickException(f"Failed to get positions: {str(e)}")

@tradier.group()
@click.option('--account-id', help='Specific account ID (optional)')
@click.pass_context
def orders(ctx, account_id):
    """Manage trading orders."""
    ctx.ensure_object(dict)
    ctx.obj['account_id'] = account_id

@orders.command('list')
@click.option('--include-filled/--no-include-filled', default=True, help='Include filled orders (default: True)')
@click.pass_context
def orders_list(ctx, include_filled):
    """List trading orders."""
    try:
        client = get_tradier_client(use_sandbox=ctx.parent.obj['sandbox'])
        
        # Use provided account ID or get from environment
        account_id = ctx.parent.obj.get('account_id')
        if not account_id:
            account_id = get_tradier_account_id(use_sandbox=ctx.parent.obj['sandbox'])
        
        if not account_id:
            env_var = "TRADIER_ACCOUNT_NUMBER" if ctx.parent.obj['sandbox'] == False else "TRADIER_SANDBOX_ACCOUNT_NUMBER"
            raise click.ClickException(f"No account ID provided. Set {env_var} or use --account-id")
        
        click.echo(f"Getting orders for account {account_id} ({ctx.parent.obj['environment']})...")
        click.echo(f"Include filled orders: {include_filled}\n")
        
        orders = client.get_orders(account_id=account_id, include_filled=include_filled)
        
        # Show verbose output if requested
        show_verbose_output(ctx, orders, "Raw Orders API Response")
        
        if not orders:
            click.echo("No orders found.")
            return
        
        # Format and display orders
        click.echo(f"Found {len(orders)} orders:\n")
        
        for i, order in enumerate(orders, 1):
            click.echo(f"Order {i}:")
            click.echo(f"  ID: {order.get('id', 'N/A')}")
            click.echo(f"  Symbol: {order.get('symbol', 'N/A')}")
            click.echo(f"  Status: {order.get('status', 'N/A')}")
            click.echo(f"  Type: {order.get('type', 'N/A')}")
            click.echo(f"  Class: {order.get('class', 'N/A')}")
            
            # Show strategy for multileg orders
            if order.get('strategy'):
                click.echo(f"  Strategy: {order.get('strategy', 'N/A')}")
            
            # Show price for limit orders
            if order.get('price') and order.get('price') != 0:
                click.echo(f"  Price: ${order.get('price', 'N/A')}")
            
            # Show legs for multileg orders
            if order.get('leg') and isinstance(order.get('leg'), list):
                click.echo(f"  Legs ({len(order['leg'])}):")
                for j, leg in enumerate(order['leg'], 1):
                    click.echo(f"    Leg {j}:")
                    click.echo(f"      Side: {leg.get('side', 'N/A')}")
                    click.echo(f"      Quantity: {leg.get('quantity', 'N/A')}")
                    click.echo(f"      Option Symbol: {leg.get('option_symbol', 'N/A')}")
                    click.echo(f"      Status: {leg.get('status', 'N/A')}")
                    if leg.get('price') and leg.get('price') != 0:
                        click.echo(f"      Price: ${leg.get('price', 'N/A')}")
            elif order.get('option_symbol'):
                # Single option order
                click.echo(f"  Option Symbol: {order.get('option_symbol', 'N/A')}")
                click.echo(f"  Side: {order.get('side', 'N/A')}")
                click.echo(f"  Quantity: {order.get('quantity', 'N/A')}")
            
            click.echo(f"  Created: {order.get('create_date', 'N/A')}")
            click.echo()
        
    except Exception as e:
        raise click.ClickException(f"Failed to get orders: {str(e)}")

@orders.command('cancel')
@click.argument('order_id')
@click.pass_context
def orders_cancel(ctx, order_id):
    """Cancel an existing order."""
    try:
        client = get_tradier_client(use_sandbox=ctx.parent.obj['sandbox'])
        
        # Use provided account ID or get from environment
        account_id = ctx.parent.obj.get('account_id')
        if not account_id:
            account_id = get_tradier_account_id(use_sandbox=ctx.parent.obj['sandbox'])
        
        if not account_id:
            env_var = "TRADIER_ACCOUNT_NUMBER" if ctx.parent.obj['sandbox'] == False else "TRADIER_SANDBOX_ACCOUNT_NUMBER"
            raise click.ClickException(f"No account ID provided. Set {env_var} or use --account-id")
        
        click.echo(f"Cancelling order {order_id} for account {account_id} ({ctx.parent.obj['environment']})...")
        
        response = client.cancel_order(account_id=account_id, order_id=order_id)
        
        # Show verbose output if requested
        show_verbose_output(ctx, response, "Raw Cancel Order API Response")
        
        click.echo(f"Order {order_id} cancellation submitted successfully!")
        
        if response:
            click.echo(f"Response: {json.dumps(response, indent=2)}")
        
    except Exception as e:
        raise click.ClickException(f"Failed to cancel order {order_id}: {str(e)}")

@orders.command('change')
@click.argument('order_id')
@click.option('--order-type', help='New order type (market, limit, stop, stop_limit)')
@click.option('--price', type=float, help='New limit price (required for limit orders)')
@click.option('--stop', type=float, help='New stop price (required for stop orders)')
@click.option('--duration', help='New order duration (day, gtc, pre, post)')
@click.option('--quantity', type=float, help='New quantity')
@click.pass_context
def orders_change(ctx, order_id, order_type, price, stop, duration, quantity):
    """Change/modify an existing order."""
    try:
        client = get_tradier_client(use_sandbox=ctx.parent.obj['sandbox'])
        
        # Use provided account ID or get from environment
        account_id = ctx.parent.obj.get('account_id')
        if not account_id:
            account_id = get_tradier_account_id(use_sandbox=ctx.parent.obj['sandbox'])
        
        if not account_id:
            env_var = "TRADIER_ACCOUNT_NUMBER" if ctx.parent.obj['sandbox'] == False else "TRADIER_SANDBOX_ACCOUNT_NUMBER"
            raise click.ClickException(f"No account ID provided. Set {env_var} or use --account-id")
        
        # Validate that at least one parameter is being changed
        if all(param is None for param in [order_type, price, stop, duration, quantity]):
            raise click.ClickException("At least one order parameter must be provided for modification")
        
        # Validate order type and price dependencies
        if order_type in ['limit', 'stop_limit'] and price is None:
            raise click.ClickException(f"Price is required for {order_type} orders")
        
        if order_type in ['stop', 'stop_limit'] and stop is None:
            raise click.ClickException(f"Stop price is required for {order_type} orders")
        
        # Build changes summary for display
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
        click.echo(f"Changing order {order_id} for account {account_id} ({ctx.parent.obj['environment']})...")
        click.echo(f"Changes: {changes_summary}")
        
        response = client.change_order(
            account_id=account_id,
            order_id=order_id,
            order_type=order_type,
            price=price,
            stop=stop,
            duration=duration,
            quantity=quantity
        )
        
        # Show verbose output if requested
        show_verbose_output(ctx, response, "Raw Change Order API Response")
        
        click.echo(f"Order {order_id} modification submitted successfully!")
        
        if response:
            click.echo(f"Response: {json.dumps(response, indent=2)}")
        
    except Exception as e:
        raise click.ClickException(f"Failed to change order {order_id}: {str(e)}")

@tradier.command()
@click.pass_context
def account_info(ctx):
    """Get account information."""
    try:
        client = get_tradier_client(use_sandbox=ctx.obj['sandbox'])
        
        click.echo(f"Getting account information ({ctx.obj['environment']})...\n")
        
        account_info = client.get_account_info()
        
        # Show verbose output if requested
        show_verbose_output(ctx, account_info, "Raw Account Info API Response")
        
        click.echo("Account Information:")
        click.echo(f"  Profile ID: {account_info.get('profile_id', 'N/A')}")
        click.echo(f"  Profile Name: {account_info.get('profile_name', 'N/A')}")
        click.echo(f"  Account Number: {account_info.get('account_number', 'N/A')}")
        click.echo(f"  Account Type: {account_info.get('account_type', 'N/A')}")
        click.echo(f"  Classification: {account_info.get('classification', 'N/A')}")
        click.echo(f"  Day Trader: {account_info.get('day_trader', 'N/A')}")
        click.echo(f"  Option Level: {account_info.get('option_level', 'N/A')}")
        click.echo(f"  Status: {account_info.get('status', 'N/A')}")
        click.echo(f"  Date Created: {account_info.get('date_created', 'N/A')}")
        click.echo(f"  Last Update: {account_info.get('last_update_date', 'N/A')}")
        
    except Exception as e:
        raise click.ClickException(f"Failed to get account info: {str(e)}")

@tradier.command()
@click.option('--account-id', help='Specific account ID (optional)')
@click.pass_context
def balance(ctx, account_id):
    """Get account balance."""
    try:
        client = get_tradier_client(use_sandbox=ctx.obj['sandbox'])
        
        # Use provided account ID or get from environment
        if not account_id:
            account_id = get_tradier_account_id(use_sandbox=ctx.obj['sandbox'])
        
        if not account_id:
            env_var = "TRADIER_ACCOUNT_NUMBER" if ctx.obj['sandbox'] == False else "TRADIER_SANDBOX_ACCOUNT_NUMBER"
            raise click.ClickException(f"No account ID provided. Set {env_var} or use --account-id")
        
        click.echo(f"Getting balance for account {account_id} ({ctx.obj['environment']})...\n")
        
        balance = client.get_balance(account_id)
        
        # Show verbose output if requested
        show_verbose_output(ctx, balance, "Raw Balance API Response")
        
        click.echo("Account Balance:")
        for key, value in balance.items():
            click.echo(f"  {key.replace('_', ' ').title()}: ${value}")
        
    except Exception as e:
        raise click.ClickException(f"Failed to get balance: {str(e)}")

@tradier.command()
@click.argument('symbol')
@click.pass_context
def quote(ctx, symbol):
    """Get quote for a stock symbol."""
    try:
        client = get_tradier_client(use_sandbox=ctx.obj['sandbox'])
        
        click.echo(f"Getting quote for {symbol} ({ctx.obj['environment']})...\n")
        
        quote = client.get_quote(symbol)
        
        # Show verbose output if requested
        show_verbose_output(ctx, quote, f"Raw Quote API Response for {symbol}")
        
        click.echo(f"Quote for {symbol}:")
        for key, value in quote.items():
            if isinstance(value, (int, float)):
                click.echo(f"  {key.replace('_', ' ').title()}: ${value}")
            else:
                click.echo(f"  {key.replace('_', ' ').title()}: {value}")
        
    except Exception as e:
        raise click.ClickException(f"Failed to get quote for {symbol}: {str(e)}")

@tradier.command()
@click.option('--account-id', help='Specific account ID (optional)')
@click.option('--limit', type=int, help='Number of records to return')
@click.option('--page', type=int, help='Page number for pagination')
@click.option('--start-date', help='Start date in YYYY-MM-DD format')
@click.option('--end-date', help='End date in YYYY-MM-DD format')
@click.option('--type', 'type_filter', help='Filter by transaction type')
@click.pass_context
def history(ctx, account_id, limit, page, start_date, end_date, type_filter):
    """Get account historical activity."""
    try:
        client = get_tradier_client(use_sandbox=ctx.obj['sandbox'])
        
        # Use provided account ID or get from environment
        if not account_id:
            account_id = get_tradier_account_id(use_sandbox=ctx.obj['sandbox'])
        
        if not account_id:
            env_var = "TRADIER_ACCOUNT_NUMBER" if ctx.obj['sandbox'] == False else "TRADIER_SANDBOX_ACCOUNT_NUMBER"
            raise click.ClickException(f"No account ID provided. Set {env_var} or use --account-id")
        
        # Build filter summary for display
        filters = []
        if start_date and end_date:
            filters.append(f"from {start_date} to {end_date}")
        elif start_date:
            filters.append(f"from {start_date}")
        elif end_date:
            filters.append(f"until {end_date}")
        
        if type_filter:
            filters.append(f"type: {type_filter}")
        
        if limit:
            filters.append(f"limit: {limit}")
        
        if page:
            filters.append(f"page: {page}")
        
        filter_summary = " | ".join(filters) if filters else "all available"
        
        click.echo(f"Getting account history for account {account_id} ({ctx.obj['environment']})...")
        click.echo(f"Filters: {filter_summary}\n")
        
        history = client.get_account_history(
            account_id=account_id,
            limit=limit,
            page=page,
            start_date=start_date,
            end_date=end_date,
            type_filter=type_filter
        )
        
        # Show verbose output if requested
        show_verbose_output(ctx, history, "Raw Account History API Response")
        
        if not history['events']:
            click.echo("No historical events found.")
            return
        
        # Format and display history
        click.echo(f"Found {history['total_events']} historical events:\n")
        
        for i, event in enumerate(history['events'], 1):
            click.echo(f"Event {i}:")
            click.echo(f"  Date: {event.get('date', 'N/A')}")
            click.echo(f"  Type: {event.get('type', 'N/A')}")
            click.echo(f"  Symbol: {event.get('symbol', 'N/A')}")
            click.echo(f"  Description: {event.get('description', 'N/A')}")
            
            # Show financial details if available
            if event.get('amount') is not None:
                click.echo(f"  Amount: ${event['amount']}")
            if event.get('quantity') is not None:
                click.echo(f"  Quantity: {event['quantity']}")
            if event.get('price') is not None:
                click.echo(f"  Price: ${event['price']}")
            if event.get('commission') is not None:
                click.echo(f"  Commission: ${event['commission']}")
            if event.get('fees') is not None:
                click.echo(f"  Fees: ${event['fees']}")
            
            # Show dates
            if event.get('transaction_date') != 'N/A':
                click.echo(f"  Transaction Date: {event['transaction_date']}")
            if event.get('trade_date') != 'N/A':
                click.echo(f"  Trade Date: {event['trade_date']}")
            if event.get('settlement_date') != 'N/A':
                click.echo(f"  Settlement Date: {event['settlement_date']}")
            
            click.echo()
        
    except Exception as e:
        raise click.ClickException(f"Failed to get account history: {str(e)}")

# Placeholder for future E-Trade support
@cli.group()
@click.option('--production', is_flag=True, help='Use production environment (default: paper trading)')
@click.pass_context
def etrade(ctx, production):
    """E-Trade trading platform commands (coming soon)."""
    ctx.ensure_object(dict)
    ctx.obj['sandbox'] = not production
    ctx.obj['environment'] = 'production' if production else 'paper trading'
    ctx.obj['platform'] = 'etrade'
    
    # For now, just show a message that it's not implemented yet
    click.echo("E-Trade support is not yet implemented.")
    click.echo("This is a placeholder for future E-Trade integration.")
    ctx.exit()

if __name__ == '__main__':
    cli()
