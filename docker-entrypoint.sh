#!/bin/bash
set -e

# Colors for output
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo -e "${YELLOW}Running database migrations...${NC}"

# Run migrations using your CLI
python -m example_service.cli.main db upgrade

# Check if migrations succeeded
if [ $? -eq 0 ]; then
    echo -e "${GREEN}✓ Migrations applied successfully${NC}"
else
    echo -e "${YELLOW}⚠ Migration check failed, but continuing...${NC}"
fi

echo -e "${GREEN}Starting application...${NC}"

# Execute the CMD from Dockerfile (passed as arguments to this script)
exec "$@"
