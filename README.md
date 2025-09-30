# MCP Trading Server 📈

A Model Context Protocol (MCP) server that provides trading capabilities for various brokerages. Currently supports Tradier with extensible architecture for additional platforms.

## Features

- **Multi-Platform Support**: Extensible factory pattern for multiple brokerages
- **Sandbox & Production**: Toggle between test and live trading environments
- **Comprehensive Trading Tools**: Quotes, options chains, account info, order placement, and more
- **MCP Integration**: Works with Claude Desktop and other MCP clients

## Deployment

This server is **deployed on Railway** and accessible at:
```
https://mcp-trading-production.up.railway.app/mcp
```

### Use the Deployed Server (Easiest)

Add this to your Claude Desktop configuration (`~/Library/Application Support/Claude/claude_desktop_config.json`):

```json
{
  "mcpServers": {
    "trading": {
      "command": "npx",
      "args": ["-y", "mcp-remote", "https://mcp-trading-production.up.railway.app/mcp"],
      "icon": "📈"
    }
  }
}
```

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


## Available Tools

The server exposes comprehensive trading capabilities including:
- Real-time quotes and options chains
- Account information and positions
- Order placement (single and multi-leg strategies)
- Order management and history
- Market calendars and time/sales data

See the tool definitions in `trading.py` for complete documentation.

## Project Structure

```
mcp-trading/
├── trading.py              # Main MCP server
├── tradier_client.py       # Tradier API client
├── pyproject.toml          # Project configuration
└── .env                    # Environment variables (create this)
```

## License

[Add your license here]