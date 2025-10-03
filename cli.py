#!/usr/bin/env python3
"""
CLI tool for testing trading client functionality.
Supports multiple trading platforms with action-based commands.
"""

import os
import json
import click
from typing import Optional, Tuple
from dotenv import load_dotenv
from tradier_client import TradierClient
from schwab_client import SchwabClient

# Load environment variables
load_dotenv()

# ============================================================================
# HELPER FUNCTIONS
# ============================================================================

def get_platform_client(platform: str):
    """
    Get a client instance for the specified platform.

    Args:
        platform: Trading platform ('tradier', 'tradier_paper', or 'schwab')

    Returns:
        Tuple of (client, account_identifier)

    Raises:
        click.ClickException: If configuration is invalid
    """
    if platform == "tradier":
        # Tradier production
        access_token = os.getenv("TRADIER_ACCESS_TOKEN")
        account_id = os.getenv("TRADIER_ACCOUNT_NUMBER")
        if not access_token:
            raise click.ClickException("TRADIER_ACCESS_TOKEN environment variable is required")
        
        client = TradierClient(access_token=access_token, base_url="https://api.tradier.com")
        return client, account_id
        
    elif platform == "tradier_paper":
        # Tradier paper trading
        access_token = os.getenv("TRADIER_PAPER_ACCESS_TOKEN")
        account_id = os.getenv("TRADIER_PAPER_ACCOUNT_NUMBER")
        if not access_token:
            raise click.ClickException("TRADIER_PAPER_ACCESS_TOKEN environment variable is required")
        
        client = TradierClient(access_token=access_token, base_url="https://sandbox.tradier.com")
        return client, account_id

    elif platform == "schwab":
        # Schwab uses easy_client for automatic authentication
        app_key = os.getenv("SCHWAB_APP_KEY")
        app_secret = os.getenv("SCHWAB_APP_SECRET")
        account_hash = os.getenv("SCHWAB_ACCOUNT_HASH")

        if not app_key or not app_secret:
            raise click.ClickException(
                "Schwab requires SCHWAB_APP_KEY and SCHWAB_APP_SECRET environment variables. "
                "These are your Schwab API application credentials."
            )

        if not account_hash:
            raise click.ClickException(
                "SCHWAB_ACCOUNT_HASH environment variable is required. "
                "This is your Schwab account identifier."
            )

        # easy_client will handle authentication automatically
        # It will prompt for OAuth flow if no valid tokens exist
        client = SchwabClient(
            access_token="dummy",  # easy_client ignores this
            refresh_token="dummy",  # easy_client ignores this
            account_hash=account_hash
        )
        return client, account_hash

    else:
        raise click.ClickException(f"Unsupported platform: {platform}")


def determine_platform(platform: str, production: bool) -> str:
    """
    Determine which platform to use based on input and flags.

    Args:
        platform: Trading platform input
        production: Whether --production flag was specified

    Returns:
        Platform string ('tradier', 'tradier_paper', or 'schwab')
    """
    if platform == "tradier":
        return "tradier" if production else "tradier_paper"
    elif platform == "schwab":
        return "schwab"
    else:
        # Allow direct platform specification
        return platform


def show_verbose_output(ctx, data, title="Raw API Response"):
    """Display verbose output if verbose flag is set."""
    if ctx.obj.get('verbose', False):
        click.echo(f"\n{'='*50}")
        click.echo(f"{title}")
        click.echo(f"{'='*50}")
        click.echo(json.dumps(data, indent=2))
        click.echo(f"{'='*50}\n")


# ============================================================================
# CLI COMMANDS
# ============================================================================

@click.group()
@click.option('--verbose', '-v', is_flag=True, help='Show raw API responses')
@click.pass_context
def cli(ctx, verbose):
    """CLI tool for trading operations across multiple platforms."""
    ctx.ensure_object(dict)
    ctx.obj['verbose'] = verbose


@cli.command()
@click.argument('platform')
@click.option('--production', is_flag=True, help='Use production environment (default: paper)')
@click.option('--account-id', help='Specific account ID (optional)')
@click.pass_context
def positions(ctx, platform, production, account_id):
    """Get current trading positions."""
    try:
        actual_platform = determine_platform(platform, production)
        client, default_account = get_platform_client(actual_platform)

        account_to_use = account_id or default_account
        if not account_to_use:
            raise click.ClickException(f"No account ID available for {actual_platform}")

        click.echo(f"Getting positions for {actual_platform}...")

        positions = client.get_positions(account_to_use)

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
            click.echo(f"  Gain/Loss: ${position.get('gain_loss', 'N/A')}")
            click.echo(f"  Type: {position.get('type', 'N/A')}")
            click.echo()

    except Exception as e:
        raise click.ClickException(f"Failed to get positions: {str(e)}")


@cli.command()
@click.argument('symbol')
@click.argument('platform')
@click.option('--production', is_flag=True, help='Use production environment (default: paper)')
@click.pass_context
def quote(ctx, symbol, platform, production):
    """Get quote for a stock symbol."""
    try:
        actual_platform = determine_platform(platform, production)
        client, _ = get_platform_client(actual_platform)

        click.echo(f"Getting quote for {symbol} on {actual_platform}...\n")

        quote = client.get_quote(symbol)

        show_verbose_output(ctx, quote, f"Raw Quote API Response for {symbol}")

        click.echo(f"Quote for {symbol}:")
        for key, value in quote.items():
            if isinstance(value, (int, float)):
                click.echo(f"  {key.replace('_', ' ').title()}: ${value}")
            else:
                click.echo(f"  {key.replace('_', ' ').title()}: {value}")

    except Exception as e:
        raise click.ClickException(f"Failed to get quote for {symbol}: {str(e)}")


@cli.command()
@click.argument('platform')
@click.option('--production', is_flag=True, help='Use production environment (default: paper)')
@click.option('--account-id', help='Specific account ID (optional)')
@click.pass_context
def balance(ctx, platform, production, account_id):
    """Get account balance."""
    try:
        actual_platform = determine_platform(platform, production)
        client, default_account = get_platform_client(actual_platform)

        account_to_use = account_id or default_account
        if not account_to_use:
            raise click.ClickException(f"No account ID available for {actual_platform}")

        click.echo(f"Getting balance for {actual_platform}...\n")

        balance = client.get_balance(account_to_use)

        show_verbose_output(ctx, balance, "Raw Balance API Response")

        click.echo("Account Balance:")
        for key, value in balance.items():
            click.echo(f"  {key.replace('_', ' ').title()}: ${value}")

    except Exception as e:
        raise click.ClickException(f"Failed to get balance: {str(e)}")


@cli.command()
@click.argument('platform')
@click.option('--production', is_flag=True, help='Use production environment (default: paper)')
@click.option('--account-id', help='Specific account ID (optional)')
@click.pass_context
def account_info(ctx, platform, production, account_id):
    """Get account information."""
    try:
        actual_platform = determine_platform(platform, production)
        client, default_account = get_platform_client(actual_platform)

        account_to_use = account_id or default_account

        click.echo(f"Getting account information for {actual_platform}...\n")

        account_info = client.get_account_info(account_to_use)

        show_verbose_output(ctx, account_info, "Raw Account Info API Response")

        click.echo("Account Information:")
        for key, value in account_info.items():
            click.echo(f"  {key.replace('_', ' ').title()}: {value}")

    except Exception as e:
        raise click.ClickException(f"Failed to get account info: {str(e)}")


@cli.group()
@click.pass_context
def orders(ctx):
    """Manage trading orders."""
    ctx.ensure_object(dict)


@orders.command('list')
@click.argument('platform')
@click.option('--production', is_flag=True, help='Use production environment (default: paper)')
@click.option('--account-id', help='Specific account ID (optional)')
@click.pass_context
def orders_list(ctx, platform, production, account_id):
    """List trading orders."""
    try:
        actual_platform = determine_platform(platform, production)
        client, default_account = get_platform_client(actual_platform)

        account_to_use = account_id or default_account
        if not account_to_use:
            raise click.ClickException(f"No account ID available for {actual_platform}")

        click.echo(f"Getting orders for {actual_platform}...")

        orders = client.get_orders(account_id=account_to_use, include_filled=True)

        show_verbose_output(ctx, orders, "Raw Orders API Response")

        if not orders:
            click.echo("No orders found.")
            return

        # Format and display orders
        click.echo(f"Found {len(orders)} orders:\n")

        for i, order in enumerate(orders, 1):
            click.echo(f"Order {i}:")
            click.echo(f"  ID: {order.get('id', order.get('orderId', 'N/A'))}")
            click.echo(f"  Symbol: {order.get('symbol', 'N/A')}")
            click.echo(f"  Status: {order.get('status', 'N/A')}")
            click.echo(f"  Type: {order.get('type', order.get('orderType', 'N/A'))}")
            click.echo(f"  Created: {order.get('create_date', order.get('enteredTime', 'N/A'))}")
            click.echo()

    except Exception as e:
        raise click.ClickException(f"Failed to get orders: {str(e)}")


@orders.command('cancel')
@click.argument('order_id')
@click.argument('platform')
@click.option('--production', is_flag=True, help='Use production environment (default: paper)')
@click.option('--account-id', help='Specific account ID (optional)')
@click.pass_context
def orders_cancel(ctx, order_id, platform, production, account_id):
    """Cancel an existing order."""
    try:
        actual_platform = determine_platform(platform, production)
        client, default_account = get_platform_client(actual_platform)

        account_to_use = account_id or default_account
        if not account_to_use:
            raise click.ClickException(f"No account ID available for {actual_platform}")

        click.echo(f"Cancelling order {order_id} on {actual_platform}...")

        response = client.cancel_order(account_id=account_to_use, order_id=order_id)

        show_verbose_output(ctx, response, "Raw Cancel Order API Response")

        click.echo(f"Order {order_id} cancellation submitted successfully!")

        if response:
            click.echo(f"Response: {json.dumps(response, indent=2)}")

    except Exception as e:
        raise click.ClickException(f"Failed to cancel order {order_id}: {str(e)}")


if __name__ == '__main__':
    cli()
