"""Email management CLI commands.

This module provides CLI commands for managing email:
- Test email configuration
- View email usage statistics
- Manage email configurations
- List available providers
"""

import sys

import click

from example_service.cli.utils import (
    coro,
    error,
    header,
    info,
    section,
    success,
    warning,
)


@click.group(name="email")
def email() -> None:
    """Email management commands.

    Commands for testing email configuration, viewing usage
    statistics, and managing email providers.
    """


@email.command(name="test")
@click.option(
    "--tenant-id",
    "-t",
    required=True,
    help="Tenant ID to test email for",
)
@click.option(
    "--to",
    "-r",
    "recipient",
    required=True,
    help="Recipient email address",
)
@click.option(
    "--use-system",
    is_flag=True,
    help="Use system defaults instead of tenant config",
)
@coro
async def test_email(tenant_id: str, recipient: str, use_system: bool) -> None:
    """Send a test email to verify configuration.

    Sends a test email and reports delivery status.

    Examples:
    \b
      example-service email test -t tenant-123 --to admin@example.com
    """
    from example_service.features.email.service import EmailConfigService
    from example_service.infra.database.session import async_sessionmaker
    from example_service.infra.email.enhanced_service import get_email_service

    header("Sending Test Email")
    info(f"Tenant: {tenant_id}")
    info(f"Recipient: {recipient}")

    async with async_sessionmaker() as session:
        email_service = await get_email_service()
        service = EmailConfigService(session, email_service)

        result = await service.test_config(
            tenant_id,
            recipient,
            use_tenant_config=not use_system,
        )

        click.echo()
        if result.success:
            success("Test email sent successfully!")
            click.echo(f"  Message ID: {result.message_id}")
            click.echo(f"  Provider: {result.provider}")
            click.echo(f"  Duration: {result.duration_ms}ms")
        else:
            error("Test email failed!")
            if result.error:
                click.secho(f"  Error: {result.error}", fg="red")
            if result.error_code:
                click.echo(f"  Error Code: {result.error_code}")
            click.echo(f"  Duration: {result.duration_ms}ms")
            sys.exit(1)


@email.command(name="config")
@click.argument("tenant_id")
@click.option(
    "--show-secrets",
    is_flag=True,
    help="Show sensitive values (API keys, passwords)",
)
@coro
async def show_config(tenant_id: str, show_secrets: bool) -> None:
    """Show email configuration for a tenant.

    TENANT_ID is the ID of the tenant.
    """
    from example_service.features.email.service import EmailConfigService
    from example_service.infra.database.session import async_sessionmaker
    from example_service.infra.email.enhanced_service import get_email_service

    header(f"Email Configuration: {tenant_id}")

    async with async_sessionmaker() as session:
        email_service = await get_email_service()
        service = EmailConfigService(session, email_service)
        config = await service.get_config(tenant_id)

        if not config:
            warning("No email configuration found for this tenant")
            info("Using system defaults")
            return

        section("Provider")
        click.echo(f"  Type: {config.provider_type}")
        status = click.style("Active", fg="green") if config.is_active else click.style("Inactive", fg="red")
        click.echo(f"  Status: {status}")

        section("Sender")
        click.echo(f"  From Email: {config.from_email}")
        click.echo(f"  From Name: {config.from_name or 'Not set'}")
        if config.reply_to:
            click.echo(f"  Reply To: {config.reply_to}")

        section("Provider Settings")
        if config.provider_type == "smtp":
            click.echo(f"  SMTP Host: {config.smtp_host}")
            click.echo(f"  SMTP Port: {config.smtp_port}")
            click.echo(f"  SMTP Username: {config.smtp_username or 'Not set'}")
            if show_secrets and config.smtp_password:
                click.echo(f"  SMTP Password: {config.smtp_password}")
            else:
                click.echo(f"  SMTP Password: {'******' if config.smtp_password else 'Not set'}")
            click.echo(f"  TLS: {config.smtp_use_tls}")
            click.echo(f"  SSL: {config.smtp_use_ssl}")
        elif config.provider_type in ("sendgrid", "mailgun"):
            if show_secrets and config.api_key:
                click.echo(f"  API Key: {config.api_key}")
            else:
                click.echo(f"  API Key: {'******' if config.api_key else 'Not set'}")
        elif config.provider_type == "aws_ses":
            click.echo(f"  AWS Region: {config.aws_region}")
            if show_secrets:
                click.echo(f"  AWS Access Key: {config.aws_access_key}")
            else:
                click.echo(f"  AWS Access Key: {'******' if config.aws_access_key else 'Not set'}")

        section("Rate Limiting")
        click.echo(f"  Enabled: {config.rate_limit_enabled}")
        if config.rate_limit_enabled:
            click.echo(f"  Per Minute: {config.rate_limit_per_minute}")
            click.echo(f"  Per Hour: {config.rate_limit_per_hour}")
            click.echo(f"  Per Day: {config.rate_limit_per_day}")

        section("Timestamps")
        click.echo(f"  Created: {config.created_at.strftime('%Y-%m-%d %H:%M:%S')}")
        click.echo(f"  Updated: {config.updated_at.strftime('%Y-%m-%d %H:%M:%S')}")

        success("Configuration retrieved")


@email.command(name="usage")
@click.option(
    "--tenant-id",
    "-t",
    required=True,
    help="Tenant ID to show usage for",
)
@click.option(
    "--days",
    default=30,
    type=int,
    help="Number of days to analyze (default: 30)",
)
@coro
async def show_usage(tenant_id: str, days: int) -> None:
    """Show email usage statistics for a tenant.

    Displays send counts, success rates, and costs by provider.
    """
    from datetime import UTC, datetime, timedelta

    from example_service.features.email.service import EmailConfigService
    from example_service.infra.database.session import async_sessionmaker
    from example_service.infra.email.enhanced_service import get_email_service

    header(f"Email Usage: {tenant_id}")
    info(f"Period: Last {days} days")

    start_date = datetime.now(UTC) - timedelta(days=days)
    end_date = datetime.now(UTC)

    async with async_sessionmaker() as session:
        email_service = await get_email_service()
        service = EmailConfigService(session, email_service)

        stats = await service.get_usage_stats(
            tenant_id,
            start_date=start_date,
            end_date=end_date,
        )

        section("Summary")
        click.echo(f"  Total Emails: {stats.total_emails:,}")
        click.echo(f"  Successful: {stats.successful_emails:,}")
        click.echo(f"  Failed: {stats.failed_emails:,}")

        if stats.total_emails > 0:
            success_color = "green" if stats.success_rate >= 95 else "yellow" if stats.success_rate >= 80 else "red"
            click.secho(f"  Success Rate: {stats.success_rate:.1f}%", fg=success_color)

        click.echo(f"  Total Recipients: {stats.total_recipients:,}")

        if stats.rate_limit_hits > 0:
            click.secho(f"  Rate Limit Hits: {stats.rate_limit_hits}", fg="yellow")

        if stats.emails_by_provider:
            section("By Provider")
            for provider, count in stats.emails_by_provider.items():
                pct = (count / stats.total_emails * 100) if stats.total_emails else 0
                click.echo(f"  {provider}: {count:,} ({pct:.1f}%)")

        if stats.total_cost_usd is not None and stats.total_cost_usd > 0:
            section("Costs")
            click.echo(f"  Total Cost: ${stats.total_cost_usd:.4f}")
            if stats.cost_by_provider:
                for provider, cost in stats.cost_by_provider.items():
                    click.echo(f"  {provider}: ${cost:.4f}")

        success("Usage stats retrieved")


@email.command(name="health")
@click.option(
    "--tenant-id",
    "-t",
    required=True,
    help="Tenant ID to check health for",
)
@coro
async def check_health(tenant_id: str) -> None:
    """Check email provider health for a tenant.

    Verifies connectivity and configuration with the email provider.
    """
    from example_service.features.email.service import EmailConfigService
    from example_service.infra.database.session import async_sessionmaker
    from example_service.infra.email.enhanced_service import get_email_service

    header(f"Email Health Check: {tenant_id}")

    async with async_sessionmaker() as session:
        email_service = await get_email_service()
        service = EmailConfigService(session, email_service)

        is_healthy, response_time, error_msg = await service.check_health(tenant_id)

        click.echo()
        if is_healthy:
            success("Email provider is healthy")
            if response_time:
                click.echo(f"  Response Time: {response_time}ms")
        else:
            error("Email provider health check failed")
            if error_msg:
                click.secho(f"  Error: {error_msg}", fg="red")
            sys.exit(1)


@email.command(name="providers")
@coro
async def list_providers() -> None:
    """List available email providers.

    Shows supported providers with their requirements and capabilities.
    """
    from example_service.features.email.service import EmailConfigService
    from example_service.infra.database.session import async_sessionmaker
    from example_service.infra.email.enhanced_service import get_email_service

    header("Available Email Providers")

    async with async_sessionmaker() as session:
        email_service = await get_email_service()
        service = EmailConfigService(session, email_service)
        providers = service.get_available_providers()

        for provider in providers:
            section(provider["name"])
            click.echo(f"  Type: {provider['provider_type'].value}")
            click.echo(f"  Description: {provider['description']}")

            if provider["required_fields"]:
                click.echo(f"  Required: {', '.join(provider['required_fields'])}")
            if provider["optional_fields"]:
                click.echo(f"  Optional: {', '.join(provider['optional_fields'])}")

            features = []
            if provider["supports_html"]:
                features.append("HTML")
            if provider["supports_attachments"]:
                features.append("Attachments")
            if provider["supports_templates"]:
                features.append("Templates")
            click.echo(f"  Features: {', '.join(features) if features else 'Basic'}")

            if provider["estimated_cost_per_1000"] is not None:
                click.echo(f"  Est. Cost: ${provider['estimated_cost_per_1000']:.2f}/1000 emails")
            click.echo()

        success(f"Total: {len(providers)} providers available")


@email.command(name="audit")
@click.option(
    "--tenant-id",
    "-t",
    required=True,
    help="Tenant ID to show audit logs for",
)
@click.option(
    "--page",
    default=1,
    type=int,
    help="Page number (default: 1)",
)
@click.option(
    "--page-size",
    default=20,
    type=int,
    help="Items per page (default: 20)",
)
@coro
async def list_audit_logs(tenant_id: str, page: int, page_size: int) -> None:
    """Show email audit logs for a tenant.

    Displays email send history with status and details.
    """
    from example_service.features.email.service import EmailConfigService
    from example_service.infra.database.session import async_sessionmaker
    from example_service.infra.email.enhanced_service import get_email_service

    header(f"Email Audit Logs: {tenant_id}")
    info(f"Page {page} (size: {page_size})")

    async with async_sessionmaker() as session:
        email_service = await get_email_service()
        service = EmailConfigService(session, email_service)

        result = await service.get_audit_logs(
            tenant_id,
            page=page,
            page_size=page_size,
        )

        if not result.items:
            info("No audit logs found")
            return

        click.echo()
        for log in result.items:
            status_color = "green" if log.success else "red"
            status_icon = "+" if log.success else "x"

            click.echo(f"  [{log.created_at.strftime('%Y-%m-%d %H:%M:%S')}]")
            click.secho(f"    [{status_icon}] {log.event_type}", fg=status_color)
            click.echo(f"    Provider: {log.provider}")
            click.echo(f"    To: {log.recipient_count} recipient(s)")
            if log.message_id:
                click.echo(f"    Message ID: {log.message_id}")
            if log.error_message:
                click.secho(f"    Error: {log.error_message}", fg="red")
            click.echo()

        success(f"Showing page {page} of {(result.total + page_size - 1) // page_size}")


@email.command(name="send")
@click.option(
    "--tenant-id",
    "-t",
    required=True,
    help="Tenant ID to send from",
)
@click.option(
    "--to",
    "-r",
    "recipients",
    multiple=True,
    required=True,
    help="Recipient email address(es)",
)
@click.option(
    "--subject",
    "-s",
    required=True,
    help="Email subject",
)
@click.option(
    "--body",
    "-b",
    required=True,
    help="Email body (plain text)",
)
@click.option(
    "--html",
    help="HTML body (optional)",
)
@coro
async def send_email(
    tenant_id: str,
    recipients: tuple[str, ...],
    subject: str,
    body: str,
    html: str | None,
) -> None:
    """Send an email using tenant configuration.

    Examples:
    \b
      example-service email send -t tenant-123 --to user@example.com -s "Hello" -b "Test message"
    """
    from example_service.features.email.service import EmailConfigService
    from example_service.infra.database.session import async_sessionmaker
    from example_service.infra.email.enhanced_service import get_email_service

    header("Sending Email")
    info(f"Tenant: {tenant_id}")
    info(f"Recipients: {', '.join(recipients)}")
    info(f"Subject: {subject}")

    async with async_sessionmaker() as session:
        email_service = await get_email_service()
        service = EmailConfigService(session, email_service)

        try:
            result = await service.send_email(
                tenant_id,
                to=list(recipients),
                subject=subject,
                body=body,
                body_html=html,
            )

            click.echo()
            if result.success:
                success("Email sent successfully!")
                click.echo(f"  Message ID: {result.message_id}")
                click.echo(f"  Provider: {result.provider}")
                click.echo(f"  Recipients: {result.recipients_count}")
                click.echo(f"  Duration: {result.duration_ms}ms")
            else:
                error("Email send failed!")
                if result.error:
                    click.secho(f"  Error: {result.error}", fg="red")
                if result.error_code:
                    click.echo(f"  Error Code: {result.error_code}")
                sys.exit(1)

        except Exception as e:
            error(f"Failed to send email: {e}")
            sys.exit(1)
