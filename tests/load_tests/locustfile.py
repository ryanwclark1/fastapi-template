"""Locust load testing for the FastAPI application.

This module defines load test scenarios using Locust.

Usage:
    # Start Locust web UI
    locust -f tests/load_tests/locustfile.py --host=http://localhost:8000

    # Run headless with specific parameters
    locust -f tests/load_tests/locustfile.py --host=http://localhost:8000 \
        --headless --users 100 --spawn-rate 10 --run-time 5m

    # Run specific user class
    locust -f tests/load_tests/locustfile.py --host=http://localhost:8000 \
        -u 50 -r 5 -t 2m --class-picker

Configuration:
    HOST: Target host (default: http://localhost:8000)
    Users: Number of concurrent users
    Spawn rate: Users spawned per second
    Run time: Duration of the test

Output:
    - Real-time statistics in web UI
    - HTML report with --html flag
    - CSV export with --csv flag
"""

from __future__ import annotations

from datetime import datetime, timedelta
import random
import string

from locust import HttpUser, between, events, task


def generate_random_string(length: int = 10) -> str:
    """Generate a random string."""
    return "".join(random.choices(string.ascii_letters + string.digits, k=length))


def generate_random_email() -> str:
    """Generate a random email address."""
    return f"{generate_random_string(8)}@example.com"


class BaseAPIUser(HttpUser):
    """Base class for API load testing users.

    Provides common setup and authentication handling.
    """

    # Wait between 1 and 3 seconds between tasks
    wait_time = between(1, 3)

    # Override in subclasses
    abstract = True

    def on_start(self):
        """Called when user starts - authenticate if needed."""
        # Add authentication headers if using auth
        self.auth_headers = {
            "Content-Type": "application/json",
            # Add auth token if needed:
            # "Authorization": "Bearer <token>",
        }


class HealthCheckUser(HttpUser):
    """User that only performs health checks.

    Useful for baseline load testing and monitoring.
    """

    wait_time = between(0.5, 1)
    weight = 1  # Lower weight = fewer users

    @task
    def health_check(self):
        """Check health endpoint."""
        self.client.get("/api/v1/health")

    @task
    def readiness_check(self):
        """Check readiness endpoint."""
        self.client.get("/api/v1/health/ready")


class ReminderAPIUser(HttpUser):
    """User that interacts with the reminders API.

    Simulates typical reminder CRUD operations.
    """

    wait_time = between(1, 3)
    weight = 5  # Higher weight = more users

    def on_start(self):
        """Initialize user state."""
        self.auth_headers = {"Content-Type": "application/json"}
        self.created_reminder_ids = []

    @task(5)
    def list_reminders(self):
        """List reminders - most common operation."""
        with self.client.get(
            "/api/v1/reminders",
            headers=self.auth_headers,
            catch_response=True,
        ) as response:
            if response.status_code == 200:
                response.success()
            elif response.status_code == 401:
                response.success()  # Expected without auth
            else:
                response.failure(f"Unexpected status: {response.status_code}")

    @task(3)
    def get_reminder(self):
        """Get a specific reminder."""
        if not self.created_reminder_ids:
            return

        reminder_id = random.choice(self.created_reminder_ids)
        self.client.get(
            f"/api/v1/reminders/{reminder_id}",
            headers=self.auth_headers,
            name="/api/v1/reminders/[id]",
        )

    @task(2)
    def create_reminder(self):
        """Create a new reminder."""
        reminder_data = {
            "title": f"Load Test Reminder {generate_random_string(6)}",
            "description": f"Created by load test at {datetime.now().isoformat()}",
            "remind_at": (datetime.now() + timedelta(days=1)).isoformat(),
        }

        with self.client.post(
            "/api/v1/reminders",
            json=reminder_data,
            headers=self.auth_headers,
            catch_response=True,
        ) as response:
            if response.status_code == 201:
                try:
                    data = response.json()
                    self.created_reminder_ids.append(data.get("id"))
                    response.success()
                except Exception:
                    response.success()
            elif response.status_code in (401, 403):
                response.success()  # Expected without proper auth
            else:
                response.failure(f"Create failed: {response.status_code}")

    @task(1)
    def update_reminder(self):
        """Update an existing reminder."""
        if not self.created_reminder_ids:
            return

        reminder_id = random.choice(self.created_reminder_ids)
        update_data = {
            "title": f"Updated Reminder {generate_random_string(6)}",
        }

        self.client.patch(
            f"/api/v1/reminders/{reminder_id}",
            json=update_data,
            headers=self.auth_headers,
            name="/api/v1/reminders/[id]",
        )

    @task(1)
    def search_reminders(self):
        """Search reminders."""
        search_terms = ["meeting", "important", "todo", "call", "review"]
        query = random.choice(search_terms)

        self.client.get(
            f"/api/v1/search?q={query}&entities=reminders",
            headers=self.auth_headers,
            name="/api/v1/search",
        )


class MixedWorkloadUser(HttpUser):
    """User with mixed read/write workload.

    Simulates a realistic mix of operations across different endpoints.
    """

    wait_time = between(0.5, 2)
    weight = 3

    @task(10)
    def browse_reminders(self):
        """Browse reminders with pagination."""
        page = random.randint(0, 5)
        self.client.get(
            f"/api/v1/reminders?limit=20&offset={page * 20}",
            name="/api/v1/reminders (paginated)",
        )

    @task(5)
    def check_health(self):
        """Quick health check."""
        self.client.get("/api/v1/health")

    @task(3)
    def get_metrics(self):
        """Fetch metrics endpoint."""
        self.client.get("/metrics")

    @task(2)
    def search(self):
        """Perform a search."""
        self.client.get(
            "/api/v1/search?q=test",
            name="/api/v1/search",
        )

    @task(1)
    def get_audit_logs(self):
        """Fetch recent audit logs."""
        self.client.get(
            "/api/v1/audit/logs?limit=50",
            name="/api/v1/audit/logs",
        )


# Event hooks for custom reporting


@events.request.add_listener
def log_request(
    request_type,
    name,
    response_time,
    response_length,
    response,
    exception,
    **kwargs,
):
    """Log request details for debugging."""
    if exception:
        print(f"Request failed: {name} - {exception}")


@events.test_start.add_listener
def on_test_start(environment, **kwargs):
    """Called when test starts."""
    print(f"Load test starting against {environment.host}")


@events.test_stop.add_listener
def on_test_stop(environment, **kwargs):
    """Called when test stops."""
    print("Load test completed")
    stats = environment.stats
    print(f"Total requests: {stats.total.num_requests}")
    print(f"Failures: {stats.total.num_failures}")
    print(f"Median response time: {stats.total.median_response_time}ms")
