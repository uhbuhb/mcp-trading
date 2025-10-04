#!/usr/bin/env python3
"""
Main entry point for MCP Trading Server.

This application provides:
1. OAuth 2.1 authorization server for MCP clients
2. Web interface for credential management
3. MCP trading server with tools git logfor various brokers

Usage:
    python main.py          # Run the full application (web + MCP)
"""

import os
import sys
import logging
from pathlib import Path

# Add project root to Python path
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

# Import the main FastAPI application
from app import app

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("main")

def main():
    """Main entry point for the application."""
    logger.info("🚀 Starting MCP Trading Server")
    logger.info(f"Project root: {project_root}")
    
    # Get port from environment variable
    port = int(os.getenv("PORT", "8000"))
    
    # Import uvicorn for running the FastAPI app
    import uvicorn
    
    logger.info(f"Starting server on http://0.0.0.0:{port}")
    
    # Run the application
    uvicorn.run(
        "app:app",
        host="0.0.0.0",
        port=port,
        log_level="info",
        reload=False  # Set to True for development
    )

if __name__ == "__main__":
    main()
