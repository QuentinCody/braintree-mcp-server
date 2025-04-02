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
BRAINTREE_API_VERSION = "2024-07-01" # Example, update as needed

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
    

# --- NEW TOOL ---
@mcp.tool()
async def braintree_get_graphql_id_from_legacy_id(legacy_id: str, legacy_id_type: str) -> str:
    """
    Retrieves the Braintree GraphQL ID corresponding to a given legacy ID and its type.

    Args:
        legacy_id: The legacy identifier (e.g., transaction ID, customer ID).
        legacy_id_type: The type of the legacy ID. Common values: TRANSACTION, CUSTOMER, PAYMENT_METHOD, SUBSCRIPTION, DISPUTE.
    """
    print(f"Executing braintree_get_graphql_id_from_legacy_id for ID: {legacy_id}, Type: {legacy_id_type}")

    # The GraphQL query provided
    query = """
        query IdFromLegacyId($legacyId: ID!, $type: LegacyIdType!) {
            idFromLegacyId(legacyId: $legacyId, type: $type)
        }
    """

    # The variables matching the query definition
    variables = {
        "legacyId": legacy_id,
        "type": legacy_id_type
    }

    # Make the API call
    result = await make_braintree_request(query, variables)

    # Process the response
    if "errors" in result:
        # Handle errors returned by the API (could be auth, network, or GraphQL errors)
        error_message = ", ".join([err.get("message", "Unknown error") for err in result["errors"]])
        return f"Error retrieving GraphQL ID: {error_message}"
    elif "data" in result and "idFromLegacyId" in result["data"]:
        graphql_id = result["data"]["idFromLegacyId"]
        if graphql_id:
            # Success case
            return graphql_id
        else:
            # The query succeeded but didn't find a corresponding ID (returned null)
            return f"No GraphQL ID found for legacy ID '{legacy_id}' of type '{legacy_id_type}'."
    else:
        # Unexpected response structure
        return f"Unexpected response structure from Braintree: {json.dumps(result)}"

# --- End of NEW TOOL ---


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