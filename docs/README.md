# Documentation Guide

This directory contains the primary references for working on, deploying, and operating the FastAPI template. Documents are grouped by purpose to make it easier to find the right level of detail.

## Architecture & Design

| Topic | Description |
| --- | --- |
| [`architecture/overview.md`](architecture/overview.md) | High-level service architecture, layering strategy, and request flow. |
| [`MIDDLEWARE_ARCHITECTURE.md`](MIDDLEWARE_ARCHITECTURE.md) | Deep dive into the middleware stack, ordering, and performance considerations. |
| [`CORRELATION_ID_USAGE.md`](CORRELATION_ID_USAGE.md) | Guidance for propagating correlation IDs through internal and external calls. |
| [`CLI_ENHANCEMENTS.md`](CLI_ENHANCEMENTS.md) | Code-generation and workflow commands available via the project CLI. |

## Development Workflow

| Topic | Description |
| --- | --- |
| [`development/setup.md`](development/setup.md) | Environment prerequisites, uv installation, and local tooling workflow. |
| [`development/testing.md`](development/testing.md) | Testing matrix, including the Docker-backed integration suite and useful pytest markers. |

## Operations & Security

| Topic | Description |
| --- | --- |
| [`deployment/kubernetes.md`](deployment/kubernetes.md) | Kubernetes deployment guidance, probe configuration, and resource sizing tips. |
| [`DEPLOYMENT_VALIDATION.md`](DEPLOYMENT_VALIDATION.md) | Checklist for validating middleware-heavy deployments in staging/production. |
| [`MONITORING_SETUP.md`](MONITORING_SETUP.md) | Prometheus/Grafana setup instructions plus observability wiring. |
| [`SECURITY_CONFIGURATION.md`](SECURITY_CONFIGURATION.md) | Configuration reference covering rate limiting, PII masking, and security headers. |

## Database Reference

| Topic | Description |
| --- | --- |
| [`database/DATABASE_GUIDE.md`](database/DATABASE_GUIDE.md) | Database architecture, repository usage, and schema guidance. |
| [`database/quick-reference.md`](database/quick-reference.md) | Cheat sheet with common commands and conventions. |
