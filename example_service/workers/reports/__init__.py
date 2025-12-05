"""Report generation and delivery tasks.

This module demonstrates advanced task orchestration patterns:
- Task chaining (sequential execution: A → B → C)
- Parent-child task relationships
- Result passing between tasks
- Conditional workflows (branching logic)
- Task callbacks (success/failure handlers)
- Batch processing with parallel execution
- Error handling and rollback strategies

Use cases:
- PDF report generation
- Multi-format export pipelines
- Email delivery with attachments
- Data aggregation → formatting → distribution workflows
"""

from __future__ import annotations

__all__: list[str] = []
