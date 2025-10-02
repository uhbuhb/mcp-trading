# MCP Trading Server 📈

A Model Context Protocol (MCP) server that provides trading capabilities for various brokerages. Currently supports Tradier with extensible architecture for additional platforms.

## Features

- **Multi-Platform Support**: Extensible factory pattern for multiple brokerages
- **Sandbox & Production**: Toggle between test and live trading environments
- **Comprehensive Trading Tools**: Quotes, options chains, account info, order placement, and more
- **MCP Integration**: Works with Claude Desktop and other MCP clients

## Local Development

### Prerequisites

- Python 3.13+
- [uv](https://github.com/astral-sh/uv) package manager

### Setup

1. **Clone the repository**
   ```bash
   git clone <repo-url>
   cd mcp-trading
   ```

2. **Install dependencies**
   ```bash
   uv sync
   ```

3. **Configure environment variables**
   
   Create a `.env` file in the project root with your API credentials:
   
   **For Tradier:**
   ```bash
   # Tradier Sandbox (for testing)
   TRADIER_SANDBOX_ACCESS_TOKEN=your_sandbox_token_here
   TRADIER_SANDBOX_ACCOUNT_NUMBER=your_sandbox_account_here
   TRADIER_SANDBOX_ENDPOINT=https://sandbox.tradier.com
   
   # Tradier Production (for live trading)
   TRADIER_ACCESS_TOKEN=your_production_token_here
   TRADIER_ACCOUNT_NUMBER=your_production_account_here
   TRADIER_ENDPOINT=https://api.tradier.com
   ```
   
   **For Schwab:**
   ```bash
   # Schwab API credentials (automatic OAuth authentication)
   SCHWAB_APP_KEY=your_app_key_here
   SCHWAB_APP_SECRET=your_app_secret_here
   SCHWAB_ACCOUNT_HASH=your_account_hash_here
   SCHWAB_CALLBACK_URL=https://127.0.0.1:8080  # optional, defaults to this
   ```

### Running Locally

**Option 1: Direct execution**
```bash
uv run trading.py
```

**Option 2: With Claude Desktop (local)**

Add this to your Claude Desktop configuration:
```json
{
  "mcpServers": {
    "trading": {
      "command": "uv",
      "args": [
        "--directory",
        "/absolute/path/to/mcp-trading",
        "run",
        "trading.py"
      ],
      "env": {
        "TRADIER_SANDBOX_ACCESS_TOKEN": "your_token",
        "TRADIER_SANDBOX_ACCOUNT_NUMBER": "your_account",
        "TRADIER_ACCESS_TOKEN": "your_prod_token",
        "TRADIER_ACCOUNT_NUMBER": "your_prod_account",
        "TRADIER_SANDBOX_ENDPOINT": "https://sandbox.tradier.com",
        "TRADIER_ENDPOINT": "https://api.tradier.com"
      }
    }
  }
}
```
OR for HTTP service (OAuth-enabled):
```
{
  "mcpServers": {
    "trading-localhost": {
      "command": "npx",
      "args": ["-y", "mcp-remote", "http://localhost:8000/mcp/"],
      "icon": "📈"
    }
  }
}
```

**⚠️ Important**: The MCP endpoint URL **must include the trailing slash** (`/mcp/`) to match the server's OAuth resource metadata. Without it, OAuth authentication will fail with a resource mismatch error.


## Available Tools

The server exposes comprehensive trading capabilities including:
- Real-time quotes and options chains
- Account information and positions
- Order placement (single and multi-leg strategies)
- Order management and history
- Market calendars and time/sales data

See the tool definitions in `trading_server_oauth.py` for complete documentation.

## Project Structure

```
mcp-trading/
├── trading_server_oauth.py # Main MCP server with OAuth
├── schwab_client.py        # Schwab API client (easy_client)
├── tradier_client.py       # Tradier API client
├── cli.py                  # Command-line interface
├── pyproject.toml          # Project configuration
└── .env                    # Environment variables (create this)
```

## License

[Add your license here]