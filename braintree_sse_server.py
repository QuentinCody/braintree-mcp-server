"""
Braintree MCP Server with SSE Transport

This version of the Braintree MCP server uses Server-Sent Events (SSE) transport
for persistent, multi-client connections. This is meant for manual deployment as 
a standalone web server, not for use with Claude Desktop.

For Claude Desktop integration, use braintree_server.py which uses STDIO transport.
"""

import os
import httpx 
import base64 
import asyncio 
import json 
try:
    import orjson as json_lib  # Faster and more robust
except ImportError:
    import json as json_lib
from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP
from typing import Any, Dict, Union, List, Optional 

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

# Default host and port for the SSE server
DEFAULT_HOST = "127.0.0.1"  # Using localhost for security (prevent DNS rebinding attacks)
DEFAULT_PORT = 8001  # Changed from 8000 to avoid conflicts
DEFAULT_LOG_LEVEL = "INFO"

mcp = FastMCP("braintree", version="0.1.0")
print("Braintree MCP Server initialized.")

def sanitize_for_json(obj: Any, max_depth: int = 10, depth: int = 0) -> Any:
    """
    Recursively sanitize objects for JSON serialization by converting non-serializable
    objects to strings.
    
    Args:
        obj: The object to sanitize
        max_depth: Maximum recursion depth to prevent stack overflow
        depth: Current recursion depth
        
    Returns:
        JSON-serializable version of the object
    """
    if depth > max_depth:
        return str(obj)
    
    if isinstance(obj, dict):
        return {k: sanitize_for_json(v, max_depth, depth+1) for k, v in obj.items()}
    elif isinstance(obj, list) or isinstance(obj, tuple):
        return [sanitize_for_json(i, max_depth, depth+1) for i in obj]
    elif hasattr(obj, '__dict__') and not isinstance(obj, type):
        # Convert custom objects to dict representation
        return sanitize_for_json(obj.__dict__, max_depth, depth+1)
    else:
        # Handle common non-serializable types
        try:
            # Test if object is JSON serializable
            json_lib.dumps(obj)
            return obj
        except (TypeError, ValueError, OverflowError):
            # For specialized types that need specific formatting
            if hasattr(obj, 'isoformat'):  # datetime, date, time objects
                return obj.isoformat()
            else:
                return str(obj)

def safe_json_dumps(obj: Any, fallback_msg: str = "Non-serializable response") -> str:
    """
    Safely convert any object to a JSON string, handling non-serializable data.
    
    Args:
        obj: The object to serialize
        fallback_msg: Message to use if serialization fails
        
    Returns:
        JSON string or error message wrapped in a JSON object
    """
    try:
        return json_lib.dumps(obj)
    except (TypeError, ValueError, OverflowError) as e:
        print(f"JSON serialization error: {e}")
        # Try to sanitize the object first
        try:
            sanitized = sanitize_for_json(obj)
            # Convert back to standard json for consistent return type
            # (orjson returns bytes, standard json returns str)
            if isinstance(sanitized, bytes):
                return sanitized.decode('utf-8')
            return json.dumps(sanitized)
        except Exception as e2:
            print(f"Failed to sanitize non-serializable object: {e2}")
            return json.dumps({"error": fallback_msg})

def safe_json_parse(text: str, content_type: str = None) -> Dict[str, Any]:
    """
    Safely parse a JSON string, handling malformed JSON.
    
    Args:
        text: The string to parse
        content_type: Optional content-type header to validate
        
    Returns:
        Parsed JSON object or error dict
    """
    if not text or not isinstance(text, str):
        return {"errors": [{"message": "Empty or non-string response"}]}
    
    # Check content type if provided
    if content_type and 'application/json' not in content_type.lower():
        print(f"Warning: Content-Type is {content_type}, not application/json")
        # Additional checks for common API errors in non-JSON responses
        if 'text/html' in content_type.lower() and ('<html' in text[:1000].lower() or '<!doctype' in text[:1000].lower()):
            return {"errors": [{"message": "Received HTML instead of JSON - possible authentication or URL error", 
                               "context": text[:200] + ("..." if len(text) > 200 else "")}]}
    
    try:
        # Handle both orjson (returns bytes) and standard json
        if hasattr(json_lib, 'loads'):
            return json_lib.loads(text)
        else:
            # orjson.loads returns dict directly instead of loads method
            result = json_lib(text)
            if isinstance(result, bytes):
                result = result.decode('utf-8')
            return result
    except json.JSONDecodeError as e:
        print(f"JSON parse error at position {e.pos}: {e.msg}")
        # Try to provide context around the error position
        if len(text) > 20:
            context_start = max(0, e.pos - 10)
            context_end = min(len(text), e.pos + 10)
            error_context = text[context_start:context_end]
            problem_marker = "~" * (min(10, e.pos)) + "^" + "~" * (min(10, len(text) - e.pos - 1))
            print(f"Context: ...{error_context}...")
            print(f"Position: ...{problem_marker}...")
            
        return {
            "errors": [{
                "message": f"Invalid JSON response: {e.msg} at position {e.pos}",
                "context": text[:200] + ("..." if len(text) > 200 else "")
            }]
        }
    except Exception as e:
        print(f"Unexpected error parsing JSON: {e}")
        return {
            "errors": [{
                "message": f"Error parsing response: {str(e)}",
                "context": text[:200] + ("..." if len(text) > 200 else "")
            }]
        }

async def make_braintree_request(query: str, variables: Dict[str, Any] = None, max_retries: int = 2) -> Dict[str, Any]:
    """
    Makes an authenticated GraphQL request to the Braintree API.
    Handles basic authentication, error checking, and retries.
    
    Args:
        query: The GraphQL query or mutation to execute
        variables: Optional dictionary of variables for the query
        max_retries: Maximum number of retry attempts for recoverable errors
        
    Returns:
        Dictionary containing the API response or errors
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
        "Accept": "application/json",  # Explicitly request JSON
        "User-Agent": "MCPBraintreeServer/0.1.0" # Good practice
    }

    payload = {"query": query}
    if variables:
        payload["variables"] = variables

    # Initialize retry counter and results
    attempts = 0
    last_exception = None
    backoff_time = 1.0  # Start with 1 second backoff

    while attempts <= max_retries:
        try:
            print(f"Sending request to Braintree (attempt {attempts+1}/{max_retries+1}): {query[:100]}...")
            
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    BRAINTREE_API_URL,
                    headers=headers,
                    json=payload,
                    timeout=30.0
                )
                
                # Check status code first
                if response.status_code >= 500 and attempts < max_retries:
                    print(f"Server error {response.status_code}, retrying after {backoff_time}s")
                    await asyncio.sleep(backoff_time)
                    attempts += 1
                    backoff_time *= 2  # Exponential backoff
                    continue
                
                response.raise_for_status() # Raise HTTP errors (4xx, 5xx)
                print(f"Braintree response status: {response.status_code}")
                
                # Get content type for better parsing
                content_type = response.headers.get('content-type', '')
                
                # Safely handle response body - could be invalid JSON
                response_text = response.text
                result = safe_json_parse(response_text, content_type)
                
                # Check for GraphQL errors that might benefit from retry
                if "errors" in result:
                    print(f"GraphQL Errors: {result['errors']}")
                    
                    # Check if these are retryable errors (rate limiting, temporary issues)
                    retryable = False
                    for error in result.get("errors", []):
                        error_msg = error.get("message", "").lower()
                        # Common retryable error messages
                        if any(msg in error_msg for msg in ["rate limit", "too many requests", "timeout", "temporary"]):
                            retryable = True
                            break
                    
                    if retryable and attempts < max_retries:
                        print(f"Retryable error detected, retrying after {backoff_time}s")
                        await asyncio.sleep(backoff_time)
                        attempts += 1
                        backoff_time *= 2  # Exponential backoff
                        continue
                
                return result
                
        except httpx.RequestError as e:
            print(f"HTTP Request Error: {e}")
            last_exception = e
            
            # Only retry on connection errors, not request formation errors
            if attempts < max_retries:
                print(f"Connection error, retrying after {backoff_time}s")
                await asyncio.sleep(backoff_time)
                attempts += 1
                backoff_time *= 2  # Exponential backoff
                continue
                
            return {"errors": [{"message": f"HTTP Request Error connecting to Braintree: {e}"}]}
            
        except httpx.HTTPStatusError as e:
            print(f"HTTP Status Error: {e.response.status_code} - {e.response.text}")
            last_exception = e
            
            # Don't retry client errors (4xx) except for 429 Too Many Requests
            if e.response.status_code == 429 and attempts < max_retries:
                # Parse retry-after header if available
                retry_after = e.response.headers.get('retry-after')
                wait_time = float(retry_after) if retry_after and retry_after.isdigit() else backoff_time
                print(f"Rate limited, retrying after {wait_time}s")
                await asyncio.sleep(wait_time)
                attempts += 1
                backoff_time *= 2  # Exponential backoff
                continue
            elif e.response.status_code >= 500 and attempts < max_retries:
                print(f"Server error, retrying after {backoff_time}s")
                await asyncio.sleep(backoff_time)
                attempts += 1
                backoff_time *= 2  # Exponential backoff
                continue
                
            error_detail = f"HTTP Status Error: {e.response.status_code}"
            try:
                # Try to parse Braintree's error response if JSON
                content_type = e.response.headers.get('content-type', '')
                err_resp = safe_json_parse(e.response.text, content_type)
                if "errors" in err_resp:
                    error_detail += f" - {err_resp['errors'][0]['message']}"
                elif "error" in err_resp and "message" in err_resp["error"]:
                    error_detail += f" - {err_resp['error']['message']}"
                else:
                    error_detail += f" - Response: {e.response.text[:200]}"
            except Exception:
                error_detail += f" - Response: {e.response.text[:200]}"

            return {"errors": [{"message": error_detail}]}
            
        except Exception as e:
            print(f"Generic Error during Braintree request: {e}")
            last_exception = e
            
            if attempts < max_retries:
                print(f"Unexpected error, retrying after {backoff_time}s")
                await asyncio.sleep(backoff_time)
                attempts += 1
                backoff_time *= 2  # Exponential backoff
                continue
                
            return {"errors": [{"message": f"An unexpected error occurred: {e}"}]}
    
    # If we've exhausted all retries and still have errors
    if last_exception:
        return {"errors": [{"message": f"Failed after {max_retries} retries. Last error: {last_exception}"}]}
    else:
        return {"errors": [{"message": "Failed after retries with unknown error"}]}

@mcp.tool()
async def braintree_sse_ping(random_string: str = "") -> str:
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
    try:
        result = await make_braintree_request(query, max_retries=1)

        if "errors" in result:
            # Format errors nicely for the LLM/user
            error_message = ", ".join([err.get("message", "Unknown error") for err in result["errors"]])
            return f"Error pinging Braintree: {error_message}"
        elif "data" in result and result["data"].get("ping") == "pong":
            return "pong"
        else:
            # Unexpected response structure
            return f"Unexpected response from Braintree ping: {safe_json_dumps(result)}"
    except Exception as e:
        print(f"Error in braintree_ping: {e}")
        return f"Error connecting to Braintree: {sanitize_for_json(e)}"

@mcp.tool()
async def braintree_execute_graphql_sse(query: str, variables: Dict[str, Any] = None) -> str:
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

    try:
        # Validate query is not empty
        if not query or not isinstance(query, str):
            return json.dumps({"errors": [{"message": "Query cannot be empty and must be a string"}]})
            
        # Basic GraphQL query validation
        query = query.strip()
        if not (query.startswith('query') or query.startswith('mutation') or query.startswith('{')):
            return json.dumps({"errors": [{"message": "Invalid GraphQL query format. Must start with 'query', 'mutation', or '{'"}]})
        
        # Make the API call with retry logic
        result = await make_braintree_request(query, variables, max_retries=2)
        
        # Return the raw result as JSON using safe serialization
        return safe_json_dumps(result)
    except Exception as e:
        print(f"Error in braintree_execute_graphql: {e}")
        # Use sanitization to handle the exception
        error_obj = {"errors": [{"message": f"Error executing GraphQL: {sanitize_for_json(e)}"}]}
        return safe_json_dumps(error_obj)

if __name__ == "__main__":
    import sys
    
    # Check if being run by Claude Desktop
    is_claude_desktop = True
    
    # Print diagnostic information to stderr so Claude Desktop can capture it
    print("Braintree SSE MCP Server initializing...", file=sys.stderr)
    
    # Basic check before running
    if not all([BRAINTREE_MERCHANT_ID, BRAINTREE_PUBLIC_KEY, BRAINTREE_PRIVATE_KEY]):
        print("FATAL: Cannot start server, Braintree credentials missing.", file=sys.stderr)
    else:
        print(f"Configured for Braintree Environment: {BRAINTREE_ENVIRONMENT}", file=sys.stderr)
        print(f"Starting SSE server on {DEFAULT_HOST}:{DEFAULT_PORT}", file=sys.stderr)
        try:
            # Use a different port to avoid conflicts
            os.environ["FASTMCP_SSE_HOST"] = DEFAULT_HOST
            os.environ["FASTMCP_SSE_PORT"] = str(DEFAULT_PORT)
            os.environ["FASTMCP_LOG_LEVEL"] = DEFAULT_LOG_LEVEL
            
            if is_claude_desktop:
                print("Detected Claude Desktop environment, using appropriate transport", file=sys.stderr)
                # When running in Claude Desktop, let it decide the transport type
                mcp.run()
            else:
                # For manual standalone usage with SSE
                print("Running with SSE transport on port {DEFAULT_PORT}", file=sys.stderr)
                mcp.run(transport='sse')
                
            print("Server stopped.", file=sys.stderr)
        except Exception as e:
            print(f"Error running server: {e}", file=sys.stderr) 