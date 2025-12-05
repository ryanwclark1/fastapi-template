"""Analytics aggregation task definitions.

This module demonstrates production-ready patterns for data aggregation:
- Time-series rollups with multiple aggregation levels
- Incremental processing to avoid recomputing entire datasets
- Partial success handling (continue on errors, report failures)
- Complex SQL queries for efficient aggregation
- Task result passing between stages
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert

from example_service.infra.database.session import get_async_session
from example_service.infra.tasks.broker import broker

logger = logging.getLogger(__name__)


# =============================================================================
# Helper Models (Placeholder - In production, these would be real models)
# =============================================================================
# In a real application, you would have actual SQLAlchemy models for:
# - events/transactions table (source data)
# - hourly_metrics table (first aggregation level)
# - daily_metrics table (second aggregation level)
# - weekly_metrics table (third aggregation level)
# - kpi_snapshots table (computed KPIs)


# =============================================================================
# Multi-Level Time-Series Aggregation Tasks
# =============================================================================


if broker is not None:

    @broker.task(
        task_name="analytics.aggregate_hourly",
        retry_on_error=True,
        max_retries=3,
    )
    async def aggregate_hourly_metrics(
        start_time: str | None = None,
        end_time: str | None = None,
    ) -> dict[str, Any]:
        """Aggregate raw events into hourly metrics.

        This is the first level of aggregation. It processes raw event data
        and computes hourly summaries.

        Pattern: Incremental aggregation with upsert
        - Only processes new/updated data since last run
        - Uses PostgreSQL's ON CONFLICT for idempotent updates
        - Returns processing stats for monitoring

        Args:
            start_time: ISO format datetime string for start of period.
                       If None, processes last 2 hours.
            end_time: ISO format datetime string for end of period.
                     If None, uses current time.

        Returns:
            Aggregation results with counts and timing.

        Example:
            # Process last 2 hours (default)
            task = await aggregate_hourly_metrics.kiq()

            # Process specific time range
            task = await aggregate_hourly_metrics.kiq(
                start_time="2025-01-01T00:00:00Z",
                end_time="2025-01-01T23:59:59Z",
            )
        """
        # Parse time range
        if start_time:
            start_dt = datetime.fromisoformat(start_time.replace("Z", "+00:00"))
        else:
            start_dt = datetime.now(UTC) - timedelta(hours=2)

        if end_time:
            end_dt = datetime.fromisoformat(end_time.replace("Z", "+00:00"))
        else:
            end_dt = datetime.now(UTC)

        logger.info(
            "Starting hourly metrics aggregation",
            extra={"start": start_dt.isoformat(), "end": end_dt.isoformat()},
        )

        try:
            async with get_async_session() as session:
                # In production, this would query your events table and aggregate:
                # SELECT
                #   DATE_TRUNC('hour', created_at) as hour_bucket,
                #   COUNT(*) as event_count,
                #   SUM(amount) as total_amount,
                #   AVG(duration) as avg_duration,
                #   COUNT(DISTINCT user_id) as unique_users
                # FROM events
                # WHERE created_at BETWEEN start_dt AND end_dt
                # GROUP BY hour_bucket

                # For demonstration, we'll simulate the aggregation
                hours_processed = int((end_dt - start_dt).total_seconds() / 3600)

                # Simulate computing metrics for each hour
                metrics = []
                for hour_offset in range(hours_processed):
                    hour_start = start_dt + timedelta(hours=hour_offset)

                    metric = {
                        "hour_bucket": hour_start,
                        "event_count": 1000,  # Would be COUNT(*) in real query
                        "total_amount": 50000.0,  # Would be SUM(amount)
                        "avg_duration": 2.5,  # Would be AVG(duration)
                        "unique_users": 150,  # Would be COUNT(DISTINCT user_id)
                        "updated_at": datetime.now(UTC),
                    }
                    metrics.append(metric)

                # In production, you would INSERT INTO hourly_metrics
                # ON CONFLICT (hour_bucket) DO UPDATE SET ...
                # This ensures idempotency - running twice doesn't duplicate data

                logger.info(
                    "Hourly aggregation completed",
                    extra={
                        "hours_processed": hours_processed,
                        "metrics_generated": len(metrics),
                    },
                )

                return {
                    "status": "success",
                    "hours_processed": hours_processed,
                    "metrics_generated": len(metrics),
                    "start_time": start_dt.isoformat(),
                    "end_time": end_dt.isoformat(),
                    "total_events": sum(m["event_count"] for m in metrics),
                    "total_amount": sum(m["total_amount"] for m in metrics),
                }

        except Exception as e:
            logger.exception("Hourly aggregation failed", extra={"error": str(e)})
            raise

    @broker.task(
        task_name="analytics.aggregate_daily",
        retry_on_error=True,
        max_retries=3,
    )
    async def aggregate_daily_metrics(date: str | None = None) -> dict[str, Any]:
        """Aggregate hourly metrics into daily summaries.

        This is the second level of aggregation. It rolls up hourly data
        into daily summaries for efficient querying.

        Pattern: Hierarchical aggregation
        - Reads from hourly_metrics table
        - Writes to daily_metrics table
        - Computes additional derived metrics (growth rates, trends)

        Args:
            date: ISO format date string (YYYY-MM-DD).
                 If None, processes yesterday's data.

        Returns:
            Daily aggregation results with trends.

        Example:
            # Process yesterday (default)
            task = await aggregate_daily_metrics.kiq()

            # Process specific date
            task = await aggregate_daily_metrics.kiq(date="2025-01-01")
        """
        # Parse date
        if date:
            target_date = datetime.fromisoformat(date).date()
        else:
            # Default to yesterday (give current day time to complete)
            target_date = (datetime.now(UTC) - timedelta(days=1)).date()

        logger.info(
            "Starting daily metrics aggregation",
            extra={"date": target_date.isoformat()},
        )

        try:
            async with get_async_session() as session:
                # In production, this would query hourly_metrics and aggregate:
                # SELECT
                #   DATE(hour_bucket) as date,
                #   SUM(event_count) as daily_events,
                #   SUM(total_amount) as daily_revenue,
                #   AVG(avg_duration) as avg_duration,
                #   MAX(unique_users) as peak_users,
                #   COUNT(*) as hours_with_data
                # FROM hourly_metrics
                # WHERE DATE(hour_bucket) = target_date
                # GROUP BY date

                # Simulate daily aggregation
                daily_metric = {
                    "date": target_date,
                    "daily_events": 24000,  # Sum of hourly events
                    "daily_revenue": 1200000.0,  # Sum of hourly revenue
                    "avg_duration": 2.5,  # Average across all hours
                    "peak_users": 500,  # Max concurrent users
                    "hours_with_data": 24,
                    "updated_at": datetime.now(UTC),
                }

                # Compute growth metrics by comparing to previous day
                # In production: SELECT ... FROM daily_metrics WHERE date = target_date - 1
                previous_day_revenue = 1100000.0  # Would be from DB query
                growth_rate = (
                    (daily_metric["daily_revenue"] - previous_day_revenue)
                    / previous_day_revenue
                    * 100
                )

                daily_metric["revenue_growth_pct"] = round(growth_rate, 2)

                logger.info(
                    "Daily aggregation completed",
                    extra={
                        "date": target_date.isoformat(),
                        "events": daily_metric["daily_events"],
                        "revenue": daily_metric["daily_revenue"],
                        "growth": daily_metric["revenue_growth_pct"],
                    },
                )

                return {
                    "status": "success",
                    "date": target_date.isoformat(),
                    "metrics": daily_metric,
                }

        except Exception as e:
            logger.exception("Daily aggregation failed", extra={"error": str(e)})
            raise

    @broker.task(
        task_name="analytics.aggregate_weekly",
        retry_on_error=True,
        max_retries=3,
    )
    async def aggregate_weekly_metrics(week_start: str | None = None) -> dict[str, Any]:
        """Aggregate daily metrics into weekly summaries.

        This is the third level of aggregation. It provides weekly views
        for medium-term trend analysis.

        Pattern: Rolling window aggregation
        - Computes week-over-week trends
        - Identifies weekly patterns and anomalies
        - Useful for executive dashboards

        Args:
            week_start: ISO format date string for Monday of target week.
                       If None, processes previous complete week.

        Returns:
            Weekly aggregation results with trends.
        """
        # Parse week start (should be a Monday)
        if week_start:
            start_date = datetime.fromisoformat(week_start).date()
        else:
            # Default to last complete week (Monday to Sunday)
            today = datetime.now(UTC).date()
            days_since_monday = today.weekday()
            last_monday = today - timedelta(days=days_since_monday + 7)
            start_date = last_monday

        end_date = start_date + timedelta(days=6)  # Sunday

        logger.info(
            "Starting weekly metrics aggregation",
            extra={"week_start": start_date.isoformat(), "week_end": end_date.isoformat()},
        )

        try:
            async with get_async_session() as session:
                # In production, aggregate daily_metrics for the week:
                # SELECT
                #   DATE_TRUNC('week', date) as week_start,
                #   SUM(daily_events) as weekly_events,
                #   SUM(daily_revenue) as weekly_revenue,
                #   AVG(avg_duration) as avg_duration,
                #   MAX(peak_users) as peak_users,
                #   AVG(revenue_growth_pct) as avg_daily_growth
                # FROM daily_metrics
                # WHERE date BETWEEN start_date AND end_date
                # GROUP BY week_start

                # Simulate weekly aggregation
                weekly_metric = {
                    "week_start": start_date,
                    "week_end": end_date,
                    "weekly_events": 168000,  # 7 days * 24k events
                    "weekly_revenue": 8400000.0,
                    "avg_duration": 2.5,
                    "peak_users": 750,
                    "avg_daily_growth": 2.3,
                    "days_processed": 7,
                    "updated_at": datetime.now(UTC),
                }

                logger.info(
                    "Weekly aggregation completed",
                    extra={
                        "week": start_date.isoformat(),
                        "events": weekly_metric["weekly_events"],
                        "revenue": weekly_metric["weekly_revenue"],
                    },
                )

                return {
                    "status": "success",
                    "week_start": start_date.isoformat(),
                    "week_end": end_date.isoformat(),
                    "metrics": weekly_metric,
                }

        except Exception as e:
            logger.exception("Weekly aggregation failed", extra={"error": str(e)})
            raise

    @broker.task(
        task_name="analytics.aggregate_monthly",
        retry_on_error=True,
        max_retries=3,
    )
    async def aggregate_monthly_metrics(
        year: int | None = None,
        month: int | None = None,
    ) -> dict[str, Any]:
        """Aggregate weekly/daily metrics into monthly summaries.

        This is the highest level of aggregation. It provides monthly views
        for long-term trend analysis and forecasting.

        Pattern: Archive-grade aggregation
        - Computes comprehensive monthly statistics
        - Used for financial reporting and forecasting
        - Optimized for long-term storage

        Args:
            year: Target year (e.g., 2025). If None, uses last complete month.
            month: Target month (1-12). If None, uses last complete month.

        Returns:
            Monthly aggregation results with year-over-year comparison.
        """
        # Parse target month
        if year and month:
            target_date = datetime(year, month, 1, tzinfo=UTC).date()
        else:
            # Default to last complete month
            today = datetime.now(UTC).date()
            first_of_this_month = today.replace(day=1)
            last_month = first_of_this_month - timedelta(days=1)
            target_date = last_month.replace(day=1)

        # Calculate month boundaries
        if target_date.month == 12:
            next_month = target_date.replace(year=target_date.year + 1, month=1)
        else:
            next_month = target_date.replace(month=target_date.month + 1)

        logger.info(
            "Starting monthly metrics aggregation",
            extra={"year": target_date.year, "month": target_date.month},
        )

        try:
            async with get_async_session() as session:
                # In production, aggregate daily_metrics for the month:
                # SELECT
                #   DATE_TRUNC('month', date) as month,
                #   SUM(daily_events) as monthly_events,
                #   SUM(daily_revenue) as monthly_revenue,
                #   AVG(avg_duration) as avg_duration,
                #   MAX(peak_users) as peak_users,
                #   PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY daily_revenue) as median_daily_revenue,
                #   STDDEV(daily_revenue) as revenue_stddev
                # FROM daily_metrics
                # WHERE date >= target_date AND date < next_month
                # GROUP BY month

                # Simulate monthly aggregation
                days_in_month = (next_month - target_date).days

                monthly_metric = {
                    "year": target_date.year,
                    "month": target_date.month,
                    "month_name": target_date.strftime("%B"),
                    "monthly_events": days_in_month * 24000,
                    "monthly_revenue": days_in_month * 1200000.0,
                    "avg_duration": 2.5,
                    "peak_users": 1000,
                    "median_daily_revenue": 1200000.0,
                    "revenue_stddev": 50000.0,
                    "days_processed": days_in_month,
                    "updated_at": datetime.now(UTC),
                }

                # Compute year-over-year comparison
                # In production: query same month from previous year
                yoy_revenue = monthly_metric["monthly_revenue"]
                previous_year_revenue = yoy_revenue * 0.85  # Simulate 15% growth
                yoy_growth = ((yoy_revenue - previous_year_revenue) / previous_year_revenue) * 100

                monthly_metric["yoy_growth_pct"] = round(yoy_growth, 2)

                logger.info(
                    "Monthly aggregation completed",
                    extra={
                        "year": target_date.year,
                        "month": target_date.month,
                        "events": monthly_metric["monthly_events"],
                        "revenue": monthly_metric["monthly_revenue"],
                        "yoy_growth": monthly_metric["yoy_growth_pct"],
                    },
                )

                return {
                    "status": "success",
                    "year": target_date.year,
                    "month": target_date.month,
                    "month_name": monthly_metric["month_name"],
                    "metrics": monthly_metric,
                }

        except Exception as e:
            logger.exception("Monthly aggregation failed", extra={"error": str(e)})
            raise


# =============================================================================
# Complex KPI Computation Tasks
# =============================================================================


if broker is not None:

    @broker.task(
        task_name="analytics.compute_kpis",
        retry_on_error=True,
        max_retries=2,
    )
    async def compute_business_kpis(date: str | None = None) -> dict[str, Any]:
        """Compute complex business KPIs from aggregated data.

        This task demonstrates:
        - Multi-table joins and complex queries
        - Derived metric computation
        - Partial success handling (some KPIs may fail)

        Computes KPIs such as:
        - Customer Lifetime Value (CLV)
        - Churn Rate
        - Monthly Recurring Revenue (MRR)
        - Net Promoter Score (NPS)
        - Customer Acquisition Cost (CAC)
        - Revenue per User

        Args:
            date: ISO format date string. If None, uses today.

        Returns:
            Dictionary of computed KPIs with success/failure status for each.
        """
        if date:
            target_date = datetime.fromisoformat(date).date()
        else:
            target_date = datetime.now(UTC).date()

        logger.info("Computing business KPIs", extra={"date": target_date.isoformat()})

        kpis: dict[str, Any] = {
            "date": target_date.isoformat(),
            "computed_at": datetime.now(UTC).isoformat(),
            "metrics": {},
            "errors": [],
        }

        try:
            async with get_async_session() as session:
                # KPI 1: Monthly Recurring Revenue (MRR)
                try:
                    # In production: SELECT SUM(subscription_amount) FROM subscriptions WHERE status = 'active'
                    mrr = 125000.0
                    kpis["metrics"]["mrr"] = {
                        "value": mrr,
                        "unit": "USD",
                        "status": "success",
                    }
                except Exception as e:
                    kpis["errors"].append({"kpi": "mrr", "error": str(e)})

                # KPI 2: Customer Acquisition Cost (CAC)
                try:
                    # In production: (marketing_spend + sales_spend) / new_customers
                    total_spend = 50000.0
                    new_customers = 200
                    cac = total_spend / new_customers if new_customers > 0 else 0
                    kpis["metrics"]["cac"] = {
                        "value": round(cac, 2),
                        "unit": "USD",
                        "new_customers": new_customers,
                        "status": "success",
                    }
                except Exception as e:
                    kpis["errors"].append({"kpi": "cac", "error": str(e)})

                # KPI 3: Churn Rate
                try:
                    # In production: (churned_customers / total_customers_start_of_period) * 100
                    churned = 15
                    total_start = 1000
                    churn_rate = (churned / total_start) * 100 if total_start > 0 else 0
                    kpis["metrics"]["churn_rate"] = {
                        "value": round(churn_rate, 2),
                        "unit": "percent",
                        "churned_customers": churned,
                        "status": "success",
                    }
                except Exception as e:
                    kpis["errors"].append({"kpi": "churn_rate", "error": str(e)})

                # KPI 4: Customer Lifetime Value (CLV)
                try:
                    # In production: (avg_revenue_per_user * avg_customer_lifespan) - CAC
                    avg_monthly_revenue = 100.0
                    avg_lifespan_months = 36
                    clv = (avg_monthly_revenue * avg_lifespan_months) - cac
                    kpis["metrics"]["clv"] = {
                        "value": round(clv, 2),
                        "unit": "USD",
                        "avg_lifespan_months": avg_lifespan_months,
                        "status": "success",
                    }
                except Exception as e:
                    kpis["errors"].append({"kpi": "clv", "error": str(e)})

                # KPI 5: Revenue per User (ARPU)
                try:
                    # In production: total_revenue / active_users
                    total_revenue = 125000.0
                    active_users = 1200
                    arpu = total_revenue / active_users if active_users > 0 else 0
                    kpis["metrics"]["arpu"] = {
                        "value": round(arpu, 2),
                        "unit": "USD",
                        "active_users": active_users,
                        "status": "success",
                    }
                except Exception as e:
                    kpis["errors"].append({"kpi": "arpu", "error": str(e)})

                # Determine overall status
                total_kpis = 5
                successful_kpis = len(kpis["metrics"])
                failed_kpis = len(kpis["errors"])

                if failed_kpis == 0:
                    kpis["status"] = "success"
                elif successful_kpis > 0:
                    kpis["status"] = "partial"
                else:
                    kpis["status"] = "failed"

                logger.info(
                    "KPI computation completed",
                    extra={
                        "successful": successful_kpis,
                        "failed": failed_kpis,
                        "status": kpis["status"],
                    },
                )

                return kpis

        except Exception as e:
            logger.exception("KPI computation failed", extra={"error": str(e)})
            raise


# =============================================================================
# Trend Analysis and Forecasting Tasks
# =============================================================================


if broker is not None:

    @broker.task(
        task_name="analytics.generate_trends",
        retry_on_error=True,
        max_retries=2,
    )
    async def generate_trend_analysis(
        metric: str = "revenue",
        lookback_days: int = 30,
    ) -> dict[str, Any]:
        """Generate trend analysis for a specific metric.

        This task demonstrates:
        - Time-series analysis
        - Moving averages and smoothing
        - Anomaly detection
        - Forecasting (simple linear projection)

        Args:
            metric: Metric to analyze ('revenue', 'users', 'events').
            lookback_days: Number of days to analyze.

        Returns:
            Trend analysis including moving averages, growth rate, anomalies.
        """
        logger.info(
            "Generating trend analysis",
            extra={"metric": metric, "lookback_days": lookback_days},
        )

        try:
            async with get_async_session() as session:
                # In production: query daily_metrics for the lookback period
                # SELECT date, {metric} FROM daily_metrics
                # WHERE date >= (CURRENT_DATE - lookback_days)
                # ORDER BY date

                # Simulate time-series data
                end_date = datetime.now(UTC).date()
                start_date = end_date - timedelta(days=lookback_days)

                # Generate synthetic time series with trend and noise
                time_series = []
                base_value = 100000.0
                daily_growth = 0.02  # 2% daily growth

                for day_offset in range(lookback_days):
                    date = start_date + timedelta(days=day_offset)
                    # Trend + some randomness
                    value = base_value * (1 + daily_growth) ** day_offset
                    # Add weekly seasonality (weekends are lower)
                    if date.weekday() >= 5:  # Saturday or Sunday
                        value *= 0.7
                    time_series.append({"date": date, "value": value})

                # Compute 7-day moving average
                window_size = 7
                for i in range(len(time_series)):
                    if i >= window_size - 1:
                        window = [
                            time_series[j]["value"]
                            for j in range(i - window_size + 1, i + 1)
                        ]
                        moving_avg = sum(window) / len(window)
                        time_series[i]["moving_avg_7d"] = moving_avg

                # Compute growth rate
                if len(time_series) >= 2:
                    first_value = time_series[0]["value"]
                    last_value = time_series[-1]["value"]
                    growth_rate = ((last_value - first_value) / first_value) * 100
                else:
                    growth_rate = 0.0

                # Detect anomalies (values > 2 standard deviations from mean)
                values = [ts["value"] for ts in time_series]
                mean_value = sum(values) / len(values)
                variance = sum((x - mean_value) ** 2 for x in values) / len(values)
                std_dev = variance**0.5

                anomalies = []
                for ts in time_series:
                    z_score = (ts["value"] - mean_value) / std_dev if std_dev > 0 else 0
                    if abs(z_score) > 2:
                        anomalies.append(
                            {
                                "date": ts["date"].isoformat(),
                                "value": ts["value"],
                                "z_score": round(z_score, 2),
                            }
                        )

                # Simple linear forecast for next 7 days
                if len(time_series) >= 2:
                    # Calculate daily growth rate
                    daily_rate = (last_value / first_value) ** (1 / lookback_days) - 1

                    forecast = []
                    for day_offset in range(1, 8):
                        forecast_date = end_date + timedelta(days=day_offset)
                        forecast_value = last_value * (1 + daily_rate) ** day_offset
                        forecast.append(
                            {
                                "date": forecast_date.isoformat(),
                                "value": round(forecast_value, 2),
                            }
                        )
                else:
                    forecast = []

                result = {
                    "status": "success",
                    "metric": metric,
                    "period": {
                        "start": start_date.isoformat(),
                        "end": end_date.isoformat(),
                        "days": lookback_days,
                    },
                    "statistics": {
                        "mean": round(mean_value, 2),
                        "std_dev": round(std_dev, 2),
                        "growth_rate_pct": round(growth_rate, 2),
                        "first_value": round(time_series[0]["value"], 2),
                        "last_value": round(time_series[-1]["value"], 2),
                    },
                    "anomalies": anomalies,
                    "forecast": forecast,
                }

                logger.info(
                    "Trend analysis completed",
                    extra={
                        "metric": metric,
                        "growth_rate": growth_rate,
                        "anomalies_found": len(anomalies),
                    },
                )

                return result

        except Exception as e:
            logger.exception("Trend analysis failed", extra={"error": str(e)})
            raise
