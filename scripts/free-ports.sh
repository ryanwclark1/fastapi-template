#!/usr/bin/env bash
#
# Free Ports Script for FastAPI Template Local Stack
# Kills processes using ports required by FastAPI, PostgreSQL, Redis, RabbitMQ, and observability stack
#
# Usage:
#   ./scripts/free-ports.sh [--force] [--ports PORT1,PORT2,...]
#
# Author: FastAPI Template Development Team

set -euo pipefail

readonly SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" >/dev/null 2>&1 && pwd)"
readonly REPO_ROOT="$(dirname "${SCRIPT_DIR}")"

# Colors for output
readonly RED='\033[0;31m'
readonly GREEN='\033[0;32m'
readonly YELLOW='\033[1;33m'
readonly BLUE='\033[0;34m'
readonly NC='\033[0m' # No Color

# Default ports for FastAPI template stack
readonly DEFAULT_PORTS=(
    8000   # FastAPI API
    5432   # PostgreSQL
    6379   # Redis
    5672   # RabbitMQ AMQP
    15672  # RabbitMQ Management UI
    3003   # Grafana UI
    3101   # Loki API
    3200   # Tempo query frontend
    4317   # OTLP gRPC
    4318   # OTLP HTTP
    9091   # Prometheus web UI
    12346  # Grafana Alloy UI
)

FORCE=false
PORTS=()

# Parse arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        --force|-f)
            FORCE=true
            shift
            ;;
        --ports|-p)
            IFS=',' read -ra PORTS <<< "$2"
            shift 2
            ;;
        --help|-h)
            echo "Usage: $0 [OPTIONS]"
            echo ""
            echo "Options:"
            echo "  --force, -f              Skip confirmation prompt"
            echo "  --ports, -p PORTS        Comma-separated list of ports (default: all FastAPI template stack ports)"
            echo "  --help, -h               Show this help message"
            echo ""
            echo "Default ports:"
            printf "  %s\n" "${DEFAULT_PORTS[@]}"
            exit 0
            ;;
        *)
            echo -e "${RED}Unknown option: $1${NC}"
            exit 1
            ;;
    esac
done

# Use default ports if none specified
if [[ ${#PORTS[@]} -eq 0 ]]; then
    PORTS=("${DEFAULT_PORTS[@]}")
fi

##############################################################################
# Find processes using a specific port
# Arguments:
#   $1 - Port number
# Returns:
#   Array of PIDs using the port
##############################################################################
find_port_processes() {
    local port="$1"
    local pids=()
    local found=false

    # Try lsof first (most reliable when it works)
    if command -v lsof &> /dev/null; then
        while IFS= read -r pid; do
            if [[ -n "$pid" && "$pid" != "PID" ]]; then
                pids+=("$pid")
                found=true
            fi
        done < <(lsof -ti ":$port" 2>/dev/null || true)
    fi

    # If lsof didn't find anything, try ss (may need sudo for PID info)
    if [[ "$found" == "false" ]] && command -v ss &> /dev/null; then
        # First check if port is in use at all
        if ss -tln "sport = :$port" 2>/dev/null | grep -q ":$port "; then
            # Port is in use, try to get PIDs (may require sudo)
            while IFS= read -r line; do
                local pid=$(echo "$line" | awk '{print $6}' | cut -d',' -f2 | grep -oP 'pid=\K\d+' 2>/dev/null || echo "")
                if [[ -n "$pid" ]]; then
                    pids+=("$pid")
                    found=true
                fi
            done < <(ss -tlnp "sport = :$port" 2>/dev/null | grep -v "^State" || true)

            # If we found port in use but no PIDs, return a special marker
            if [[ "$found" == "false" ]]; then
                echo "UNKNOWN"
                return 0
            fi
        fi
    fi

    # If still nothing found, try netstat as last resort
    if [[ "$found" == "false" ]] && command -v netstat &> /dev/null; then
        while IFS= read -r line; do
            local pid=$(echo "$line" | awk '{print $7}' | cut -d'/' -f1)
            if [[ -n "$pid" && "$pid" =~ ^[0-9]+$ ]]; then
                pids+=("$pid")
                found=true
            fi
        done < <(netstat -tlnp 2>/dev/null | grep ":$port " || true)
    fi

    # Remove duplicates and return
    if [[ ${#pids[@]} -gt 0 ]]; then
        printf '%s\n' "${pids[@]}" | sort -u
    fi
}

##############################################################################
# Get process information
# Arguments:
#   $1 - PID
# Returns:
#   Process name and command
##############################################################################
get_process_info() {
    local pid="$1"
    if [[ -f "/proc/$pid/cmdline" ]]; then
        local cmdline=$(tr '\0' ' ' < "/proc/$pid/cmdline" | head -c 100)
        echo "$cmdline"
    elif command -v ps &> /dev/null; then
        ps -p "$pid" -o comm=,args= 2>/dev/null | head -c 100 || echo "unknown"
    else
        echo "unknown"
    fi
}

##############################################################################
# Kill process with confirmation
# Arguments:
#   $1 - PID
#   $2 - Port number
#   $3 - Process info
##############################################################################
kill_process() {
    local pid="$1"
    local port="$2"
    local info="$3"

    if [[ "$FORCE" == "true" ]]; then
        echo -e "${YELLOW}Killing PID $pid (port $port)${NC}"
        kill -9 "$pid" 2>/dev/null || true
        echo -e "${GREEN}✓ Killed PID $pid${NC}"
    else
        echo -e "${YELLOW}Found process on port $port:${NC}"
        echo "  PID: $pid"
        echo "  Command: $info"
        echo ""
    fi
}

# Main execution
echo -e "${BLUE}🔍 Checking ports for FastAPI template stack...${NC}"
echo ""

found_any=false
declare -A port_pids

# Check each port
for port in "${PORTS[@]}"; do
    echo -n "Checking port $port... "

    pids=$(find_port_processes "$port")

    if [[ -n "$pids" ]]; then
        echo -e "${RED}IN USE${NC}"
        found_any=true
        port_pids["$port"]="$pids"

        # Show process details
        if [[ "$pids" == "UNKNOWN" ]]; then
            echo -e "${YELLOW}  → Process detected but PID unavailable (try running with sudo)${NC}"
        else
            while IFS= read -r pid; do
                if [[ -n "$pid" ]]; then
                    info=$(get_process_info "$pid")
                    echo "  → PID $pid: $info"
                fi
            done <<< "$pids"
        fi
    else
        echo -e "${GREEN}FREE${NC}"
    fi
done

echo ""

# If no processes found, exit
if [[ "$found_any" == "false" ]]; then
    echo -e "${GREEN}✅ All ports are free!${NC}"
    exit 0
fi

# Check if any ports have unknown PIDs (require sudo)
has_unknown=false
for port in "${!port_pids[@]}"; do
    if [[ "${port_pids[$port]}" == "UNKNOWN" ]]; then
        has_unknown=true
        break
    fi
done

if [[ "$has_unknown" == "true" ]]; then
    echo -e "${RED}❌ Some ports are in use but PIDs cannot be determined without elevated privileges.${NC}"
    echo -e "${YELLOW}   Please run this script with sudo to kill all processes.${NC}"
    echo ""
    exit 1
fi

# Confirmation prompt
if [[ "$FORCE" != "true" ]]; then
    echo -e "${YELLOW}⚠️  Found processes using required ports.${NC}"
    echo ""
    echo "The following ports are in use:"
    for port in "${!port_pids[@]}"; do
        echo "  - Port $port"
    done
    echo ""
    echo -e "${YELLOW}Do you want to kill these processes? (y/N)${NC}"
    read -r response

    if [[ ! "$response" =~ ^[Yy]$ ]]; then
        echo -e "${BLUE}Aborted. Ports were not freed.${NC}"
        exit 0
    fi
fi

# Kill processes
echo ""
echo -e "${BLUE}🛑 Killing processes...${NC}"
echo ""

killed_count=0
for port in "${!port_pids[@]}"; do
    pids="${port_pids[$port]}"
    while IFS= read -r pid; do
        if [[ -n "$pid" ]]; then
            info=$(get_process_info "$pid")
            kill_process "$pid" "$port" "$info"
            ((killed_count++)) || true
        fi
    done <<< "$pids"
done

# Wait a moment for processes to terminate
sleep 1

# Verify ports are free
echo ""
echo -e "${BLUE}🔍 Verifying ports are free...${NC}"
echo ""

all_free=true
for port in "${PORTS[@]}"; do
    pids=$(find_port_processes "$port")
    if [[ -n "$pids" ]]; then
        echo -e "${RED}⚠️  Port $port is still in use${NC}"
        all_free=false
    else
        echo -e "${GREEN}✓ Port $port is free${NC}"
    fi
done

echo ""
if [[ "$all_free" == "true" ]]; then
    echo -e "${GREEN}✅ Successfully freed all ports!${NC}"
    echo -e "${GREEN}   Killed $killed_count process(es)${NC}"
    exit 0
else
    echo -e "${YELLOW}⚠️  Some ports may still be in use.${NC}"
    echo -e "${YELLOW}   You may need to manually kill remaining processes.${NC}"
    exit 1
fi
