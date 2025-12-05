# Documentation

Welcome to the FastAPI Template documentation. This guide is organized by topic to help you find exactly what you need.

## Quick Navigation

| Getting Started | Operations | Reference |
|-----------------|------------|-----------|
| [Getting Started Guide](getting-started/getting-started.md) | [Deployment](operations/kubernetes.md) | [CLI Commands](reference/cli-enhancements.md) |
| [Development Setup](development/setup.md) | [Monitoring](operations/monitoring-setup.md) | [Feature Overview](features/accent-ai-features.md) |
| [Testing Guide](testing/testing-guide.md) | [Security Config](operations/security-configuration.md) | [Health Checks](features/health-checks.md) |

---

## Getting Started

New to the project? Start here.

| Document | Description |
|----------|-------------|
| [Getting Started Guide](getting-started/getting-started.md) | Complete onboarding guide with setup instructions |
| [Development Setup](development/setup.md) | Environment prerequisites and local tooling |
| [Testing Guide](testing/testing-guide.md) | Testing strategies and pytest patterns |

---

## Architecture & Design

Understanding how the system is built.

| Document | Description |
|----------|-------------|
| [Architecture Overview](architecture/overview.md) | High-level service architecture and request flow |
| [Final Architecture](architecture/final-architecture.md) | Complete system design with Accent-Auth integration |
| [Multi-Tenancy](architecture/multi-tenancy.md) | Tenant context system, data isolation, and TenantAwareSession |
| [Middleware Architecture](architecture/middleware-architecture.md) | Deep dive into middleware stack and ordering |

---

## Features

Core capabilities of the template.

| Document | Description |
|----------|-------------|
| [Feature Overview](features/accent-ai-features.md) | Comprehensive overview of all features |
| [Health Checks](features/health-checks.md) | Health check system with 8+ providers |
| [Optional Dependencies](features/optional-dependencies.md) | Feature matrix and graceful degradation |

---

## Middleware

Request/response processing pipeline.

| Document | Description |
|----------|-------------|
| [Middleware Guide](middleware/middleware-guide.md) | Configuration reference for all middleware |
| [Debug Middleware](middleware/debug-middleware.md) | Distributed tracing and debug features |
| [Debug Examples](middleware/debug-middleware-production-example.md) | Production deployment examples |
| [I18n Middleware](middleware/i18n-middleware.md) | Multi-language support |
| [I18n Examples](middleware/i18n-examples.md) | Practical locale detection examples |
| [Request Logging](middleware/request-logging-enhancements.md) | Request/response logging features |
| [Security Headers](middleware/security-headers-enhancements.md) | Security headers implementation |
| [N+1 Detection](middleware/n-plus-one-detection.md) | Query optimization detection |
| [Correlation IDs](middleware/correlation-id-usage.md) | Distributed tracing correlation |

---

## Integrations

External service integration guides.

| Document | Description |
|----------|-------------|
| [Accent Auth Integration](integrations/accent-auth-integration.md) | Complete Accent-Auth setup and ACL patterns |
| [Accent Auth Summary](integrations/accent-auth-summary.md) | Quick reference for Accent-Auth |
| [Auth Lifespan Pattern](integrations/accent-auth-lifespan.md) | On-demand authentication design |
| [Auth Client Library](integrations/using-accent-auth-client.md) | Using the accent-auth-client wrapper |

---

## Patterns

Reusable design patterns.

| Document | Description |
|----------|-------------|
| [Circuit Breaker](patterns/circuit-breaker.md) | Resilience patterns with comprehensive examples |

---

## Database

Data layer documentation.

| Document | Description |
|----------|-------------|
| [Database Guide](database/database-guide.md) | Database architecture and repository usage |
| [Quick Reference](database/quick-reference.md) | Common commands and conventions cheat sheet |

---

## Development

Development workflow and tooling.

| Document | Description |
|----------|-------------|
| [Best Practices](development/best-practices.md) | Comprehensive development patterns and guidelines (1,700+ lines) |
| [Setup Guide](development/setup.md) | Environment setup and uv installation |
| [Testing Matrix](development/testing.md) | Docker-backed integration suite and markers |

---

## Testing

Quality assurance documentation.

| Document | Description |
|----------|-------------|
| [Testing Guide](testing/testing-guide.md) | Overall testing strategy |
| [Testing Infrastructure](testing/testing-infrastructure.md) | Test setup and fixtures |

---

## Operations

Deployment and production guidance.

| Document | Description |
|----------|-------------|
| [Kubernetes Deployment](operations/kubernetes.md) | K8s guidance, probes, and resource sizing |
| [Production Checklist](operations/production-deployment-checklist.md) | Comprehensive pre-flight deployment checklist |
| [Deployment Validation](operations/deployment-validation.md) | Staging/production validation checklist |
| [Monitoring Setup](operations/monitoring-setup.md) | Prometheus/Grafana setup |
| [Security Configuration](operations/security-configuration.md) | Rate limiting, PII masking, security headers |

---

## Reference

Quick lookup resources.

| Document | Description |
|----------|-------------|
| [CLI Reference](reference/cli-readme.md) | Complete CLI command documentation |
| [CLI Enhancements](reference/cli-enhancements.md) | Code generation and workflow commands |

---

## Archive

Historical documentation for reference.

| Document | Description |
|----------|-------------|
| [Template Enhancements](archive/template-enhancements-complete.md) | Complete enhancement summary |
| [Test Verification Report](archive/test-verification-report.md) | Test suite verification analysis |
| [Implementation Summary](archive/implementation-summary.md) | Debug middleware implementation details |
| [Improvements Summary](archive/improvements-summary.md) | Historical improvements record |
| [Enhancements Completed](archive/enhancements-completed.md) | 98% feature completion summary |
| [Accent Voice2 Comparison](archive/accent-voice2-comparison.md) | Feature comparison analysis |

---

## Document Statistics

- **Total Documents**: 42
- **Categories**: 12
- **Last Updated**: December 2025
