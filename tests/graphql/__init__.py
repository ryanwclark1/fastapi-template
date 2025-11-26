"""GraphQL test suite."""

import os

import pytest

if os.environ.get("RUN_GRAPHQL_TESTS") != "1":  # pragma: no cover - default skip
    pytestmark = pytest.mark.skip(reason="GraphQL tests require RUN_GRAPHQL_TESTS=1")
