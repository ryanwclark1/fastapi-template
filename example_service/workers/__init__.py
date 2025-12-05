"""Background worker task definitions.

This package contains the actual task implementations (the work being done):
- ai/: AI pipeline execution tasks
- analytics/: Multi-level time-series aggregation and KPI computation (example)
- backup/: Database backup tasks (pg_dump + S3 upload)
- cache/: Cache warming and invalidation
- cleanup/: Cleanup tasks (temp files, old backups, expired data)
- export/: Data export (CSV/JSON)
- files/: File processing tasks
- notifications/: Reminder notification tasks
- reports/: Report generation with task chaining and workflows (example)
- webhooks/: Webhook delivery tasks
- examples/: Advanced patterns (circuit breakers, sagas, idempotency)

For task infrastructure (broker, scheduler, tracking), see `infra/tasks/`.

Task definitions are registered with the broker on import.
"""

from __future__ import annotations

__all__: list[str] = []
