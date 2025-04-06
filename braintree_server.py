import os
import httpx # Add this import
import base64 # Add this import
import json # Add this import
from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP
from typing import Any, Dict # Add these imports

load_dotenv()

# Braintree Configuration
BRAINTREE_MERCHANT_ID = os.getenv("BRAINTREE_MERCHANT_ID")
BRAINTREE_PUBLIC_KEY = os.getenv("BRAINTREE_PUBLIC_KEY")
BRAINTREE_PRIVATE_KEY = os.getenv("BRAINTREE_PRIVATE_KEY")
BRAINTREE_ENVIRONMENT = os.getenv("BRAINTREE_ENVIRONMENT", "sandbox") # Default to sandbox

if not all([BRAINTREE_MERCHANT_ID, BRAINTREE_PUBLIC_KEY, BRAINTREE_PRIVATE_KEY]):
    print("ERROR: Braintree credentials not found in .env file.")
    # In a real app, you might exit or raise an exception
    # For MCP, logging the error might be better once connected

BRAINTREE_API_URL = (
    "https://payments.sandbox.braintree-api.com/graphql"
    if BRAINTREE_ENVIRONMENT == "sandbox"
    else "https://payments.braintree-api.com/graphql"
)

# Braintree API Version (Check Braintree docs for the latest recommended version)
BRAINTREE_API_VERSION = "2025-04-01" # Example, update as needed

mcp = FastMCP("braintree", version="0.1.0")
print("Braintree MCP Server initialized.")

async def make_braintree_request(query: str, variables: Dict[str, Any] = None) -> Dict[str, Any]:
    """
    Makes an authenticated GraphQL request to the Braintree API.
    Handles basic authentication and error checking.
    """
    if not all([BRAINTREE_PUBLIC_KEY, BRAINTREE_PRIVATE_KEY]):
         return {"errors": [{"message": "Server missing Braintree API credentials."}]}

    # Basic Authentication: base64(public_key:private_key)
    auth_string = f"{BRAINTREE_PUBLIC_KEY}:{BRAINTREE_PRIVATE_KEY}"
    encoded_auth = base64.b64encode(auth_string.encode()).decode()

    headers = {
        "Authorization": f"Basic {encoded_auth}",
        "Braintree-Version": BRAINTREE_API_VERSION,
        "Content-Type": "application/json",
        "User-Agent": "MCPBraintreeServer/0.1.0" # Good practice
    }

    payload = {"query": query}
    if variables:
        payload["variables"] = variables

    async with httpx.AsyncClient() as client:
        try:
            print(f"Sending request to Braintree: {query[:100]}...") # Log query start
            response = await client.post(
                BRAINTREE_API_URL,
                headers=headers,
                json=payload,
                timeout=30.0
            )
            response.raise_for_status() # Raise HTTP errors (4xx, 5xx)
            print(f"Braintree response status: {response.status_code}")
            result = response.json()
            # Check for GraphQL errors within the response body
            if "errors" in result:
                print(f"GraphQL Errors: {result['errors']}")
            return result
        except httpx.RequestError as e:
            print(f"HTTP Request Error: {e}")
            return {"errors": [{"message": f"HTTP Request Error connecting to Braintree: {e}"}]}
        except httpx.HTTPStatusError as e:
             print(f"HTTP Status Error: {e.response.status_code} - {e.response.text}")
             error_detail = f"HTTP Status Error: {e.response.status_code}"
             try:
                 # Try to parse Braintree's error response if JSON
                 err_resp = e.response.json()
                 if "errors" in err_resp:
                      error_detail += f" - {err_resp['errors'][0]['message']}"
                 elif "error" in err_resp and "message" in err_resp["error"]:
                      error_detail += f" - {err_resp['error']['message']}"
                 else:
                     error_detail += f" - Response: {e.response.text[:200]}"
             except json.JSONDecodeError:
                 error_detail += f" - Response: {e.response.text[:200]}"

             return {"errors": [{"message": error_detail}]}

        except Exception as e:
            print(f"Generic Error during Braintree request: {e}")
            return {"errors": [{"message": f"An unexpected error occurred: {e}"}]}

@mcp.tool()
async def braintree_ping() -> str:
    """
    Performs a simple ping query to the Braintree GraphQL API to check connectivity and authentication.
    Returns 'pong' on success, or an error message.
    """
    print("Executing braintree_ping tool...")
    query = """
        query Ping {
            ping
        }
    """
    result = await make_braintree_request(query)

    if "errors" in result:
        # Format errors nicely for the LLM/user
        error_message = ", ".join([err.get("message", "Unknown error") for err in result["errors"]])
        return f"Error pinging Braintree: {error_message}"
    elif "data" in result and result["data"].get("ping") == "pong":
        return "pong"
    else:
        # Unexpected response structure
        return f"Unexpected response from Braintree ping: {json.dumps(result)}"

@mcp.tool()
async def braintree_execute_graphql(query: str, variables: Dict[str, Any] = None) -> str:
    """
    Executes an arbitrary GraphQL query or mutation against the Braintree API.
    This powerful tool provides unlimited flexibility for any Braintree GraphQL operation
    by directly passing queries with full control over selection sets and variables.
    
    ## GraphQL Introspection
    You can discover the Braintree API schema using GraphQL introspection queries such as:
    
    ```graphql
    # Get all available query types
    query IntrospectionQuery {
      __schema {
        queryType { name }
        types {
          name
          kind
          description
          fields {
            name
            description
            args {
              name
              description
              type { name kind }
            }
            type { name kind }
          }
        }
      }
    }
    
    # Get details for a specific type
    query TypeQuery {
      __type(name: "Transaction") {
        name
        description
        fields {
          name
          description
          type { name kind ofType { name kind } }
        }
      }
    }
    
    # Get input fields required for a specific mutation
    query InputTypeQuery {
      __type(name: "ChargePaymentMethodInput") {
        name
        description
        inputFields {
          name
          description
          type { name kind ofType { name kind } }
        }
      }
    }
    ```
    
    ## Common Operation Patterns
    
    ### Converting Legacy IDs to GraphQL IDs
    ```graphql
    query IdFromLegacyId($legacyId: ID!, $type: LegacyIdType!) {
      idFromLegacyId(legacyId: $legacyId, type: $type)
    }
    ```
    Variables: `{"legacyId": "123456", "type": "CUSTOMER"}`
    
    ### Fetching entities by ID
    ```graphql
    query GetEntity($id: ID!) {
      node(id: $id) {
        ... on Transaction { id status amount { value currencyCode } }
        ... on Customer { id firstName lastName email }
        ... on PaymentMethod { id details { ... on CreditCardDetails { last4 expirationMonth expirationYear } } }
      }
    }
    ```
    
    ### Creating transactions
    ```graphql
    mutation ChargePayment($input: ChargePaymentMethodInput!) {
      chargePaymentMethod(input: $input) {
        transaction { id status amount { value currencyCode } }
      }
    }
    ```
    Variables: `{"input": {"paymentMethodId": "abc123", "transaction": {"amount": "10.00"}}}`
    
    ### Searching
    ```graphql
    query SearchTransactions($input: TransactionSearchInput!, $first: Int!) {
      search {
        transactions(input: $input, first: $first) {
          pageInfo { hasNextPage endCursor }
          edges { node { id amount { value } status } }
        }
      }
    }
    ```
    Variables: `{"input": {"createdAt": {"greaterThanOrEqualTo": "2023-01-01T00:00:00Z"}}, "first": 50}`
    
    ## Pagination
    For paginated results, use the `after` parameter with the `endCursor` from previous queries:
    ```graphql
    query GetNextPage($input: TransactionSearchInput!, $first: Int!, $after: String) {
      search {
        transactions(input: $input, first: $first, after: $after) {
          pageInfo { hasNextPage endCursor }
          edges { node { id } }
        }
      }
    }
    ```
    
    ## Error Handling Tips
    - Check for the "errors" array in the response
    - Common error reasons:
      - Invalid GraphQL syntax: verify query structure
      - Unknown fields: check field names through introspection
      - Missing required fields: ensure all required fields are in queries
      - Permission issues: verify API keys have appropriate permissions
      - Legacy ID conversion: use idFromLegacyId for older IDs
    
    ## Variables Usage
    Variables should be provided as a Python dictionary where:
    - Keys match the variable names defined in the query/mutation
    - Values follow the appropriate data types expected by Braintree
    - Nested objects must be structured according to GraphQL input types
    
    Args:
        query: The complete GraphQL query or mutation to execute.
        variables: Optional dictionary of variables for the query. Should match 
                  the parameter names defined in the query with appropriate types.

    Returns:
        JSON string containing the complete response from Braintree, including data and errors if any.
    """
    print(f"Executing braintree_execute_graphql with query: {query[:100]}...")

    # Make the API call
    result = await make_braintree_request(query, variables)

    # Return the raw result as JSON
    return json.dumps(result)

if __name__ == "__main__":
     print("Attempting to run Braintree MCP server via stdio...")
     # Basic check before running
     if not all([BRAINTREE_MERCHANT_ID, BRAINTREE_PUBLIC_KEY, BRAINTREE_PRIVATE_KEY]):
          print("FATAL: Cannot start server, Braintree credentials missing.")
     else:
        print(f"Configured for Braintree Environment: {BRAINTREE_ENVIRONMENT}")
        try:
            mcp.run(transport='stdio')
            print("Server stopped.")
        except Exception as e:
            print(f"Error running server: {e}")