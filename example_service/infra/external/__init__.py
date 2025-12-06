"""External service clients.

This module provides HTTP clients for interacting with external services.
All clients inherit from BaseHTTPClient and provide typed interfaces.
"""

from example_service.infra.external.auth import AuthClient
from example_service.infra.external.base_client import BaseHTTPClient

__all__ = [
    "AuthClient",
    "BaseHTTPClient",
]
