#!/bin/bash
# Demo script for testing the Items API

BASE_URL="http://localhost:8000/api/v1"

echo "🚀 Items API Demo"
echo "================="
echo

# Colors for output
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Function to pretty print JSON
print_response() {
    echo -e "${GREEN}Response:${NC}"
    echo "$1" | python3 -m json.tool
    echo
}

# 1. Create some items
echo -e "${BLUE}1. Creating items...${NC}"
echo "POST ${BASE_URL}/items/"
echo

ITEM1=$(curl -s -X POST "${BASE_URL}/items/" \
  -H "Content-Type: application/json" \
  -d '{"title": "Buy groceries", "description": "Milk, eggs, bread", "is_completed": false}')
print_response "$ITEM1"

ITEM2=$(curl -s -X POST "${BASE_URL}/items/" \
  -H "Content-Type: application/json" \
  -d '{"title": "Write documentation", "description": "Update README and API docs", "is_completed": false}')
print_response "$ITEM2"

ITEM3=$(curl -s -X POST "${BASE_URL}/items/" \
  -H "Content-Type: application/json" \
  -d '{"title": "Deploy to staging", "description": "Test all features", "is_completed": true}')
print_response "$ITEM3"

# Extract first item ID
ITEM1_ID=$(echo "$ITEM1" | python3 -c "import sys, json; print(json.load(sys.stdin)['id'])")
echo -e "${YELLOW}Created item with ID: $ITEM1_ID${NC}"
echo

# 2. List all items
echo -e "${BLUE}2. Listing all items...${NC}"
echo "GET ${BASE_URL}/items/"
echo

ITEMS_LIST=$(curl -s "${BASE_URL}/items/")
print_response "$ITEMS_LIST"

# 3. List only incomplete items
echo -e "${BLUE}3. Listing incomplete items...${NC}"
echo "GET ${BASE_URL}/items/?completed=false"
echo

INCOMPLETE=$(curl -s "${BASE_URL}/items/?completed=false")
print_response "$INCOMPLETE"

# 4. Get specific item
echo -e "${BLUE}4. Getting specific item...${NC}"
echo "GET ${BASE_URL}/items/${ITEM1_ID}"
echo

ITEM=$(curl -s "${BASE_URL}/items/${ITEM1_ID}")
print_response "$ITEM"

# 5. Update item
echo -e "${BLUE}5. Updating item (marking as completed)...${NC}"
echo "PATCH ${BASE_URL}/items/${ITEM1_ID}"
echo

UPDATED=$(curl -s -X PATCH "${BASE_URL}/items/${ITEM1_ID}" \
  -H "Content-Type: application/json" \
  -d '{"is_completed": true, "description": "Milk, eggs, bread, butter"}')
print_response "$UPDATED"

# 6. List with pagination
echo -e "${BLUE}6. Listing with pagination...${NC}"
echo "GET ${BASE_URL}/items/?page=1&page_size=2"
echo

PAGINATED=$(curl -s "${BASE_URL}/items/?page=1&page_size=2")
print_response "$PAGINATED"

# 7. Delete item
echo -e "${BLUE}7. Deleting item...${NC}"
echo "DELETE ${BASE_URL}/items/${ITEM1_ID}"
echo

DELETE_RESPONSE=$(curl -s -w "\nHTTP Status: %{http_code}" -X DELETE "${BASE_URL}/items/${ITEM1_ID}")
echo -e "${GREEN}${DELETE_RESPONSE}${NC}"
echo

# 8. Verify deletion (should return 404)
echo -e "${BLUE}8. Verifying deletion (should fail)...${NC}"
echo "GET ${BASE_URL}/items/${ITEM1_ID}"
echo

NOT_FOUND=$(curl -s -w "\nHTTP Status: %{http_code}" "${BASE_URL}/items/${ITEM1_ID}")
echo -e "${YELLOW}${NOT_FOUND}${NC}"
echo

echo -e "${GREEN}✓ Demo complete!${NC}"
echo
echo "You can explore more with:"
echo "  - Swagger UI: http://localhost:8000/docs"
echo "  - ReDoc: http://localhost:8000/redoc"
echo "  - Health: http://localhost:8000/api/v1/health/"
