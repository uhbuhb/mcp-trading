# Trading CLI Tool

A command-line interface for testing trading platform functionality.

## Usage

The CLI is organized by trading platform, with each platform having its own subcommands.

### Tradier Commands

```bash
# Get positions (paper trading by default)
./cli.py tradier positions

# Get positions in production
./cli.py tradier --production positions

# Get positions with verbose output (shows raw API response)
./cli.py -v tradier positions

# Get orders
./cli.py tradier orders

# Get orders excluding filled ones
./cli.py tradier orders --no-include-filled

# Get orders with verbose output (shows raw API response)
./cli.py -v tradier orders

# Get account information
./cli.py tradier account-info

# Get account balance
./cli.py tradier balance

# Get quote for a stock
./cli.py tradier quote AAPL

# Get quote with verbose output
./cli.py -v tradier quote AAPL

# Use specific account ID
./cli.py tradier positions --account-id "123456"

# Combine flags: production + verbose + specific account
./cli.py -v tradier --production positions --account-id "123456"
```

### Environment Variables

For **paper trading** (default):
- `TRADIER_SANDBOX_ACCESS_TOKEN` - Your Tradier sandbox API token
- `TRADIER_SANDBOX_ACCOUNT_NUMBER` - Your sandbox account number

For **production**:
- `TRADIER_ACCESS_TOKEN` - Your Tradier production API token  
- `TRADIER_PRODUCTION_ACCOUNT_NUMBER` - Your production account number

### Future Platforms

The CLI is designed to support multiple trading platforms:

```bash
# Future E-Trade support (placeholder)
./cli.py etrade positions
./cli.py etrade orders

# With verbose output
./cli.py -v etrade positions
```

## Installation

Install dependencies:
```bash
pip install -r requirements-cli.txt
```

Make executable:
```bash
chmod +x cli.py
```

## Verbose Output

Use the `--verbose` or `-v` flag to see the raw API responses from the trading platform. This is useful for:

- **Debugging** - See exactly what data the API returns
- **Development** - Understand the data structure for building integrations
- **Troubleshooting** - Identify issues with API responses

Example:
```bash
./cli.py -v tradier positions
```

This will show both the formatted output and the raw JSON response from the API.

## Orders Output Format

The orders command now shows a cleaner, more focused output:

- **Symbol & Status**: Key order information at the top
- **Strategy**: Shows the strategy type for multi-leg orders (e.g., "condor", "spread")
- **Legs Details**: For multi-leg option orders, shows each leg with:
  - Side (buy_to_open, sell_to_close, etc.)
  - Quantity
  - Option symbol
  - Status
  - Price (if applicable)

Example output:
```
Order 1:
  ID: 19850370
  Symbol: AAPL
  Status: canceled
  Type: market
  Class: multileg
  Strategy: condor
  Legs (4):
    Leg 1:
      Side: sell_to_close
      Quantity: 1.0
      Option Symbol: AAPL251003C00250000
      Status: canceled
    Leg 2:
      Side: buy_to_close
      Quantity: 1.0
      Option Symbol: AAPL251003C00260000
      Status: canceled
    ...
```

## Safety

- **Paper trading is the default** - you must explicitly use `--production` to access real money
- All commands show which environment they're using
- Account IDs are validated before making API calls
