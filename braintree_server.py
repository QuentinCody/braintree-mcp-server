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


# --- NEW TOOL ---
@mcp.tool()
async def braintree_get_graphql_id_from_legacy_id(legacyId: str, legacyIdType: str) -> str:
    """
    Retrieves the Braintree GraphQL ID corresponding to a given legacy ID and its type.

    Args:
        legacyId: The legacy identifier (e.g., transaction ID, customer ID).
        legacyIdType: The type of the legacy ID. Common values: TRANSACTION, CUSTOMER, PAYMENT_METHOD, SUBSCRIPTION, DISPUTE.
    """
    print(f"Executing braintree_get_graphql_id_from_legacy_id for ID: {legacyId}, Type: {legacyIdType}")

    # The GraphQL query provided
    query = """
        query IdFromLegacyId($legacyId: ID!, $type: LegacyIdType!) {
            idFromLegacyId(legacyId: $legacyId, type: $type)
        }
    """

    # The variables matching the query definition
    variables = {
        "legacyId": legacyId,
        "type": legacyIdType
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
            return f"No GraphQL ID found for legacy ID '{legacyId}' of type '{legacyIdType}'."
    else:
        # Unexpected response structure
        return f"Unexpected response structure from Braintree: {json.dumps(result)}"

# --- End of NEW TOOL ---

@mcp.tool()
async def braintree_get_transactions_by_date(date: str) -> str:
    """
    Retrieves all transactions from Braintree for a specific date.

    Args:
        date: The date to retrieve transactions for, in YYYY-MM-DD format.

    Returns:
        JSON string containing the transactions for the specified date.
    """
    print(f"Executing braintree_get_transactions_by_date for date: {date}")

    # Create the start and end datetime for the specified date (midnight to midnight)
    start_datetime = f"{date}T00:00:00Z"
    end_datetime = f"{date}T23:59:59Z"

    # The GraphQL query for searching transactions by date
    query = """
        query TransactionsByDate($input: TransactionSearchInput!, $first: Int!, $after: String) {
            search {
                transactions(input: $input, first: $first, after: $after) {
                    pageInfo {
                        hasNextPage
                        endCursor
                    }
                    edges {
                        node {
                            id
                            legacyId
                            amount {
                                value
                                currencyCode
                            }
                            status
                            createdAt
                            paymentMethodSnapshot {
                                __typename
                                ... on CreditCardDetails {
                                    bin
                                    last4
                                    expirationMonth
                                    expirationYear
                                }
                            }
                            customer {
                                id
                                firstName
                                lastName
                                email
                            }
                        }
                    }
                }
            }
        }
    """

    # Variables for the GraphQL query - updated to use lessThanOrEqualTo/greaterThanOrEqualTo
    variables = {
        "input": {
            "createdAt": {
                "lessThanOrEqualTo": end_datetime,
                "greaterThanOrEqualTo": start_datetime
            }
        },
        "first": 50  # Fetch exactly 50 transactions
    }

    # Collect transactions (single page only)
    all_transactions = []

    print("Fetching transactions...")
    result = await make_braintree_request(query, variables)

    # Check for errors
    if "errors" in result:
        error_message = ", ".join([err.get("message", "Unknown error") for err in result["errors"]])
        return f"Error retrieving transactions: {error_message}"

    # Extract transactions data
    try:
        transactions_data = result["data"]["search"]["transactions"]
        all_transactions = [edge["node"] for edge in transactions_data["edges"]]
        print(f"Retrieved {len(all_transactions)} transactions")
    except (KeyError, TypeError) as e:
        print(f"Error parsing transaction data: {e}")
        return f"Error parsing transaction data: {e}. Response: {json.dumps(result)}"

    # Format and return the transactions
    return json.dumps({
        "date": date,
        "transaction_count": len(all_transactions),
        "transactions": all_transactions
    })

@mcp.tool()
async def braintree_get_transaction_by_id(transactionId: str) -> str:
    """
    Retrieves a transaction by its ID using Braintree's node query.
    The ID can be a legacy ID or a GraphQL ID.

    If this tool fails with the provided ID, try using braintree_get_graphql_id_from_legacy_id 
    with type "TRANSACTION" to convert a legacy ID to a GraphQL ID, then try this tool again with the GraphQL ID.

    Args:
        transactionId: The ID of the transaction to retrieve.

    Returns:
        JSON string containing the transaction details.
    """
    print(f"Executing braintree_get_transaction_by_id for transaction: {transactionId}")

    # Prepare the GraphQL query for transaction details
    query = """
        query GetTransaction($id: ID!) {
            node(id: $id) {
                ... on Transaction {
                    id
                    legacyId
                    status
                    amount {
                        value
                        currencyCode
                    }
                    createdAt
                    paymentMethodSnapshot {
                        __typename
                        ... on CreditCardDetails {
                            bin
                            last4
                            expirationMonth
                            expirationYear
                        }
                    }
                    customer {
                        id
                        firstName
                        lastName
                        email
                    }
                }
            }
        }
    """

    variables = {
        "id": transactionId # Use the provided ID directly
    }

    # Make the API call
    result = await make_braintree_request(query, variables)

    # Process the response
    if "errors" in result:
        error_message = ", ".join([err.get("message", "Unknown error") for err in result["errors"]])
        return json.dumps({
            "success": False,
            "error": error_message
        })

    try:
        transaction_data = result.get("data", {}).get("node")

        if transaction_data is None:
            return json.dumps({
                "success": False,
                "error": f"Transaction with ID '{transactionId}' not found or is not a transaction."
            })

        return json.dumps({
            "success": True,
            "transaction": transaction_data
        })

    except (KeyError, TypeError) as e:
        return json.dumps({
            "success": False,
            "error": f"Error processing transaction data: {e}",
            "raw_response": result
        })

@mcp.tool()
async def braintree_charge_payment_method(paymentMethodId: str, amount: str, currencyCode: str = "USD", orderId: str = None) -> str:
    """
    Creates a transaction and immediately submits it for settlement using a payment method.
    The paymentMethodId can be a legacy ID or a GraphQL ID.

    If this tool fails with the provided ID, try using braintree_get_graphql_id_from_legacy_id 
    with type "PAYMENT_METHOD" to convert a legacy ID to a GraphQL ID, then try this tool again with the GraphQL ID.

    Args:
        paymentMethodId: The ID of the payment method to charge.
        amount: The amount to charge (e.g. "10.00").
        currencyCode: The currency code (default: "USD").
        orderId: Optional order ID for the transaction.

    Returns:
        JSON string containing the transaction details or error information.
    """
    print(f"Executing braintree_charge_payment_method for payment method: {paymentMethodId}, amount: {amount}")

    # Prepare the GraphQL mutation
    mutation = """
        mutation ChargePaymentMethod($input: ChargePaymentMethodInput!) {
            chargePaymentMethod(input: $input) {
                transaction {
                    id
                    legacyId
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

    # Prepare the variables
    variables = {
        "input": {
            "paymentMethodId": paymentMethodId, # Use the provided ID directly
            "transaction": {
                "amount": amount
            }
        }
    }

    # Add optional fields if provided
    if currencyCode and currencyCode != "USD":
        variables["input"]["transaction"]["currencyCode"] = currencyCode

    if orderId:
        variables["input"]["transaction"]["orderId"] = orderId

    print(f"Charging payment method {paymentMethodId} for {amount} {currencyCode}")

    # Make the API call
    result = await make_braintree_request(mutation, variables)

    # Process the response
    if "errors" in result:
        error_message = ", ".join([err.get("message", "Unknown error") for err in result["errors"]])
        print(f"Error processing payment: {error_message}")
        return json.dumps({
            "success": False,
            "error": error_message
        })

    try:
        transaction_data = result["data"]["chargePaymentMethod"]["transaction"]
        return json.dumps({
            "success": True,
            "transaction": transaction_data
        })
    except (KeyError, TypeError) as e:
        print(f"Error extracting transaction data: {e}")
        return json.dumps({
            "success": False,
            "error": f"Error extracting transaction data: {e}",
            "raw_response": result
        })

@mcp.tool()
async def braintree_authorize_payment_method(paymentMethodId: str, amount: str, currencyCode: str = "USD", orderId: str = None) -> str:
    """
    Creates a transaction but doesn't submit it for settlement yet. The funds are put on hold.
    The paymentMethodId can be a legacy ID or a GraphQL ID.

    If this tool fails with the provided ID, try using braintree_get_graphql_id_from_legacy_id 
    with type "PAYMENT_METHOD" to convert a legacy ID to a GraphQL ID, then try this tool again with the GraphQL ID.

    Args:
        paymentMethodId: The ID of the payment method to authorize.
        amount: The amount to authorize (e.g. "10.00").
        currencyCode: The currency code (default: "USD").
        orderId: Optional order ID for the transaction.

    Returns:
        JSON string containing the transaction details or error information.
    """
    print(f"Executing braintree_authorize_payment_method for payment method: {paymentMethodId}, amount: {amount}")

    # Prepare the GraphQL mutation
    mutation = """
        mutation AuthorizePaymentMethod($input: AuthorizePaymentMethodInput!) {
            authorizePaymentMethod(input: $input) {
                transaction {
                    id
                    legacyId
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

    # Prepare the variables
    variables = {
        "input": {
            "paymentMethodId": paymentMethodId, # Use the provided ID directly
            "transaction": {
                "amount": amount
            }
        }
    }

    # Add optional fields if provided
    if currencyCode and currencyCode != "USD":
        variables["input"]["transaction"]["currencyCode"] = currencyCode

    if orderId:
        variables["input"]["transaction"]["orderId"] = orderId

    # Make the API call
    result = await make_braintree_request(mutation, variables)

    # Process the response
    if "errors" in result:
        error_message = ", ".join([err.get("message", "Unknown error") for err in result["errors"]])
        return json.dumps({
            "success": False,
            "error": error_message
        })

    try:
        transaction_data = result["data"]["authorizePaymentMethod"]["transaction"]
        return json.dumps({
            "success": True,
            "transaction": transaction_data
        })
    except (KeyError, TypeError) as e:
        return json.dumps({
            "success": False,
            "error": f"Unexpected response structure: {e}",
            "raw_response": result
        })

@mcp.tool()
async def braintree_capture_transaction(transactionId: str) -> str:
    """
    Captures an authorized transaction, submitting it for settlement.
    The transactionId can be a legacy ID or a GraphQL ID.

    If this tool fails with the provided ID, try using braintree_get_graphql_id_from_legacy_id 
    with type "TRANSACTION" to convert a legacy ID to a GraphQL ID, then try this tool again with the GraphQL ID.

    Args:
        transactionId: The ID of the authorized transaction to capture.

    Returns:
        JSON string containing the transaction details or error information.
    """
    print(f"Executing braintree_capture_transaction for transaction: {transactionId}")

    # Prepare the GraphQL mutation
    mutation = """
        mutation CaptureTransaction($input: CaptureTransactionInput!) {
            captureTransaction(input: $input) {
                transaction {
                    id
                    legacyId
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

    # Prepare the variables
    variables = {
        "input": {
            "transactionId": transactionId # Use the provided ID directly
        }
    }

    # Make the API call
    result = await make_braintree_request(mutation, variables)

    # Process the response
    if "errors" in result:
        error_message = ", ".join([err.get("message", "Unknown error") for err in result["errors"]])
        return json.dumps({
            "success": False,
            "error": error_message
        })

    try:
        transaction_data = result["data"]["captureTransaction"]["transaction"]
        return json.dumps({
            "success": True,
            "transaction": transaction_data
        })
    except (KeyError, TypeError) as e:
        return json.dumps({
            "success": False,
            "error": f"Unexpected response structure: {e}",
            "raw_response": result
        })

@mcp.tool()
async def braintree_partial_capture_transaction(transactionId: str, amount: str) -> str:
    """
    Captures part of an authorized transaction, submitting that portion for settlement.
    The transactionId can be a legacy ID or a GraphQL ID.

    If this tool fails with the provided ID, try using braintree_get_graphql_id_from_legacy_id 
    with type "TRANSACTION" to convert a legacy ID to a GraphQL ID, then try this tool again with the GraphQL ID.

    Args:
        transactionId: The ID of the authorized transaction to partially capture.
        amount: The amount to capture (must be less than the original authorized amount).

    Returns:
        JSON string containing the transaction details or error information.
    """
    print(f"Executing braintree_partial_capture_transaction for transaction: {transactionId}, amount: {amount}")

    # Prepare the GraphQL mutation
    mutation = """
        mutation PartialCaptureTransaction($input: PartialCaptureTransactionInput!) {
            partialCaptureTransaction(input: $input) {
                capture {
                    id
                    legacyId
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

    # Prepare the variables
    variables = {
        "input": {
            "transactionId": transactionId, # Use the provided ID directly
            "transaction": {
                "amount": amount
            }
        }
    }

    # Make the API call
    result = await make_braintree_request(mutation, variables)

    # Process the response
    if "errors" in result:
        error_message = ", ".join([err.get("message", "Unknown error") for err in result["errors"]])
        return json.dumps({
            "success": False,
            "error": error_message
        })

    try:
        transaction_data = result["data"]["partialCaptureTransaction"]["capture"]
        return json.dumps({
            "success": True,
            "transaction": transaction_data
        })
    except (KeyError, TypeError) as e:
        return json.dumps({
            "success": False,
            "error": f"Unexpected response structure: {e}",
            "raw_response": result
        })

@mcp.tool()
async def braintree_reverse_transaction(transactionId: str) -> str:
    """
    Reverses a transaction by either voiding or refunding it depending on its settlement status.
    The transactionId can be a legacy ID or a GraphQL ID.

    If this tool fails with the provided ID, try using braintree_get_graphql_id_from_legacy_id 
    with type "TRANSACTION" to convert a legacy ID to a GraphQL ID, then try this tool again with the GraphQL ID.

    Args:
        transactionId: The ID of the transaction to reverse.

    Returns:
        JSON string containing the reversal details or error information.
    """
    print(f"Executing braintree_reverse_transaction for transaction: {transactionId}")

    # Prepare the GraphQL mutation
    mutation = """
        mutation ReverseTransaction($input: ReverseTransactionInput!) {
            reverseTransaction(input: $input) {
                reversal {
                    ... on Transaction {
                        id
                        legacyId
                        status
                        amount {
                            value
                            currencyCode
                        }
                        createdAt
                    }
                    ... on Refund {
                        id
                        legacyId
                        amount {
                            value
                            currencyCode
                        }
                        status
                        createdAt
                        refundedTransaction {
                            id
                            legacyId
                        }
                    }
                }
            }
        }
    """

    # Prepare the variables
    variables = {
        "input": {
            "transactionId": transactionId # Use the provided ID directly
        }
    }

    # Make the API call
    result = await make_braintree_request(mutation, variables)

    # Process the response
    if "errors" in result:
        error_message = ", ".join([err.get("message", "Unknown error") for err in result["errors"]])
        return json.dumps({
            "success": False,
            "error": error_message
        })

    try:
        reversal_data = result["data"]["reverseTransaction"]["reversal"]
        return json.dumps({
            "success": True,
            "reversal": reversal_data
        })
    except (KeyError, TypeError) as e:
        return json.dumps({
            "success": False,
            "error": f"Unexpected response structure: {e}",
            "raw_response": result
        })

@mcp.tool()
async def braintree_refund_transaction(transactionId: str, amount: str = None, orderId: str = None) -> str:
    """
    Refunds a settled transaction, either fully or partially.
    The transactionId can be a legacy ID or a GraphQL ID.

    If this tool fails with the provided ID, try using braintree_get_graphql_id_from_legacy_id 
    with type "TRANSACTION" to convert a legacy ID to a GraphQL ID, then try this tool again with the GraphQL ID.

    Args:
        transactionId: The ID of the transaction to refund.
        amount: Optional amount to refund. If not provided, the entire transaction is refunded.
        orderId: Optional order ID for the refund transaction.

    Returns:
        JSON string containing the refund details or error information.
    """
    print(f"Executing braintree_refund_transaction for transaction: {transactionId}, amount: {amount}")

    # Prepare the GraphQL mutation
    mutation = """
        mutation RefundTransaction($input: RefundTransactionInput!) {
            refundTransaction(input: $input) {
                refund {
                    id
                    legacyId
                    status
                    amount {
                        value
                        currencyCode
                    }
                    createdAt
                    refundedTransaction {
                        id
                        legacyId
                    }
                }
            }
        }
    """

    # Prepare the variables
    variables = {
        "input": {
            "transactionId": transactionId # Use the provided ID directly
        }
    }

    # Add optional refund details if provided
    if amount or orderId:
        variables["input"]["refund"] = {}

        if amount:
            variables["input"]["refund"]["amount"] = amount

        if orderId:
            variables["input"]["refund"]["orderId"] = orderId

    # Make the API call
    result = await make_braintree_request(mutation, variables)

    # Process the response
    if "errors" in result:
        error_message = ", ".join([err.get("message", "Unknown error") for err in result["errors"]])
        return json.dumps({
            "success": False,
            "error": error_message
        })

    try:
        refund_data = result["data"]["refundTransaction"]["refund"]
        return json.dumps({
            "success": True,
            "refund": refund_data
        })
    except (KeyError, TypeError) as e:
        return json.dumps({
            "success": False,
            "error": f"Unexpected response structure: {e}",
            "raw_response": result
        })

@mcp.tool()
async def braintree_execute_graphql(query: str, variables: Dict[str, Any] = None) -> str:
    """
    Executes an arbitrary GraphQL query or mutation against the Braintree API.
    This provides flexibility for complex or custom GraphQL operations.

    Args:
        query: The GraphQL query or mutation to execute.
        variables: Optional dictionary of variables for the query.

    Returns:
        JSON string containing the response from Braintree.
    """
    print(f"Executing braintree_execute_graphql with query: {query[:100]}...")

    # Make the API call
    result = await make_braintree_request(query, variables)

    # Return the raw result as JSON
    return json.dumps(result)

@mcp.tool()
async def braintree_find_customer_by_name(firstName: str = None, lastName: str = None, email: str = None) -> str:
    """
    Searches for customers by first name, last name, and/or email using Braintree's customer search.
    At least one parameter must be provided.

    Args:
        firstName: The customer's first name
        lastName: The customer's last name
        email: The customer's email address

    Returns:
        JSON string containing the matching customers with their IDs and basic info.
    """
    print(f"Executing braintree_find_customer_by_name - First Name: {firstName}, Last Name: {lastName}, Email: {email}")

    if not any([firstName, lastName, email]):
        return json.dumps({
            "success": False,
            "error": "At least one search parameter (firstName, lastName, or email) must be provided."
        })

    # Construct the search input with provided fields
    search_input = {}
    if firstName:
        search_input["firstName"] = {"contains": firstName}
    if lastName:
        search_input["lastName"] = {"contains": lastName}
    if email:
        search_input["email"] = {"contains": email}

    # Build the GraphQL query with the search criteria
    query = """
        query SearchCustomers($input: CustomerSearchInput!) {
            search {
                customers(input: $input, first: 10) {
                    edges {
                        node {
                            id
                            legacyId
                            firstName
                            lastName
                            email
                            company
                            createdAt
                        }
                    }
                }
            }
        }
    """

    variables = {"input": search_input}
    
    # Make the API call
    result = await make_braintree_request(query, variables)

    # Process the response
    if "errors" in result:
        error_message = ", ".join([err.get("message", "Unknown error") for err in result["errors"]])
        return json.dumps({
            "success": False,
            "error": error_message
        })

    try:
        customers_data = result.get("data", {}).get("search", {}).get("customers", {}).get("edges", [])
        customers = [edge["node"] for edge in customers_data]
        
        if not customers:
            return json.dumps({
                "success": False,
                "error": "No customers found matching the provided criteria.",
                "search_criteria": {
                    "firstName": firstName,
                    "lastName": lastName,
                    "email": email
                }
            })
        
        return json.dumps({
            "success": True,
            "customers": customers,
            "count": len(customers)
        })
    except Exception as e:
        return json.dumps({
            "success": False,
            "error": f"Error processing customer search results: {e}",
            "raw_response": result
        })

@mcp.tool()
async def braintree_get_customer_details(customerId: str) -> str:
    """
    Retrieves detailed information about a specific customer by ID.
    The customerId can be a legacy ID or a GraphQL ID.

    If this tool fails with the provided ID, try using braintree_get_graphql_id_from_legacy_id 
    with type "CUSTOMER" to convert a legacy ID to a GraphQL ID, then try this tool again with the GraphQL ID.

    Args:
        customerId: The Braintree ID of the customer.

    Returns:
        JSON string containing the customer details including contact info and payment methods.
    """
    print(f"Executing braintree_get_customer_details for customer: {customerId}")

    # Prepare the GraphQL query for customer details including payment methods
    query = """
        query GetCustomerDetails($id: ID!) {
            node(id: $id) {
                ... on Customer {
                    id
                    legacyId
                    firstName
                    lastName
                    email
                    company
                    createdAt
                    website
                    paymentMethods {
                        edges {
                            node {
                                id
                                legacyId
                                details {
                                    ... on CreditCardDetails {
                                        bin
                                        brand
                                        last4
                                        expirationMonth
                                        expirationYear
                                        cardholderName
                                    }
                                    ... on PayPalAccountDetails {
                                        email
                                    }
                                }
                            }
                        }
                    }
                }
            }
        }
    """

    variables = {
        "id": customerId # Use the provided ID directly
    }

    # Make the API call
    result = await make_braintree_request(query, variables)
    print(f"Customer details result: {json.dumps(result)[:200]}...")

    # Process the response
    if "errors" in result:
        error_message = ", ".join([err.get("message", "Unknown error") for err in result["errors"]])
        print(f"Error retrieving customer details: {error_message}")
        return json.dumps({
            "success": False,
            "error": error_message
        })

    try:
        customer_data = result.get("data", {}).get("node")

        if customer_data is None:
            print(f"Customer with ID '{customerId}' not found or is not a customer.")
            return json.dumps({
                "success": False,
                "error": f"Customer with ID '{customerId}' not found or is not a customer."
            })

        print(f"Found customer: {customer_data.get('firstName')} {customer_data.get('lastName')}")

        # Format payment methods for easier consumption
        if "paymentMethods" in customer_data and customer_data["paymentMethods"] is not None:
             payment_methods = [edge["node"] for edge in customer_data["paymentMethods"]["edges"]]
             customer_data["paymentMethods"] = payment_methods
             print(f"Found {len(payment_methods)} payment methods for customer")
        else:
             customer_data["paymentMethods"] = [] # Ensure key exists even if null/empty
             print("No payment methods found for customer")


        return json.dumps({
            "success": True,
            "customer": customer_data
        })
    except (KeyError, TypeError) as e:
        print(f"Error processing customer data: {e}")
        return json.dumps({
            "success": False,
            "error": f"Error processing customer data: {e}",
            "raw_response": result
        })

@mcp.tool()
async def braintree_get_customer_payment_methods(customerId: str) -> str:
    """
    Retrieves all payment methods associated with a customer.
    The customerId can be a legacy ID or a GraphQL ID.

    If this tool fails with the provided ID, try using braintree_get_graphql_id_from_legacy_id 
    with type "CUSTOMER" to convert a legacy ID to a GraphQL ID, then try this tool again with the GraphQL ID.

    Args:
        customerId: The Braintree ID of the customer.

    Returns:
        JSON string containing the customer's payment methods with details.
    """
    print(f"Executing braintree_get_customer_payment_methods for customer: {customerId}")

    # Prepare the GraphQL query for payment methods
    query = """
        query GetCustomerPaymentMethods($id: ID!) {
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
                                legacyId
                                details {
                                    ... on CreditCardDetails {
                                        bin
                                        brand
                                        last4
                                        expirationMonth
                                        expirationYear
                                        cardholderName
                                    }
                                    ... on PayPalAccountDetails {
                                        email
                                    }
                                }
                            }
                        }
                    }
                }
            }
        }
    """

    variables = {
        "id": customerId # Use the provided ID directly
    }

    # Make the API call
    result = await make_braintree_request(query, variables)
    print(f"Payment methods query result: {json.dumps(result)[:200]}...")

    # Process the response
    if "errors" in result:
        error_message = ", ".join([err.get("message", "Unknown error") for err in result["errors"]])
        print(f"Error retrieving payment methods: {error_message}")
        return json.dumps({
            "success": False,
            "error": error_message
        })

    try:
        customer_node = result.get("data", {}).get("node")

        if customer_node is None:
            print(f"Customer with ID '{customerId}' not found or is not a customer.")
            return json.dumps({
                "success": False,
                "error": f"Customer with ID '{customerId}' not found or is not a customer."
            })

        print(f"Found customer: {customer_node.get('firstName')} {customer_node.get('lastName')}")

        # Format payment methods for easier consumption
        payment_methods = []
        if "paymentMethods" in customer_node and customer_node["paymentMethods"] is not None:
            payment_methods = [edge["node"] for edge in customer_node["paymentMethods"]["edges"]]
            print(f"Found {len(payment_methods)} payment methods for customer")
        else:
            print("No payment methods found for customer")


        return json.dumps({
            "success": True,
            "customer": {
                "id": customer_node["id"],
                "firstName": customer_node.get("firstName"),
                "lastName": customer_node.get("lastName"),
                "email": customer_node.get("email")
            },
            "payment_methods": payment_methods,
            "payment_method_count": len(payment_methods)
        })
    except (KeyError, TypeError) as e:
        print(f"Error processing payment methods data: {e}")
        return json.dumps({
            "success": False,
            "error": f"Error processing payment methods data: {e}",
            "raw_response": result
        })

@mcp.tool()
async def braintree_get_payment_method_by_id(paymentMethodId: str) -> str:
    """
    Retrieves a specific payment method by its ID.
    The paymentMethodId can be a legacy ID or a GraphQL ID.

    If this tool fails with the provided ID, try using braintree_get_graphql_id_from_legacy_id 
    with type "PAYMENT_METHOD" to convert a legacy ID to a GraphQL ID, then try this tool again with the GraphQL ID.

    Args:
        paymentMethodId: The Braintree ID or token of the payment method

    Returns:
        JSON string containing the payment method details.
    """
    print(f"Executing braintree_get_payment_method_by_id for payment method: {paymentMethodId}")

    # Prepare the GraphQL query for payment method details
    query = """
        query GetPaymentMethod($id: ID!) {
            node(id: $id) {
                ... on PaymentMethod {
                    id
                    legacyId
                    details {
                        ... on CreditCardDetails {
                            bin
                            brand
                            last4
                            expirationMonth
                            expirationYear
                            cardholderName
                        }
                        ... on PayPalAccountDetails {
                            email
                        }
                    }
                    customer {
                        id
                        firstName
                        lastName
                        email
                    }
                }
            }
        }
    """

    variables = {
        "id": paymentMethodId # Use the provided ID directly
    }

    # Make the API call
    result = await make_braintree_request(query, variables)

    # Process the response
    if "errors" in result:
        error_message = ", ".join([err.get("message", "Unknown error") for err in result["errors"]])
        print(f"Error retrieving payment method: {error_message}")
        return json.dumps({
            "success": False,
            "error": error_message
        })

    try:
        payment_method_data = result.get("data", {}).get("node")

        if payment_method_data is None:
            print(f"Payment method with ID '{paymentMethodId}' not found or is not a payment method.")
            return json.dumps({
                "success": False,
                "error": f"Payment method with ID '{paymentMethodId}' not found or is not a payment method."
            })

        return json.dumps({
            "success": True,
            "payment_method": payment_method_data
        })
    except (KeyError, TypeError) as e:
        print(f"Error processing payment method data: {e}")
        return json.dumps({
            "success": False,
            "error": f"Error processing payment method data: {e}",
            "raw_response": result
        })

@mcp.tool()
async def braintree_get_customer_by_id(customerId: str) -> str:
    """
    Retrieves a customer by their ID using Braintree's node query.
    The customerId can be a legacy ID or a GraphQL ID.

    If this tool fails with the provided ID, try using braintree_get_graphql_id_from_legacy_id 
    with type "CUSTOMER" to convert a legacy ID to a GraphQL ID, then try this tool again with the GraphQL ID.

    Args:
        customerId: The GraphQL ID or legacy ID of the customer to retrieve.

    Returns:
        JSON string containing the customer details.
    """
    print(f"Executing braintree_get_customer_by_id for customer: {customerId}")

    # Prepare the GraphQL query for customer details
    query = """
        query GetCustomer($id: ID!) {
            node(id: $id) {
                ... on Customer {
                    id
                    legacyId
                    firstName
                    lastName
                    email
                    company
                    website
                    createdAt
                    customFields {
                        name
                        value
                    }
                    addresses {
                        edges {
                            node {
                                id
                                addressLine1
                                addressLine2
                                adminArea1
                                adminArea2
                                postalCode
                                countryCode
                            }
                        }
                    }
                }
            }
        }
    """

    variables = {
        "id": customerId
    }

    # Make the API call
    result = await make_braintree_request(query, variables)

    # Process the response
    if "errors" in result:
        error_message = ", ".join([err.get("message", "Unknown error") for err in result["errors"]])
        print(f"Error retrieving customer: {error_message}")
        return json.dumps({
            "success": False,
            "error": error_message
        })

    try:
        customer_data = result.get("data", {}).get("node")

        if customer_data is None:
            print(f"Customer with ID '{customerId}' not found or is not a customer.")
            return json.dumps({
                "success": False,
                "error": f"Customer with ID '{customerId}' not found or is not a customer."
            })

        # Format addresses for easier consumption if present
        if "addresses" in customer_data and customer_data["addresses"] and "edges" in customer_data["addresses"]:
            addresses = [edge["node"] for edge in customer_data["addresses"]["edges"]]
            customer_data["addresses"] = addresses
            print(f"Found {len(addresses)} addresses for customer")
        else:
            customer_data["addresses"] = [] # Ensure key exists even if null/empty
            print("No addresses found for customer")


        return json.dumps({
            "success": True,
            "customer": customer_data
        })

    except (KeyError, TypeError) as e:
        print(f"Error processing customer data: {e}")
        return json.dumps({
            "success": False,
            "error": f"Error processing customer data: {e}",
            "raw_response": result
        })


@mcp.tool()
async def braintree_create_customer(
    firstName: str = None, 
    lastName: str = None, 
    email: str = None, 
    company: str = None, 
    website: str = None, 
    custom_fields: dict = None
) -> str:
    """
    Creates a new customer in Braintree.
    
    Args:
        firstName: The customer's first name (optional)
        lastName: The customer's last name (optional)
        email: The customer's email address (optional)
        company: The customer's company name (optional)
        website: The customer's website (optional)
        custom_fields: Dictionary of custom fields as {"name": "field_name", "value": "field_value"} (optional)
    
    Returns:
        JSON string containing the newly created customer details.
    """
    print(f"Executing braintree_create_customer for {firstName} {lastName}")
    
    # Prepare the GraphQL mutation
    mutation = """
        mutation CreateCustomer($input: CreateCustomerInput!) {
            createCustomer(input: $input) {
                customer {
                    id
                    legacyId
                    firstName
                    lastName
                    email
                    company
                    website
                    createdAt
                    customFields {
                        name
                        value
                    }
                }
            }
        }
    """
    
    # Build the customer input with provided fields
    customer = {}
    if firstName:
        customer["firstName"] = firstName
    if lastName:
        customer["lastName"] = lastName
    if email:
        customer["email"] = email
    if company:
        customer["company"] = company
    if website:
        customer["website"] = website
    
    # Add custom fields if provided
    if custom_fields and isinstance(custom_fields, dict):
        if "name" in custom_fields and "value" in custom_fields:
            customer["customFields"] = custom_fields
    
    # Create the variables for the mutation
    variables = {
        "input": {}
    }
    
    # Only add customer if we have any fields to set
    if customer:
        variables["input"]["customer"] = customer
    
    # Make the API call
    result = await make_braintree_request(mutation, variables)
    
    # Process the response
    if "errors" in result:
        error_message = ", ".join([err.get("message", "Unknown error") for err in result["errors"]])
        print(f"Error creating customer: {error_message}")
        return json.dumps({
            "success": False,
            "error": error_message
        })
    
    try:
        customer_data = result.get("data", {}).get("createCustomer", {}).get("customer")
        
        if not customer_data:
            return json.dumps({
                "success": False,
                "error": "Failed to create customer. No customer data returned."
            })
        
        print(f"Successfully created customer with ID: {customer_data.get('id')}")
        
        return json.dumps({
            "success": True,
            "customer": customer_data
        })
        
    except (KeyError, TypeError) as e:
        print(f"Error processing customer creation response: {e}")
        return json.dumps({
            "success": False,
            "error": f"Error processing customer creation response: {e}",
            "raw_response": result
        })

@mcp.tool()
async def braintree_update_customer(
    customerId: str,
    firstName: str = None,
    lastName: str = None,
    email: str = None,
    company: str = None,
    website: str = None,
    customFields: dict = None,
    phoneNumber: str = None,
    fax: str = None
) -> str:
    """
    Updates an existing customer in Braintree with the provided information.
    
    If this tool fails when using a legacy ID, try using braintree_get_graphql_id_from_legacy_id
    with type "CUSTOMER" to convert the ID, then retry this tool with the GraphQL ID.
    
    Args:
        customerId: The ID of the customer to update (can be GraphQL ID or legacy ID)
        firstName: The customer's updated first name (optional)
        lastName: The customer's updated last name (optional)
        email: The customer's updated email address (optional)
        company: The customer's updated company name (optional)
        website: The customer's updated website (optional)
        customFields: Dictionary of custom fields as {"name": "field_name", "value": "field_value"} (optional)
        phoneNumber: The customer's updated phone number (optional)
        fax: The customer's updated fax number (optional)
    
    Returns:
        JSON string containing the updated customer details.
    """
    print(f"Executing braintree_update_customer for customer ID: {customerId}")
    
    # Prepare the GraphQL mutation
    mutation = """
        mutation UpdateCustomer($input: UpdateCustomerInput!) {
            updateCustomer(input: $input) {
                customer {
                    id
                    legacyId
                    firstName
                    lastName
                    email
                    company
                    website
                    phoneNumber
                    fax
                    customFields {
                        name
                        value
                    }
                }
            }
        }
    """
    
    # Build the customer input with provided fields
    customer = {}
    if firstName is not None:
        customer["firstName"] = firstName
    if lastName is not None:
        customer["lastName"] = lastName
    if email is not None:
        customer["email"] = email
    if company is not None:
        customer["company"] = company
    if website is not None:
        customer["website"] = website
    if phoneNumber is not None:
        customer["phoneNumber"] = phoneNumber
    if fax is not None:
        customer["fax"] = fax
    
    # Add custom fields if provided
    if customFields and isinstance(customFields, dict):
        customer["customFields"] = customFields
    
    # Create the variables for the mutation
    variables = {
        "input": {
            "customerId": customerId,
        }
    }
    
    # Only add customer if we have any fields to update
    if customer:
        variables["input"]["customer"] = customer
    else:
        return json.dumps({
            "success": False,
            "error": "No update fields provided. At least one field must be specified to update."
        })
    
    # Make the API call
    result = await make_braintree_request(mutation, variables)
    
    # Process the response
    if "errors" in result:
        error_message = ", ".join([err.get("message", "Unknown error") for err in result["errors"]])
        print(f"Error updating customer: {error_message}")
        return json.dumps({
            "success": False,
            "error": error_message,
            "message": "If you're using a legacy ID, try converting it with braintree_get_graphql_id_from_legacy_id first."
        })
    
    try:
        customer_data = result.get("data", {}).get("updateCustomer", {}).get("customer")
        
        if not customer_data:
            return json.dumps({
                "success": False,
                "error": "Failed to update customer. No customer data returned."
            })
        
        print(f"Successfully updated customer with ID: {customer_data.get('id')}")
        
        return json.dumps({
            "success": True,
            "customer": customer_data
        })
        
    except (KeyError, TypeError) as e:
        print(f"Error processing customer update response: {e}")
        return json.dumps({
            "success": False,
            "error": f"Error processing customer update response: {e}",
            "raw_response": result
        })

@mcp.tool()
async def braintree_delete_customer(customer_id: str) -> str:
    """
    Deletes a customer from Braintree by their ID.
    
    Important: The customer cannot be deleted if they have existing payment methods.
    You must delete all payment methods associated with the customer first.
    
    If this tool fails when using a legacy ID, try using braintree_get_graphql_id_from_legacy_id
    with type "CUSTOMER" to convert the ID, then retry this tool with the GraphQL ID.
    
    Args:
        customer_id: The ID of the customer to delete.
    
    Returns:
        JSON string containing the deletion result.
    """
    print(f"Executing braintree_delete_customer for customer: {customer_id}")
    
    # Prepare the GraphQL mutation
    mutation = """
        mutation DeleteCustomer($input: DeleteCustomerInput!) {
            deleteCustomer(input: $input) {
                clientMutationId
            }
        }
    """
    
    variables = {
        "input": {
            "customerId": customer_id
        }
    }
    
    # Make the API call
    result = await make_braintree_request(mutation, variables)
    
    # Process the response
    if "errors" in result:
        error_message = ", ".join([err.get("message", "Unknown error") for err in result["errors"]])
        print(f"Error deleting customer: {error_message}")
        
        # Provide specific guidance based on common error scenarios
        if "payment methods" in error_message.lower():
            return json.dumps({
                "success": False,
                "error": error_message,
                "message": "This customer has existing payment methods. Use braintree_get_customer_payment_methods to find them, then delete each payment method before trying again."
            })
        elif "not found" in error_message.lower():
            return json.dumps({
                "success": False,
                "error": error_message,
                "message": "If you're using a legacy ID, try converting it with braintree_get_graphql_id_from_legacy_id first."
            })
        else:
            return json.dumps({
                "success": False,
                "error": error_message
            })
    
    try:
        # The successful deletion response is very simple
        if "data" in result and "deleteCustomer" in result["data"]:
            print(f"Successfully deleted customer with ID: {customer_id}")
            
            return json.dumps({
                "success": True,
                "message": f"Customer with ID '{customer_id}' has been successfully deleted."
            })
        else:
            return json.dumps({
                "success": False,
                "error": "Unexpected response format from Braintree."
            })
        
    except (KeyError, TypeError) as e:
        print(f"Error processing customer deletion response: {e}")
        return json.dumps({
            "success": False,
            "error": f"Error processing customer deletion response: {e}",
            "raw_response": result
        })

@mcp.tool()
async def braintree_vault_payment_method(
    payment_method_id: str,
    customer_id: str = None,
    make_default: bool = False,
    merchant_account_id: str = None
) -> str:
    """
    Vaults a single-use payment method to be used multiple times.
    Optionally associates it with a customer.
    
    If the payment method supports verification (e.g., credit cards), a verification
    will be performed by default before vaulting. If verification fails, the payment
    method will not be vaulted.
    
    If this tool fails when using a legacy customer ID, try using braintree_get_graphql_id_from_legacy_id
    with type "CUSTOMER" to convert the ID, then retry this tool with the GraphQL ID.
    
    Args:
        payment_method_id: ID of an existing single-use payment method to be vaulted.
        customer_id: Optional ID of customer to associate the payment method with.
        make_default: Optional flag to make this the default payment method for the customer.
        merchant_account_id: Optional ID of merchant account to use for verification.
    
    Returns:
        JSON string containing the vaulted payment method details.
    """
    print(f"Executing braintree_vault_payment_method for payment method: {payment_method_id}")
    
    # Prepare the GraphQL mutation
    mutation = """
        mutation VaultPaymentMethod($input: VaultPaymentMethodInput!) {
            vaultPaymentMethod(input: $input) {
                paymentMethod {
                    id
                    legacyId
                    usage
                    details {
                        __typename
                        ... on CreditCardDetails {
                            bin
                            brand
                            last4
                            expirationMonth
                            expirationYear
                            cardholderName
                            billingAddress {
                                id
                                addressLine1
                                addressLine2
                                adminArea1
                                adminArea2
                                postalCode
                                countryCode
                            }
                        }
                        ... on PayPalAccountDetails {
                            email
                            payer {
                                email
                                firstName
                                lastName
                                payerId
                            }
                        }
                        ... on VenmoAccountDetails {
                            username
                        }
                        ... on UsBankAccountDetails {
                            accountHolderName
                            accountType
                            bankName
                            last4
                            routingNumber
                        }
                    }
                    customer {
                        id
                        firstName
                        lastName
                        email
                    }
                }
                verification {
                    id
                    status
                    processorResponse {
                        code
                        message
                    }
                }
            }
        }
    """
    
    # Prepare the variables
    variables = {
        "input": {
            "paymentMethodId": payment_method_id
        }
    }
    
    # Add optional fields if provided
    if customer_id:
        variables["input"]["customerId"] = customer_id
    
    if make_default:
        variables["input"]["makeDefault"] = make_default
    
    if merchant_account_id:
        variables["input"]["verification"] = {
            "merchantAccountId": merchant_account_id
        }
    
    # Make the API call
    result = await make_braintree_request(mutation, variables)
    
    # Process the response - special handling for partial failures
    if "errors" in result:
        error_message = ", ".join([err.get("message", "Unknown error") for err in result["errors"]])
        print(f"Error vaulting payment method: {error_message}")
        
        # Check if this is a verification failure
        verification_data = None
        try:
            verification_data = result.get("data", {}).get("vaultPaymentMethod", {}).get("verification")
        except (KeyError, TypeError):
            pass
        
        if verification_data:
            return json.dumps({
                "success": False,
                "error": error_message,
                "verification": verification_data,
                "message": "Payment method verification failed. The payment method has not been vaulted."
            })
        elif customer_id and "not found" in error_message.lower():
            return json.dumps({
                "success": False,
                "error": error_message,
                "message": "If you're using a legacy customer ID, try converting it with braintree_get_graphql_id_from_legacy_id first."
            })
        elif "already been consumed" in error_message.lower():
            return json.dumps({
                "success": False,
                "error": error_message,
                "message": "This single-use payment method has already been used. You'll need to collect a new payment method from the customer."
            })
        elif "expired" in error_message.lower():
            return json.dumps({
                "success": False,
                "error": error_message,
                "message": "This single-use payment method has expired. Single-use payment methods expire after 3 hours."
            })
        else:
            return json.dumps({
                "success": False,
                "error": error_message
            })
    
    try:
        vault_result = result.get("data", {}).get("vaultPaymentMethod", {})
        payment_method_data = vault_result.get("paymentMethod")
        verification_data = vault_result.get("verification")
        
        if not payment_method_data:
            return json.dumps({
                "success": False,
                "error": "Failed to vault payment method. No payment method data returned.",
                "verification": verification_data
            })
        
        print(f"Successfully vaulted payment method with ID: {payment_method_data.get('id')}")
        
        return json.dumps({
            "success": True,
            "payment_method": payment_method_data,
            "verification": verification_data
        })
        
    except (KeyError, TypeError) as e:
        print(f"Error processing vault payment method response: {e}")
        return json.dumps({
            "success": False,
            "error": f"Error processing vault payment method response: {e}",
            "raw_response": result
        })


@mcp.tool()
async def braintree_verify_payment_method(
    payment_method_id: str,
    merchant_account_id: str = None
) -> str:
    """
    Verifies a payment method without creating a transaction.
    
    Verification checks whether a payment method has passed your fraud rules and
    the issuer has ensured it is associated with a valid account.
    
    If this tool fails when using a legacy ID, try using braintree_get_graphql_id_from_legacy_id
    with type "PAYMENT_METHOD" to convert the ID, then retry this tool with the GraphQL ID.
    
    Args:
        payment_method_id: ID of the payment method to verify.
        merchant_account_id: Optional ID of merchant account to use for verification.
    
    Returns:
        JSON string containing the verification result.
    """
    print(f"Executing braintree_verify_payment_method for payment method: {payment_method_id}")
    
    # Prepare the GraphQL mutation
    mutation = """
        mutation VerifyPaymentMethod($input: VerifyPaymentMethodInput!) {
            verifyPaymentMethod(input: $input) {
                verification {
                    id
                    legacyId
                    status
                    createdAt
                    gatewayRejectionReason
                    merchantAccountId
                    processorResponse {
                        code
                        message
                        avsPostalCodeResponseCode
                        avsStreetAddressResponseCode
                        cvvResponseCode
                    }
                    riskData {
                        decision
                        deviceDataCaptured
                        fraudServiceProvider
                        id
                        transactionRiskScore
                    }
                    paymentMethod {
                        id
                        legacyId
                        customer {
                            id
                            firstName
                            lastName
                        }
                    }
                }
            }
        }
    """
    
    # Prepare the variables
    variables = {
        "input": {
            "paymentMethodId": payment_method_id
        }
    }
    
    # Add merchant account ID if provided
    if merchant_account_id:
        variables["input"]["merchantAccountId"] = merchant_account_id
    
    # Make the API call
    result = await make_braintree_request(mutation, variables)
    
    # Process the response
    if "errors" in result:
        error_message = ", ".join([err.get("message", "Unknown error") for err in result["errors"]])
        print(f"Error verifying payment method: {error_message}")
        
        if "not found" in error_message.lower():
            return json.dumps({
                "success": False,
                "error": error_message,
                "message": "If you're using a legacy payment method ID, try converting it with braintree_get_graphql_id_from_legacy_id first."
            })
        else:
            return json.dumps({
                "success": False,
                "error": error_message
            })
    
    try:
        verification_data = result.get("data", {}).get("verifyPaymentMethod", {}).get("verification")
        
        if not verification_data:
            return json.dumps({
                "success": False,
                "error": "Failed to verify payment method. No verification data returned."
            })
        
        # Extract status for easier access
        verification_status = verification_data.get("status")
        print(f"Payment method verification result: {verification_status}")
        
        # Format a user-friendly response based on status
        status_message = ""
        if verification_status == "VERIFIED":
            status_message = "Payment method successfully verified."
        elif verification_status == "PROCESSOR_DECLINED":
            status_message = "Payment method verification was declined by the processor."
        elif verification_status == "GATEWAY_REJECTED":
            reason = verification_data.get("gatewayRejectionReason", "Unknown reason")
            status_message = f"Payment method verification was rejected by the gateway. Reason: {reason}"
        else:
            status_message = f"Payment method verification status: {verification_status}"
        
        return json.dumps({
            "success": verification_status == "VERIFIED",
            "status": verification_status,
            "message": status_message,
            "verification": verification_data
        })
        
    except (KeyError, TypeError) as e:
        print(f"Error processing verification response: {e}")
        return json.dumps({
            "success": False,
            "error": f"Error processing verification response: {e}",
            "raw_response": result
        })


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