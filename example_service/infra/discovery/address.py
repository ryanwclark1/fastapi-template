"""Network address detection utilities for service discovery.

This module provides utilities for detecting the advertise address
for service registration. It supports:
- Explicit address configuration
- Automatic detection from network interfaces (using netifaces)
- Graceful fallback when netifaces is unavailable
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from types import ModuleType

logger = logging.getLogger(__name__)

# Optional dependency - graceful fallback if not installed
_netifaces: ModuleType | None = None
try:
    import netifaces as _netifaces_module

    _netifaces = _netifaces_module
except ImportError:
    logger.debug("netifaces not installed; address auto-detection will fall back to 127.0.0.1")


def find_interface_address(interface_hint: str = "eth0") -> str:
    """Find IP address from a network interface.

    Attempts to find a suitable IP address by:
    1. Checking the hinted interface first
    2. Scanning common interface prefixes (eth*, en*)
    3. Falling back to loopback as last resort

    Args:
        interface_hint: Preferred interface name to check first.
            Defaults to "eth0" which is common on Linux systems.

    Returns:
        IP address string. Falls back to "127.0.0.1" if no suitable
        address is found or netifaces is unavailable.

    Example:
        >>> address = find_interface_address("eth0")
        >>> print(address)
        '192.168.1.100'
    """
    if _netifaces is None:
        logger.info("netifaces not installed; falling back to 127.0.0.1")
        return "127.0.0.1"

    # Build list of interfaces to check
    interfaces_to_check: list[str] = [interface_hint]

    # Add other candidate interfaces (eth*, en* are common network interfaces)
    for iface in _netifaces.interfaces():
        if _is_network_interface(iface) and iface not in interfaces_to_check:
            interfaces_to_check.append(iface)

    # Add loopback as last resort
    if "lo" not in interfaces_to_check:
        interfaces_to_check.append("lo")

    # Try each interface
    for iface in interfaces_to_check:
        address = _get_interface_ipv4(iface)
        if address:
            logger.debug("Found address %s on interface %s", address, iface)
            return address

    logger.warning("No suitable network interface found; falling back to 127.0.0.1")
    return "127.0.0.1"


def _is_network_interface(name: str) -> bool:
    """Check if an interface name looks like a network interface.

    Args:
        name: Interface name to check.

    Returns:
        True if the name starts with common network interface prefixes.
    """
    return any(name.startswith(prefix) for prefix in ("eth", "en", "wlan", "wl"))


def _get_interface_ipv4(iface: str) -> str | None:
    """Get IPv4 address from a specific interface.

    Args:
        iface: Interface name to query.

    Returns:
        IPv4 address string or None if not available.
    """
    if _netifaces is None:
        return None

    try:
        # Get interface addresses
        iface_info = _netifaces.ifaddresses(iface)
        ipv4_addrs = iface_info.get(_netifaces.AF_INET, [])

        # Return first valid address
        for addr_info in ipv4_addrs:
            addr = addr_info.get("addr")
            if isinstance(addr, str) and addr:
                return addr

    except ValueError:
        # Interface doesn't exist
        logger.debug("Interface does not exist: %s", iface)
    except Exception as e:
        logger.debug("Error reading interface %s: %s", iface, e)

    return None


def resolve_advertise_address(
    configured_address: str | None,
    interface_hint: str = "eth0",
) -> str:
    """Resolve the advertise address for service registration.

    Args:
        configured_address: Explicitly configured address, or None for auto-detection.
        interface_hint: Network interface to prefer for auto-detection.

    Returns:
        IP address string to advertise.

    Example:
        >>> # Explicit address
        >>> resolve_advertise_address("10.0.0.5")
        '10.0.0.5'

        >>> # Auto-detect
        >>> resolve_advertise_address(None, "eth0")
        '192.168.1.100'
    """
    if configured_address:
        # Use explicit address
        logger.debug("Using configured advertise address: %s", configured_address)
        return configured_address

    # Auto-detect from network interfaces
    address = find_interface_address(interface_hint)
    logger.info("Auto-detected advertise address: %s", address)
    return address
