# Braintree MCP Server

An unofficial Model Context Protocol (MCP) server for interacting with PayPal Braintree payment processing services.

## Overview

This server implements the Model Context Protocol (MCP) specification to provide AI assistant models with direct, structured access to Braintree's payment processing capabilities via GraphQL API. It enables AI systems to perform payment operations like fetching transactions, creating payments, and managing customer data through MCP tools.

## Requirements

- Python 3.13+
- Braintree merchant account credentials

## Installation

1. Clone this repository
```bash
git clone https://github.com/yourusername/braintree-mcp-server.git
cd braintree-mcp-server
```

2. Set up a Python 3.13+ environment
```bash
# If using pyenv
pyenv install 3.13.0
pyenv local 3.13.0

# Or using another method to ensure Python 3.13+
```

3. Install dependencies
```bash
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

### Running the server

```bash
python braintree_server.py
```

The server runs using stdio transport by default, which is suitable for integration with AI assistant systems that support MCP.

### Available MCP Tools

#### braintree_ping

Simple connectivity test to check if your Braintree credentials are working.

```python
response = await braintree_ping()
# Returns "pong" if successful
```

#### braintree_execute_graphql

Execute arbitrary GraphQL queries against the Braintree API.

```python
query = """
query GetTransactionDetails($id: ID!) {
  node(id: $id) {
    ... on Transaction {
      id
      status
      amount {
        value
        currencyCode
      }
      createdAt
    }
  }
}
"""

variables = {"id": "transaction_id_here"}

response = await braintree_execute_graphql(query, variables)
# Returns JSON response from Braintree
```

## Common GraphQL Operations

### Fetch Customer

```graphql
query GetCustomer($id: ID!) {
  node(id: $id) {
    ... on Customer {
      id
      firstName
      lastName
      email
      paymentMethods {
        edges {
          node {
            id
            details {
              ... on CreditCardDetails {
                last4
                expirationMonth
                expirationYear
                cardType
              }
            }
          }
        }
      }
    }
  }
}
```

### Create Transaction

```graphql
mutation CreateTransaction($input: ChargePaymentMethodInput!) {
  chargePaymentMethod(input: $input) {
    transaction {
      id
      status
      amount {
        value
        currencyCode
      }
    }
  }
}
```

With variables:
```json
{
  "input": {
    "paymentMethodId": "payment_method_id_here",
    "transaction": {
      "amount": "10.00",
      "orderId": "order123",
      "options": {
        "submitForSettlement": true
      }
    }
  }
}
```

## Troubleshooting

- Ensure your Braintree credentials are correct in the `.env` file
- Verify your network connection can reach Braintree's API endpoints
- Check for any rate limiting or permission issues with your Braintree account

## License

This project is intended for demonstration purposes. Use in production at your own risk.

## Disclaimer

This is an unofficial integration and is not endorsed by or affiliated with PayPal or Braintree.