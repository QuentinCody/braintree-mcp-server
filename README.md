# Braintree MCP Server

An unofficial Model Context Protocol (MCP) server for interacting with PayPal Braintree payment processing services.

## Server Versions

There are two versions of the Braintree MCP server available:

### 1. STDIO Transport Server (`braintree_server.py`)

- Uses standard input/output (STDIO) for communication
- Designed for integrations with Claude Desktop and other MCP clients that support STDIO
- Each client session spawns a new server process
- The server terminates when the client disconnects

**Usage with Claude Desktop:**
1. Configure `claude_desktop_config.json` to point to this server
2. Open Claude Desktop and select the Braintree tool

### 2. SSE Transport Server (`braintree_sse_server.py`)

- Uses Server-Sent Events (SSE) for communication
- Designed as a standalone web server that can handle multiple client connections
- Server runs persistently until manually stopped
- Binds to `127.0.0.1:8001` by default (configurable)

**Manual Usage:**
```bash
python braintree_sse_server.py
```

**Connecting to the SSE server:**
Use an MCP client that supports SSE transport and connect to `http://127.0.0.1:8001/sse`

## Overview

This MCP server provides a seamless interface to the Braintree API through GraphQL, enabling:

- Customer management
- Payment method operations
- Transaction processing
- Subscription handling
- Dispute and refund management

## Installation

```bash
# Clone the repository
git clone https://github.com/yourusername/braintree-mcp-server.git
cd braintree-mcp-server

# Install dependencies
pip install -r requirements.txt

# Optional: Install as editable package
pip install -e .
```

## Configuration

Create a `.env` file in the project root with your Braintree credentials:

```
BRAINTREE_MERCHANT_ID=your_merchant_id
BRAINTREE_PUBLIC_KEY=your_public_key
BRAINTREE_PRIVATE_KEY=your_private_key
BRAINTREE_ENVIRONMENT=sandbox  # or production
```

You can obtain these credentials from your Braintree Control Panel.

## Usage

The server exposes two primary tools:

1. `braintree_ping`: Tests connectivity to the Braintree API
2. `braintree_execute_graphql`: Executes arbitrary GraphQL queries against the Braintree API

### Example GraphQL Queries

See the docstring in `braintree_execute_graphql` for comprehensive examples of common operations with the Braintree API.

## Available Tools

The server provides these tools:

### Standard STDIO server (`braintree_server.py`):
- `braintree_ping` - Test connectivity to the Braintree API
- `braintree_execute_graphql` - Execute arbitrary GraphQL queries against the Braintree API

### SSE server (`braintree_sse_server.py`):
- `braintree_sse_ping` - Test connectivity to the Braintree API over SSE
- `braintree_execute_graphql_sse` - Execute arbitrary GraphQL queries over SSE

## Dependencies

See `requirements.txt` for the required dependencies.

## Requirements

- Python 3.13+
- Braintree merchant account credentials

## Troubleshooting

- Ensure your Braintree credentials are correct in the `.env` file
- Verify your network connection can reach Braintree's API endpoints
- Check for any rate limiting or permission issues with your Braintree account

## License

This project is intended for demonstration purposes. Use in production at your own risk.

## Disclaimer

This is an unofficial integration and is not endorsed by or affiliated with PayPal or Braintree.