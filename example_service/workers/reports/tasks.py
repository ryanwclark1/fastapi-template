"""Report generation task orchestration.

This module demonstrates production patterns for complex task workflows:
- Sequential task chaining with result passing
- Parallel task execution with fan-out/fan-in
- Conditional branching based on intermediate results
- Error handling with cleanup and rollback
- Task callbacks for notifications
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
import logging
from pathlib import Path
from tempfile import gettempdir
from typing import Any

from example_service.infra.tasks.broker import broker

logger = logging.getLogger(__name__)
REPORT_OUTPUT_DIR = Path(gettempdir()) / "example_service_reports"


# =============================================================================
# Individual Task Steps (Building Blocks)
# =============================================================================


if broker is not None:

    @broker.task(
        task_name="reports.collect_data",
        retry_on_error=True,
        max_retries=3,
    )
    async def collect_report_data(
        report_type: str,
        start_date: str,
        end_date: str,
        filters: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Step 1: Collect raw data for report generation.

        This is the first step in a report generation pipeline.
        It queries the database and prepares data for formatting.

        Args:
            report_type: Type of report ('sales', 'analytics', 'usage').
            start_date: ISO format date string for period start.
            end_date: ISO format date string for period end.
            filters: Optional filters to apply (e.g., {"region": "US"}).

        Returns:
            Dictionary containing raw data and metadata.
        """
        logger.info(
            "Collecting report data",
            extra={
                "report_type": report_type,
                "start_date": start_date,
                "end_date": end_date,
                "filters": filters,
            },
        )

        # Simulate data collection
        await asyncio.sleep(0.5)  # Simulate DB query time

        # In production: complex queries across multiple tables
        data = {
            "report_type": report_type,
            "period": {"start": start_date, "end": end_date},
            "filters": filters or {},
            "rows": [
                {"date": "2025-01-01", "revenue": 10000, "users": 100},
                {"date": "2025-01-02", "revenue": 12000, "users": 120},
                {"date": "2025-01-03", "revenue": 11500, "users": 115},
            ],
            "summary": {
                "total_revenue": 33500,
                "total_users": 335,
                "avg_daily_revenue": 11166.67,
            },
            "collected_at": datetime.now(UTC).isoformat(),
        }

        logger.info(
            "Data collection completed",
            extra={
                "rows": len(data["rows"]),
                "total_revenue": data["summary"]["total_revenue"],
            },
        )

        return data

    @broker.task(
        task_name="reports.format_report",
        retry_on_error=True,
        max_retries=2,
    )
    async def format_report(
        data: dict[str, Any],
        output_format: str = "pdf",
    ) -> dict[str, Any]:
        """Step 2: Format collected data into specified output format.

        This task receives data from collect_report_data and formats it.
        Demonstrates result passing between chained tasks.

        Args:
            data: Raw data from collect_report_data task.
            output_format: Output format ('pdf', 'csv', 'excel', 'html').

        Returns:
            Dictionary containing formatted report metadata and file path.
        """
        logger.info(
            "Formatting report",
            extra={
                "report_type": data.get("report_type"),
                "format": output_format,
                "rows": len(data.get("rows", [])),
            },
        )

        # Simulate report formatting
        await asyncio.sleep(1.0)  # Simulate formatting time

        # In production: use libraries like ReportLab (PDF), xlsxwriter (Excel)
        report_filename = (
            f"report_{datetime.now(UTC).strftime('%Y%m%d_%H%M%S')}.{output_format}"
        )
        REPORT_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        report_path = REPORT_OUTPUT_DIR / report_filename

        # Simulate file generation
        formatted_report = {
            "file_path": str(report_path),
            "filename": report_filename,
            "format": output_format,
            "size_bytes": 1024 * 150,  # 150 KB
            "pages": 5 if output_format == "pdf" else None,
            "rows": len(data.get("rows", [])),
            "generated_at": datetime.now(UTC).isoformat(),
            "metadata": {
                "title": f"{data.get('report_type', 'Unknown').title()} Report",
                "period": data.get("period"),
                "summary": data.get("summary"),
            },
        }

        logger.info(
            "Report formatting completed",
            extra={"filename": report_filename, "size_kb": 150},
        )

        return formatted_report

    @broker.task(
        task_name="reports.deliver_report",
        retry_on_error=True,
        max_retries=3,
    )
    async def deliver_report(
        report: dict[str, Any],
        recipients: list[str],
        delivery_method: str = "email",
    ) -> dict[str, Any]:
        """Step 3: Deliver formatted report to recipients.

        This is the final step in the report generation pipeline.
        Demonstrates task completion and notification.

        Args:
            report: Formatted report metadata from format_report task.
            recipients: List of email addresses or user IDs.
            delivery_method: Delivery method ('email', 's3', 'sftp').

        Returns:
            Delivery confirmation with timestamps and recipient status.
        """
        logger.info(
            "Delivering report",
            extra={
                "filename": report.get("filename"),
                "recipients": len(recipients),
                "method": delivery_method,
            },
        )

        # Simulate report delivery
        await asyncio.sleep(0.5)  # Simulate email/upload time

        delivery_results = [
            {
                "recipient": recipient,
                "status": "delivered",
                "delivered_at": datetime.now(UTC).isoformat(),
            }
            for recipient in recipients
        ]

        result = {
            "status": "success",
            "report": report.get("filename"),
            "delivery_method": delivery_method,
            "recipients": recipients,
            "delivery_results": delivery_results,
            "completed_at": datetime.now(UTC).isoformat(),
        }

        logger.info(
            "Report delivery completed",
            extra={
                "filename": report.get("filename"),
                "delivered_to": len(recipients),
            },
        )

        return result


# =============================================================================
# Orchestration Tasks (Task Chaining and Workflows)
# =============================================================================


if broker is not None:

    @broker.task(
        task_name="reports.generate_and_deliver",
        retry_on_error=False,  # We handle retries at the step level
    )
    async def generate_and_deliver_report(
        report_type: str,
        start_date: str,
        end_date: str,
        output_format: str = "pdf",
        recipients: list[str] | None = None,
        filters: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Orchestrate full report generation and delivery workflow.

        This demonstrates TASK CHAINING pattern:
        1. Collect data → 2. Format report → 3. Deliver report

        Each step is a separate task that can be retried independently.
        Results are passed from one step to the next.

        Pattern: Sequential execution with result passing
        - Each task produces output consumed by next task
        - Intermediate results are stored in result backend
        - If a step fails, only that step is retried
        - Entire workflow can be monitored as single logical unit

        Args:
            report_type: Type of report ('sales', 'analytics', 'usage').
            start_date: ISO format date string for period start.
            end_date: ISO format date string for period end.
            output_format: Output format ('pdf', 'csv', 'excel', 'html').
            recipients: List of email addresses for delivery.
            filters: Optional filters to apply.

        Returns:
            Workflow completion status with results from each step.

        Example:
            # Start the full workflow
            task = await generate_and_deliver_report.kiq(
                report_type="sales",
                start_date="2025-01-01",
                end_date="2025-01-31",
                output_format="pdf",
                recipients=["manager@example.com", "ceo@example.com"],
                filters={"region": "US"},
            )

            # Wait for completion
            result = await task.wait_result(timeout=60)
            print(f"Report delivered: {result.return_value}")
        """
        workflow_id = f"report_{datetime.now(UTC).strftime('%Y%m%d_%H%M%S')}"
        recipients = recipients or ["admin@example.com"]

        logger.info(
            "Starting report generation workflow",
            extra={
                "workflow_id": workflow_id,
                "report_type": report_type,
                "format": output_format,
            },
        )

        workflow_result: dict[str, Any] = {
            "workflow_id": workflow_id,
            "status": "in_progress",
            "started_at": datetime.now(UTC).isoformat(),
            "steps": {},
        }

        try:
            # Step 1: Collect data
            logger.info("Step 1: Collecting data")
            step1_task = await collect_report_data.kiq(
                report_type=report_type,
                start_date=start_date,
                end_date=end_date,
                filters=filters,
            )

            # Wait for step 1 to complete
            step1_result = await step1_task.wait_result(timeout=30)

            if not step1_result.is_err:
                workflow_result["steps"]["collect_data"] = {
                    "status": "success",
                    "task_id": step1_task.task_id,
                    "completed_at": datetime.now(UTC).isoformat(),
                }
                data = step1_result.return_value
            else:
                msg = f"Data collection failed: {step1_result.error}"
                raise Exception(msg)

            # Step 2: Format report
            logger.info("Step 2: Formatting report")
            step2_task = await format_report.kiq(
                data=data,
                output_format=output_format,
            )

            step2_result = await step2_task.wait_result(timeout=60)

            if not step2_result.is_err:
                workflow_result["steps"]["format_report"] = {
                    "status": "success",
                    "task_id": step2_task.task_id,
                    "completed_at": datetime.now(UTC).isoformat(),
                }
                report = step2_result.return_value
            else:
                msg = f"Report formatting failed: {step2_result.error}"
                raise Exception(msg)

            # Step 3: Deliver report
            logger.info("Step 3: Delivering report")
            step3_task = await deliver_report.kiq(
                report=report,
                recipients=recipients,
                delivery_method="email",
            )

            step3_result = await step3_task.wait_result(timeout=30)

            if not step3_result.is_err:
                workflow_result["steps"]["deliver_report"] = {
                    "status": "success",
                    "task_id": step3_task.task_id,
                    "completed_at": datetime.now(UTC).isoformat(),
                }
                delivery = step3_result.return_value
            else:
                msg = f"Report delivery failed: {step3_result.error}"
                raise Exception(msg)

            # Workflow completed successfully
            workflow_result["status"] = "completed"
            workflow_result["completed_at"] = datetime.now(UTC).isoformat()
            workflow_result["final_result"] = delivery

            logger.info(
                "Report workflow completed successfully",
                extra={"workflow_id": workflow_id, "report": report.get("filename")},
            )

            return workflow_result

        except Exception as e:
            workflow_result["status"] = "failed"
            workflow_result["error"] = str(e)
            workflow_result["failed_at"] = datetime.now(UTC).isoformat()

            logger.exception(
                "Report workflow failed",
                extra={"workflow_id": workflow_id, "error": str(e)},
            )

            return workflow_result

    @broker.task(
        task_name="reports.batch_generate",
        retry_on_error=False,
    )
    async def batch_generate_reports(
        report_specs: list[dict[str, Any]],
        parallel: bool = True,
    ) -> dict[str, Any]:
        """Generate multiple reports in batch.

        This demonstrates PARALLEL EXECUTION pattern (fan-out/fan-in):
        - Launch multiple report workflows simultaneously
        - Wait for all to complete
        - Aggregate results

        Pattern: Parallel batch processing
        - Useful for bulk operations (monthly reports for all clients)
        - Each report is independent and can fail without affecting others
        - Results include both successes and failures

        Args:
            report_specs: List of report specifications, each with:
                - report_type: Type of report
                - start_date: Period start
                - end_date: Period end
                - output_format: Desired format
                - recipients: List of emails
            parallel: If True, run reports in parallel. If False, sequential.

        Returns:
            Batch results with individual report statuses.

        Example:
            # Generate reports for multiple clients
            specs = [
                {
                    "report_type": "sales",
                    "start_date": "2025-01-01",
                    "end_date": "2025-01-31",
                    "output_format": "pdf",
                    "recipients": ["client1@example.com"],
                },
                {
                    "report_type": "sales",
                    "start_date": "2025-01-01",
                    "end_date": "2025-01-31",
                    "output_format": "excel",
                    "recipients": ["client2@example.com"],
                },
            ]

            task = await batch_generate_reports.kiq(
                report_specs=specs,
                parallel=True,
            )
        """
        batch_id = f"batch_{datetime.now(UTC).strftime('%Y%m%d_%H%M%S')}"

        logger.info(
            "Starting batch report generation",
            extra={
                "batch_id": batch_id,
                "count": len(report_specs),
                "parallel": parallel,
            },
        )

        batch_result: dict[str, Any] = {
            "batch_id": batch_id,
            "total_reports": len(report_specs),
            "parallel": parallel,
            "started_at": datetime.now(UTC).isoformat(),
            "reports": [],
        }

        if parallel:
            # Launch all reports in parallel
            tasks = []
            for idx, spec in enumerate(report_specs):
                task = await generate_and_deliver_report.kiq(
                    report_type=spec.get("report_type", "sales"),
                    start_date=spec["start_date"],
                    end_date=spec["end_date"],
                    output_format=spec.get("output_format", "pdf"),
                    recipients=spec.get("recipients", []),
                    filters=spec.get("filters"),
                )
                tasks.append((idx, task))

            # Wait for all to complete
            for idx, task in tasks:
                try:
                    result = await task.wait_result(timeout=120)
                    batch_result["reports"].append({
                        "index": idx,
                        "task_id": task.task_id,
                        "status": "success" if not result.is_err else "failed",
                        "result": result.return_value if not result.is_err else None,
                        "error": str(result.error) if result.is_err else None,
                    })
                except Exception as e:
                    batch_result["reports"].append({
                        "index": idx,
                        "task_id": task.task_id,
                        "status": "failed",
                        "error": str(e),
                    })
        else:
            # Sequential execution
            for idx, spec in enumerate(report_specs):
                try:
                    task = await generate_and_deliver_report.kiq(
                        report_type=spec.get("report_type", "sales"),
                        start_date=spec["start_date"],
                        end_date=spec["end_date"],
                        output_format=spec.get("output_format", "pdf"),
                        recipients=spec.get("recipients", []),
                        filters=spec.get("filters"),
                    )

                    result = await task.wait_result(timeout=120)
                    batch_result["reports"].append({
                        "index": idx,
                        "task_id": task.task_id,
                        "status": "success" if not result.is_err else "failed",
                        "result": result.return_value if not result.is_err else None,
                        "error": str(result.error) if result.is_err else None,
                    })
                except Exception as e:
                    batch_result["reports"].append({
                        "index": idx,
                        "status": "failed",
                        "error": str(e),
                    })

        # Calculate summary statistics
        successful = sum(1 for r in batch_result["reports"] if r["status"] == "success")
        failed = len(batch_result["reports"]) - successful

        batch_result["completed_at"] = datetime.now(UTC).isoformat()
        batch_result["summary"] = {
            "successful": successful,
            "failed": failed,
            "success_rate": (successful / len(report_specs) * 100)
            if report_specs
            else 0,
        }

        logger.info(
            "Batch report generation completed",
            extra={
                "batch_id": batch_id,
                "successful": successful,
                "failed": failed,
            },
        )

        return batch_result

    @broker.task(
        task_name="reports.conditional_report",
        retry_on_error=False,
    )
    async def generate_conditional_report(
        report_type: str,
        start_date: str,
        end_date: str,
        threshold_revenue: float = 100000.0,
    ) -> dict[str, Any]:
        """Generate report with conditional workflow.

        This demonstrates CONDITIONAL BRANCHING pattern:
        - Collect data
        - Check if data meets threshold
        - If yes: generate detailed PDF report
        - If no: generate simple CSV summary
        - Different delivery methods based on result

        Pattern: Conditional workflow execution
        - Business logic determines execution path
        - Different tasks execute based on intermediate results
        - Useful for alerts, escalations, tiered processing

        Args:
            report_type: Type of report.
            start_date: Period start.
            end_date: Period end.
            threshold_revenue: Revenue threshold for detailed reporting.

        Returns:
            Workflow result with conditional branch taken.

        Example:
            # High revenue → detailed PDF to executives
            # Low revenue → simple CSV to managers
            task = await generate_conditional_report.kiq(
                report_type="sales",
                start_date="2025-01-01",
                end_date="2025-01-31",
                threshold_revenue=100000.0,
            )
        """
        workflow_id = f"conditional_{datetime.now(UTC).strftime('%Y%m%d_%H%M%S')}"

        logger.info(
            "Starting conditional report workflow",
            extra={"workflow_id": workflow_id, "threshold": threshold_revenue},
        )

        try:
            # Step 1: Collect data
            data_task = await collect_report_data.kiq(
                report_type=report_type,
                start_date=start_date,
                end_date=end_date,
            )

            data_result = await data_task.wait_result(timeout=30)
            if data_result.is_err:
                msg = "Data collection failed"
                raise Exception(msg)

            data = data_result.return_value
            total_revenue = data["summary"]["total_revenue"]

            # Step 2: Conditional branching
            if total_revenue >= threshold_revenue:
                # High revenue → detailed PDF report to executives
                logger.info(
                    "Revenue exceeds threshold, generating detailed report",
                    extra={"revenue": total_revenue, "threshold": threshold_revenue},
                )

                format_task = await format_report.kiq(data=data, output_format="pdf")
                format_result = await format_task.wait_result(timeout=60)

                if format_result.is_err:
                    msg = "Report formatting failed"
                    raise Exception(msg)

                report = format_result.return_value

                delivery_task = await deliver_report.kiq(
                    report=report,
                    recipients=["ceo@example.com", "cfo@example.com"],
                    delivery_method="email",
                )

                branch_taken = "high_revenue"
                output_format = "pdf"
                recipients = ["ceo@example.com", "cfo@example.com"]

            else:
                # Low revenue → simple CSV to managers
                logger.info(
                    "Revenue below threshold, generating summary report",
                    extra={"revenue": total_revenue, "threshold": threshold_revenue},
                )

                format_task = await format_report.kiq(data=data, output_format="csv")
                format_result = await format_task.wait_result(timeout=60)

                if format_result.is_err:
                    msg = "Report formatting failed"
                    raise Exception(msg)

                report = format_result.return_value

                delivery_task = await deliver_report.kiq(
                    report=report,
                    recipients=["manager@example.com"],
                    delivery_method="email",
                )

                branch_taken = "low_revenue"
                output_format = "csv"
                recipients = ["manager@example.com"]

            delivery_result = await delivery_task.wait_result(timeout=30)
            if delivery_result.is_err:
                msg = "Report delivery failed"
                raise Exception(msg)

            result = {
                "workflow_id": workflow_id,
                "status": "completed",
                "branch_taken": branch_taken,
                "revenue": total_revenue,
                "threshold": threshold_revenue,
                "output_format": output_format,
                "recipients": recipients,
                "completed_at": datetime.now(UTC).isoformat(),
            }

            logger.info(
                "Conditional workflow completed",
                extra={"workflow_id": workflow_id, "branch": branch_taken},
            )

            return result

        except Exception as e:
            logger.exception("Conditional workflow failed", extra={"error": str(e)})
            return {
                "workflow_id": workflow_id,
                "status": "failed",
                "error": str(e),
                "failed_at": datetime.now(UTC).isoformat(),
            }
