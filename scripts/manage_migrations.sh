#!/usr/bin/env bash
set -e

# Change to service directory (parent of scripts/)
cd "$(dirname "$0")/.." || exit 1

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

# Database config - align with application's DB_* variables
# Primary: Use DB_* variables (matches application settings)
# Fallback: ACCENT_DB_* for backward compatibility
export DB_HOST="${DB_HOST:-${ACCENT_DB_HOST:-localhost}}"
export DB_PORT="${DB_PORT:-${ACCENT_DB_PORT:-15432}}"
export DB_USER="${DB_USER:-${ACCENT_DB_USER:-asterisk}}"
export DB_PASSWORD="${DB_PASSWORD:-${ACCENT_DB_PASSWORD:-secret123}}"
export DB_NAME="${DB_NAME:-${ACCENT_DB_NAME:-accent}}"

# For backward compatibility, also set ACCENT_DB_* if not already set
export ACCENT_DB_HOST="${ACCENT_DB_HOST:-${DB_HOST}}"
export ACCENT_DB_PORT="${ACCENT_DB_PORT:-${DB_PORT}}"
export ACCENT_DB_USER="${ACCENT_DB_USER:-${DB_USER}}"
export ACCENT_DB_PASSWORD="${ACCENT_DB_PASSWORD:-${DB_PASSWORD}}"
export ACCENT_DB_NAME="${ACCENT_DB_NAME:-${DB_NAME}}"

# Docker config
# Path from service/accent-auth/ to root docker-compose.dev.yml
DOCKER_COMPOSE_FILE="${DOCKER_COMPOSE_FILE:-../../docker-compose.dev.yml}"
DOCKER_SERVICE="${DOCKER_SERVICE:-db}"
AUTO_START_DOCKER="${AUTO_START_DOCKER:-true}"
USE_DOCKER_COMPOSE="${USE_DOCKER_COMPOSE:-auto}"  # auto, true, false
DOCKER_CONTAINER_NAME="${DOCKER_CONTAINER_NAME:-accent-dev-postgres}"
DOCKER_IMAGE="${DOCKER_IMAGE:-postgres:18-alpine}"
DOCKER_VOLUME="${DOCKER_VOLUME:-accent-postgres-data}"

check_db() {
    DB_URL="postgresql://${DB_USER}:${DB_PASSWORD}@${DB_HOST}:${DB_PORT}/${DB_NAME}"
    psql "$DB_URL" -c "SELECT 1;" >/dev/null 2>&1
}

check_docker() {
    command -v docker >/dev/null 2>&1 || {
        echo -e "${RED}Error: docker not found${NC}"
        return 1
    }
}

check_docker_compose() {
    if command -v docker-compose >/dev/null 2>&1; then
        return 0
    elif docker compose version >/dev/null 2>&1; then
        return 0
    else
        return 1
    fi
}

get_docker_compose_cmd() {
    if command -v docker-compose >/dev/null 2>&1; then
        echo "docker-compose"
    elif docker compose version >/dev/null 2>&1; then
        echo "docker compose"
    else
        return 1
    fi
}

should_use_compose() {
    case "$USE_DOCKER_COMPOSE" in
        true) return 0 ;;
        false) return 1 ;;
        auto)
            # Try docker-compose if file exists and command is available
            if [ -f "$DOCKER_COMPOSE_FILE" ] && check_docker_compose; then
                return 0
            else
                return 1
            fi
            ;;
        *) return 1 ;;
    esac
}

start_docker_db_plain() {
    echo -e "${BLUE}Starting Docker database container...${NC}"

    # Check if container already exists and is running
    if docker ps --format '{{.Names}}' | grep -q "^${DOCKER_CONTAINER_NAME}$"; then
        echo -e "${GREEN}Container ${DOCKER_CONTAINER_NAME} is already running${NC}"
        return 0
    fi

    # Check if container exists but is stopped
    if docker ps -a --format '{{.Names}}' | grep -q "^${DOCKER_CONTAINER_NAME}$"; then
        echo -e "${BLUE}Starting existing container...${NC}"
        docker start "$DOCKER_CONTAINER_NAME" >/dev/null 2>&1 || return 1
    else
        # Create new container
        echo -e "${BLUE}Creating new container...${NC}"
        docker run -d \
            --name "$DOCKER_CONTAINER_NAME" \
            -e POSTGRES_USER="${DB_USER}" \
            -e POSTGRES_PASSWORD="${DB_PASSWORD}" \
            -e POSTGRES_DB="${DB_NAME}" \
            -p "${DB_PORT}:5432" \
            -v "${DOCKER_VOLUME}:/var/lib/postgresql/data" \
            --restart unless-stopped \
            "$DOCKER_IMAGE" >/dev/null 2>&1 || return 1
    fi

    # Wait for database to be ready
    echo -e "${GREEN}Waiting for database to be ready...${NC}"
    MAX_WAIT=60
    ELAPSED=0
    while [ $ELAPSED -lt $MAX_WAIT ]; do
        if check_db; then
            echo -e "${GREEN}Database is ready!${NC}"
            return 0
        fi
        sleep 2
        ELAPSED=$((ELAPSED + 2))
        echo -n "."
    done
    echo ""
    echo -e "${YELLOW}Warning: Database may not be fully ready yet${NC}"
    return 0
}

start_docker_db_compose() {
    DOCKER_CMD=$(get_docker_compose_cmd) || return 1

    if [ ! -f "$DOCKER_COMPOSE_FILE" ]; then
        echo -e "${YELLOW}Warning: Docker compose file not found at $DOCKER_COMPOSE_FILE${NC}"
        return 1
    fi

    echo -e "${BLUE}Starting/updating Docker database via docker-compose...${NC}"

    if $DOCKER_CMD -f "$DOCKER_COMPOSE_FILE" up -d "$DOCKER_SERVICE" 2>&1; then
        echo -e "${GREEN}Waiting for database to be ready...${NC}"
        MAX_WAIT=60
        ELAPSED=0
        while [ $ELAPSED -lt $MAX_WAIT ]; do
            if check_db; then
                echo -e "${GREEN}Database is ready!${NC}"
                return 0
            fi
            sleep 2
            ELAPSED=$((ELAPSED + 2))
            echo -n "."
        done
        echo ""
        echo -e "${YELLOW}Warning: Database may not be fully ready yet${NC}"
        return 0
    else
        return 1
    fi
}

start_docker_db() {
    if [ "$AUTO_START_DOCKER" != "true" ]; then
        return 0
    fi

    if ! check_docker; then
        return 1
    fi

    # Try docker-compose first if configured, then fall back to plain docker
    if should_use_compose; then
        if start_docker_db_compose; then
            return 0
        else
            echo -e "${YELLOW}Docker-compose failed, falling back to plain docker...${NC}"
        fi
    fi

    # Fall back to plain docker
    start_docker_db_plain
}

show_status() {
    echo -e "${BLUE}Migration Status:${NC}"
    DB_URL="postgresql://${DB_USER}:${DB_PASSWORD}@${DB_HOST}:${DB_PORT}/${DB_NAME}"
    DB_REV=$(psql "$DB_URL" -t -c "SELECT version_num FROM alembic_version;" 2>/dev/null | xargs || echo "none")
    echo "Database revision: ${GREEN}${DB_REV}${NC}"
    echo ""
    echo "Available migrations:"
    uv run alembic history 2>&1 | head -10
}

case "${1:-}" in
    status)
        if ! check_db; then
            echo -e "${YELLOW}Database not available. Attempting to start Docker database...${NC}"
            start_docker_db || echo -e "${RED}Could not start database${NC}"
        fi
        show_status
        ;;
    create)
        [ -z "$2" ] && { echo "Usage: $0 create 'message'"; exit 1; }
        uv run alembic revision --autogenerate -m "$2"
        ;;
    upgrade)
        if ! check_db; then
            echo -e "${YELLOW}Database not available. Attempting to start Docker database...${NC}"
            start_docker_db || { echo -e "${RED}Could not start database${NC}"; exit 1; }
        fi
        uv run alembic upgrade "${2:-head}"
        ;;
    downgrade)
        echo -e "${YELLOW}WARNING: This will downgrade the database${NC}"
        read -p "Continue? (yes): " confirm
        [ "$confirm" = "yes" ] || exit 0
        if ! check_db; then
            echo -e "${YELLOW}Database not available. Attempting to start Docker database...${NC}"
            start_docker_db || { echo -e "${RED}Could not start database${NC}"; exit 1; }
        fi
        uv run alembic downgrade "${2:--1}"
        ;;
    sql)
        if ! check_db; then
            echo -e "${YELLOW}Database not available. Attempting to start Docker database...${NC}"
            start_docker_db || { echo -e "${RED}Could not start database${NC}"; exit 1; }
        fi
        uv run alembic upgrade "${2:-head}" --sql
        ;;
    docker-start)
        start_docker_db || exit 1
        ;;
    docker-stop)
        if ! check_docker; then
            exit 1
        fi
        if should_use_compose; then
            DOCKER_CMD=$(get_docker_compose_cmd) || exit 1
            if [ -f "$DOCKER_COMPOSE_FILE" ]; then
                echo -e "${BLUE}Stopping Docker database via docker-compose...${NC}"
                $DOCKER_CMD -f "$DOCKER_COMPOSE_FILE" stop "$DOCKER_SERVICE"
            else
                echo -e "${RED}Docker compose file not found at $DOCKER_COMPOSE_FILE${NC}"
                exit 1
            fi
        else
            echo -e "${BLUE}Stopping Docker database container...${NC}"
            docker stop "$DOCKER_CONTAINER_NAME" 2>/dev/null || {
                echo -e "${YELLOW}Container ${DOCKER_CONTAINER_NAME} not found or already stopped${NC}"
            }
        fi
        ;;
    docker-restart)
        if ! check_docker; then
            exit 1
        fi
        if should_use_compose; then
            DOCKER_CMD=$(get_docker_compose_cmd) || exit 1
            if [ -f "$DOCKER_COMPOSE_FILE" ]; then
                echo -e "${BLUE}Restarting Docker database via docker-compose...${NC}"
                $DOCKER_CMD -f "$DOCKER_COMPOSE_FILE" restart "$DOCKER_SERVICE"
            else
                echo -e "${RED}Docker compose file not found at $DOCKER_COMPOSE_FILE${NC}"
                exit 1
            fi
        else
            echo -e "${BLUE}Restarting Docker database container...${NC}"
            if docker restart "$DOCKER_CONTAINER_NAME" 2>/dev/null; then
                start_docker_db || exit 1
            else
                echo -e "${YELLOW}Container not found, starting new one...${NC}"
                start_docker_db_plain || exit 1
            fi
        fi
        ;;
    *)
        echo "Usage: $0 {status|create|upgrade|downgrade|sql|docker-start|docker-stop|docker-restart} [args]"
        echo ""
        echo "Commands:"
        echo "  status              Show migration status"
        echo "  create 'message'    Create a new migration"
        echo "  upgrade [revision] Upgrade database (default: head)"
        echo "  downgrade [rev]     Downgrade database (default: -1)"
        echo "  sql [revision]     Show SQL for upgrade (default: head)"
        echo "  docker-start       Start Docker database"
        echo "  docker-stop        Stop Docker database"
        echo "  docker-restart     Restart Docker database"
        echo ""
        echo "Environment variables:"
        echo "  Database (primary - matches application):"
        echo "    DB_HOST               Database host (default: localhost)"
        echo "    DB_PORT               Database port (default: 15432)"
        echo "    DB_USER               Database user (default: asterisk)"
        echo "    DB_PASSWORD           Database password (default: secret123)"
        echo "    DB_NAME               Database name (default: accent)"
        echo "  Database (backward compatibility):"
        echo "    ACCENT_DB_HOST        Legacy variable (falls back to DB_HOST)"
        echo "    ACCENT_DB_PORT        Legacy variable (falls back to DB_PORT)"
        echo "    ACCENT_DB_USER        Legacy variable (falls back to DB_USER)"
        echo "    ACCENT_DB_PASSWORD    Legacy variable (falls back to DB_PASSWORD)"
        echo "    ACCENT_DB_NAME        Legacy variable (falls back to DB_NAME)"
        echo "  Docker configuration:"
        echo "    DOCKER_COMPOSE_FILE     Path to docker-compose file (default: ../../docker-compose.dev.yml)"
        echo "    DOCKER_SERVICE          Docker service name for compose (default: db)"
        echo "    USE_DOCKER_COMPOSE      Use docker-compose? auto/true/false (default: auto)"
        echo "    DOCKER_CONTAINER_NAME   Container name for plain docker (default: accent-dev-postgres)"
        echo "    DOCKER_IMAGE            PostgreSQL image (default: postgres:18-alpine)"
        echo "    DOCKER_VOLUME           Volume name for data (default: accent-postgres-data)"
        echo "    AUTO_START_DOCKER       Auto-start Docker if DB unavailable (default: true)"
        exit 1
        ;;
esac
