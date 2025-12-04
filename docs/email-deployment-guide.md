# Email Capabilities Enhancement - Deployment Guide

This guide provides step-by-step instructions for deploying the enhanced email system to production.

## 📋 Pre-Deployment Checklist

### ✅ Completed
- [x] All 4 phases implemented (Foundation, Providers, Observability, API)
- [x] 19 new files created, 5 files modified
- [x] Database migrations created
- [x] API routes registered with FastAPI
- [x] Prometheus metrics implemented
- [x] Rate limiting integrated
- [x] Usage/audit logging implemented

### ⏳ Required Before Production

## 1️⃣ Environment Configuration

### Required Environment Variables

Create or update your `.env` file:

```bash
# Email Encryption (REQUIRED for secure credential storage)
EMAIL_ENCRYPTION_KEY=your-32-byte-base64-encoded-fernet-key

# Email System Settings (already exist in your settings)
EMAIL_ENABLED=true
EMAIL_BACKEND=smtp  # or console for dev
EMAIL_RATE_LIMIT_PER_MINUTE=60

# SMTP Default (if using SMTP as system default)
EMAIL_SMTP_HOST=smtp.gmail.com
EMAIL_SMTP_PORT=587
EMAIL_SMTP_USERNAME=your-email@gmail.com
EMAIL_SMTP_PASSWORD=your-app-password
EMAIL_SMTP_USE_TLS=true
EMAIL_FROM_EMAIL=noreply@yourapp.com
EMAIL_FROM_NAME="Your App Name"

# Redis (required for rate limiting - already configured)
REDIS_URL=redis://localhost:6379/0

# Optional: Provider API keys (if using cloud providers)
AWS_ACCESS_KEY_ID=your-aws-key
AWS_SECRET_ACCESS_KEY=your-aws-secret
AWS_REGION=us-east-1

SENDGRID_API_KEY=your-sendgrid-key
MAILGUN_API_KEY=your-mailgun-key
```

### Generate Encryption Key

```bash
# Generate a Fernet encryption key
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

**⚠️ CRITICAL**: Store this key securely! Loss of this key means loss of access to encrypted credentials.

## 2️⃣ Database Migration

### Run Migrations

```bash
# In development
uv run alembic upgrade head

# In production (with backup first!)
# 1. Backup database
pg_dump your_database > backup_$(date +%Y%m%d_%H%M%S).sql

# 2. Run migrations
uv run alembic upgrade head

# 3. Verify tables created
psql -d your_database -c "\dt email_*"
```

### Expected Tables

After migration, you should see:
- `email_configs` - Tenant email configurations
- `email_usage_logs` - Usage tracking for billing
- `email_audit_logs` - Privacy-compliant audit trail

## 3️⃣ Application Startup

### Initialize Enhanced Email Service

The `EnhancedEmailService` supports **gradual feature rollout**:

#### Minimal (Phase 1 + 2 only)
```python
from example_service.infra.email import initialize_enhanced_email_service

# Basic multi-tenant with providers (no rate limiting/logging)
service = initialize_enhanced_email_service(
    session_factory=get_async_session,
    settings=get_email_settings(),
    # rate_limiter=None,  # Phase 3 features disabled
    # session_factory=None,
)
```

#### Full Production (All Phases)
```python
from example_service.infra.email import initialize_enhanced_email_service
from example_service.infra.ratelimit import RateLimiter
from example_service.infra.cache import get_cache

async def initialize_email():
    # Get Redis for rate limiting
    async with get_cache() as cache:
        rate_limiter = RateLimiter(cache.get_client())

    # Initialize with all Phase 3 features
    service = initialize_enhanced_email_service(
        session_factory=get_async_session,
        settings=get_email_settings(),
        rate_limiter=rate_limiter,  # ✅ Enable rate limiting
        session_factory=get_async_session,  # ✅ Enable usage/audit logging
    )

    return service
```

### Update Lifespan (Optional)

If you want to initialize at startup:

```python
# example_service/app/lifespan.py

from example_service.infra.email import initialize_enhanced_email_service

@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Application lifespan context manager."""

    # ... existing startup code ...

    # Initialize enhanced email service (Phase 4)
    async with get_cache() as cache:
        rate_limiter = RateLimiter(cache.get_client())

    email_service = initialize_enhanced_email_service(
        session_factory=get_async_session,
        settings=get_email_settings(),
        rate_limiter=rate_limiter,
    )
    logger.info("Enhanced email service initialized")

    yield

    # Cleanup
    logger.info("Shutting down email service")
```

## 4️⃣ Testing in Staging

### Test Checklist

#### 1. Basic Functionality
```bash
# Health check
curl http://localhost:8000/api/v1/health

# List available providers
curl http://localhost:8000/api/v1/email/providers | jq
```

#### 2. Create Test Configuration
```bash
curl -X POST http://localhost:8000/api/v1/email/configs/test-tenant-001 \
  -H "Content-Type: application/json" \
  -d '{
    "provider_type": "smtp",
    "smtp_host": "smtp.gmail.com",
    "smtp_port": 587,
    "smtp_username": "test@example.com",
    "smtp_password": "app-password",
    "smtp_use_tls": true,
    "from_email": "noreply@test.com",
    "from_name": "Test App",
    "rate_limit_per_minute": 10
  }'
```

#### 3. Test Email Delivery
```bash
curl -X POST http://localhost:8000/api/v1/email/configs/test-tenant-001/test \
  -H "Content-Type: application/json" \
  -d '{
    "to": "your-email@example.com",
    "use_tenant_config": true
  }'
```

#### 4. Verify Metrics
```bash
# Check Prometheus metrics
curl http://localhost:8000/metrics | grep email_

# Expected metrics:
# email_delivery_total
# email_delivery_duration_seconds
# email_rate_limit_hits_total
# email_cost_usd_total
```

#### 5. Check Usage Logs
```bash
# Query usage statistics
curl http://localhost:8000/api/v1/email/configs/test-tenant-001/usage | jq

# Verify database logs
psql -d your_database -c "SELECT * FROM email_usage_logs ORDER BY created_at DESC LIMIT 5;"
```

## 5️⃣ Monitoring Setup

### Prometheus Queries

Add these to your monitoring dashboard:

```promql
# Success rate (last 24h)
sum(rate(email_delivery_total{status="success"}[24h]))
/ sum(rate(email_delivery_total[24h])) * 100

# P99 latency
histogram_quantile(0.99,
  rate(email_delivery_duration_seconds_bucket[5m]))

# Rate limit hit rate
sum(rate(email_rate_limit_hits_total[1h])) by (tenant_id)

# Cost tracking
sum(increase(email_cost_usd_total[1d])) by (provider)

# Provider health
email_provider_health

# Provider errors by category
sum(rate(email_provider_errors_total[5m])) by (provider, error_category)
```

### Alerting Rules

```yaml
# prometheus/alerts.yml
groups:
  - name: email_alerts
    interval: 30s
    rules:
      # Success rate below 95%
      - alert: EmailSuccessRateLow
        expr: |
          (sum(rate(email_delivery_total{status="success"}[5m]))
          / sum(rate(email_delivery_total[5m]))) < 0.95
        for: 10m
        annotations:
          summary: "Email success rate below 95%"
          description: "Only {{ $value | humanizePercentage }} emails delivering successfully"

      # Provider unhealthy
      - alert: EmailProviderUnhealthy
        expr: email_provider_health == 0
        for: 5m
        annotations:
          summary: "Email provider {{ $labels.provider }} unhealthy for {{ $labels.tenant_id }}"

      # High rate limiting
      - alert: EmailRateLimitingHigh
        expr: rate(email_rate_limit_hits_total[5m]) > 0.1
        for: 15m
        annotations:
          summary: "Tenant {{ $labels.tenant_id }} hitting rate limits frequently"

      # P99 latency above 5s
      - alert: EmailLatencyHigh
        expr: |
          histogram_quantile(0.99,
            rate(email_delivery_duration_seconds_bucket[5m])) > 5
        for: 10m
        annotations:
          summary: "Email delivery P99 latency above 5s"
```

## 6️⃣ Documentation for Users

### API Documentation

Your OpenAPI docs are automatically available at:
- **Swagger UI**: `http://your-domain.com/docs`
- **ReDoc**: `http://your-domain.com/redoc`

Navigate to the **email-configuration** tag to see all endpoints.

### Example Workflow for Tenants

1. **Get available providers**
   ```bash
   GET /api/v1/email/providers
   ```

2. **Create configuration**
   ```bash
   POST /api/v1/email/configs/{tenant_id}
   ```

3. **Test configuration**
   ```bash
   POST /api/v1/email/configs/{tenant_id}/test
   ```

4. **Monitor usage**
   ```bash
   GET /api/v1/email/configs/{tenant_id}/usage?start_date=2025-11-01
   ```

5. **Check health**
   ```bash
   GET /api/v1/email/configs/{tenant_id}/health
   ```

## 7️⃣ Security Considerations

### Encryption Key Management

**Development**:
- Store in `.env` file (not committed to git)

**Production**:
- Use secrets management (AWS Secrets Manager, HashiCorp Vault, etc.)
- Rotate keys periodically (encryption_version field supports this)

### API Access Control

**Recommended**: Add authentication middleware

```python
# Protect email config endpoints
from fastapi import Depends, HTTPException, status

async def verify_tenant_access(tenant_id: str, user: User = Depends(get_current_user)):
    """Verify user has access to tenant's email config."""
    if user.tenant_id != tenant_id and not user.is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to access this tenant's configuration"
        )
    return tenant_id
```

## 8️⃣ Cost Optimization

### Monitor Provider Costs

```bash
# Get cost breakdown
curl http://localhost:8000/api/v1/admin/email/usage?days=30 | jq '.cost_by_provider'
```

### Optimize Provider Selection

| Provider | Cost per 1000 | Use Case |
|----------|---------------|----------|
| AWS SES | $0.10 | High volume, own infrastructure |
| SendGrid | $0.15 | Easy setup, good deliverability |
| Mailgun | $0.80 | EU data residency, advanced features |
| SMTP | $0 | Own mail server, unlimited |

### Set Quotas

```bash
# Update tenant quota
curl -X PUT http://localhost:8000/api/v1/email/configs/tenant-123 \
  -H "Content-Type: application/json" \
  -d '{
    "daily_quota": 1000,
    "rate_limit_per_minute": 20
  }'
```

## 9️⃣ Troubleshooting

### Common Issues

#### Credentials not encrypted
**Symptom**: Plaintext credentials in database

**Fix**: Ensure `EMAIL_ENCRYPTION_KEY` is set before running migrations

```bash
# Check encryption
psql -d your_database -c "SELECT tenant_id, smtp_password FROM email_configs LIMIT 1;"
# Should show encrypted blob, not plaintext
```

#### Rate limiting not working
**Symptom**: No rate limits enforced

**Check**:
1. Redis is running: `redis-cli ping`
2. Rate limiter passed to service initialization
3. `rate_limit_per_minute` > 0 in config

#### Metrics not appearing
**Symptom**: No email metrics in Prometheus

**Check**:
1. `/metrics` endpoint accessible: `curl http://localhost:8000/metrics | grep email_`
2. Prometheus scraping your app
3. Emails being sent (metrics only appear after first use)

#### "Provider not available" error
**Symptom**: SESProvider not available

**Fix**: Install optional dependency
```bash
uv add aioboto3  # For AWS SES support
```

## 🔟 Gradual Rollout Strategy

### Phase 1: Pilot (Week 1)
1. Deploy to staging
2. Test with 1-2 pilot tenants
3. Monitor metrics closely
4. Gather feedback

### Phase 2: Limited Release (Week 2-3)
1. Roll out to 10% of tenants
2. Monitor success rate, latency, costs
3. Fine-tune rate limits based on actual usage
4. Adjust quotas if needed

### Phase 3: General Availability (Week 4+)
1. Enable for all tenants
2. Announce in changelog/docs
3. Provide migration guide for tenants with custom email setups
4. Monitor system-wide metrics

## 📊 Success Metrics

Track these KPIs:

- **Adoption**: % of tenants with custom configs (target: 50% in 3 months)
- **Reliability**: Email success rate (target: >99.5%)
- **Performance**: P99 delivery latency (target: <2s)
- **Cost**: Average cost per email (target: <$0.0002)
- **Efficiency**: Cache hit rate (target: >90%)

## 🆘 Support

### Logs
```bash
# View email-related logs
tail -f logs/app.log | grep "email\|Enhanced"

# Check for errors
grep "ERROR" logs/app.log | grep email
```

### Database Queries
```sql
-- Active configurations
SELECT tenant_id, provider_type, is_active
FROM email_configs
WHERE is_active = true;

-- Usage by tenant (last 7 days)
SELECT
  tenant_id,
  COUNT(*) as emails_sent,
  SUM(cost_usd) as total_cost,
  AVG(duration_ms) as avg_duration_ms
FROM email_usage_logs
WHERE created_at > NOW() - INTERVAL '7 days'
GROUP BY tenant_id
ORDER BY emails_sent DESC;

-- Error analysis
SELECT
  error_category,
  COUNT(*) as error_count
FROM email_audit_logs
WHERE status = 'failed'
  AND created_at > NOW() - INTERVAL '24 hours'
GROUP BY error_category;
```

## 🎓 Training Resources

### For Developers
- [GraphQL Features Documentation](./development/graphql-features.md)
- [Type Stubs Explanation](./development/mypy-type-stubs-explanation.md)
- [AI Services Documentation](./ai/)

### For Admins
- Monitor: `/api/v1/admin/email/health`
- Usage: `/api/v1/admin/email/usage`
- Distribution: `/api/v1/admin/email/providers/distribution`

### For End Users
- API Docs: `/docs` (Swagger UI)
- Provider info: `GET /api/v1/email/providers`
- Test your config: `POST /api/v1/email/configs/{tenant_id}/test`

---

## ✅ Final Deployment Checklist

Before going to production:

- [ ] Environment variables configured
- [ ] Encryption key generated and secured
- [ ] Database migrations run successfully
- [ ] Test emails sent and received
- [ ] Prometheus metrics visible
- [ ] Rate limiting tested
- [ ] Usage logs appearing in database
- [ ] API documentation reviewed
- [ ] Monitoring alerts configured
- [ ] Backup and rollback plan ready
- [ ] Team trained on new features

**Ready to deploy? 🚀**

For questions or issues, check the troubleshooting section or create an issue in the project repository.
