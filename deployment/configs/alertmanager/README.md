# AlertManager Configuration

This directory contains the configuration for Prometheus AlertManager, which handles alert routing, grouping, deduplication, and notifications.

## Overview

AlertManager receives alerts from Prometheus and routes them to configured notification channels (Slack, email, PagerDuty, webhooks, etc.). It provides:

- **Alert Grouping**: Combines related alerts to reduce notification noise
- **Deduplication**: Prevents duplicate notifications for the same alert
- **Inhibition**: Suppresses certain alerts based on other active alerts
- **Routing**: Sends alerts to different receivers based on labels
- **Silencing**: Temporarily mute alerts during maintenance windows

## Directory Structure

```
deployment/configs/alertmanager/
├── alertmanager.yml    # Main AlertManager configuration
└── README.md           # This file
```

## Configuration Overview

### Current Setup

The current configuration is set up for **UI-only mode** - alerts are visible in the AlertManager web interface but no external notifications are sent. This provides a foundation that's ready to be enhanced with notification channels.

### Alert Flow

```
Prometheus → Evaluates alert rules (alerts.yml)
    ↓
    Fires alerts when conditions are met
    ↓
AlertManager → Receives alerts from Prometheus
    ↓
    Groups alerts by: alertname, severity, component
    ↓
    Routes to receivers based on severity:
    - critical → 'critical' receiver (4h repeat)
    - warning → 'warning' receiver (12h repeat)
    ↓
    Currently: Visible in AlertManager UI only
    Future: Send to Slack, Email, PagerDuty, etc.
```

## Access

- **AlertManager UI**: http://localhost:9093
- **Prometheus UI**: http://localhost:9091 (see alert status)
- **Grafana**: http://localhost:3003 (can query alert metrics)

## Configured Receivers

### Default Receiver
- Catches all alerts not matched by specific routes
- Currently: UI only
- Future: General notification channel

### Critical Receiver
- Handles `severity: critical` alerts
- Repeat interval: 4 hours
- Group wait: 5 seconds (faster response)
- Future: PagerDuty, on-call rotations

### Warning Receiver
- Handles `severity: warning` alerts
- Repeat interval: 12 hours
- Future: Slack, email

## Alert Grouping

Alerts are grouped by:
- `alertname`: Alert rule name
- `severity`: critical, warning
- `component`: application, database, cache, etc.

**Example**: If 5 endpoints have `HighErrorRate` warnings, they'll be grouped into a single notification instead of 5 separate ones.

## Inhibition Rules

The following inhibition rules prevent alert spam:

1. **Critical suppresses Warning**: If a critical alert fires, related warnings are suppressed
   ```yaml
   Example: CriticalErrorRate firing → HighErrorRate suppressed
   ```

2. **Specific suppresses General**: More specific alerts suppress general ones
   ```yaml
   Example: VeryHighResponseTime firing → HighResponseTime suppressed
   ```

## Adding Notification Channels

### Slack Integration

1. Create a Slack app with Incoming Webhooks
2. Get the webhook URL
3. Update `alertmanager.yml`:

```yaml
global:
  slack_api_url: 'https://hooks.slack.com/services/YOUR/WEBHOOK/URL'

receivers:
  - name: 'warning'
    slack_configs:
      - channel: '#alerts'
        title: '{{ .GroupLabels.alertname }}'
        text: '{{ .CommonAnnotations.description }}'
        send_resolved: true
```

4. Restart AlertManager: `docker compose restart alertmanager`

### Email Integration

1. Get SMTP credentials (Gmail App Password recommended)
2. Update `alertmanager.yml`:

```yaml
global:
  smtp_smarthost: 'smtp.gmail.com:587'
  smtp_from: 'alertmanager@example.com'
  smtp_auth_username: 'your-email@example.com'
  smtp_auth_password: 'your-app-password'
  smtp_require_tls: true

receivers:
  - name: 'critical'
    email_configs:
      - to: 'oncall@example.com'
        subject: '[{{ .Status | toUpper }}] {{ .GroupLabels.alertname }}'
```

3. Restart AlertManager: `docker compose restart alertmanager`

### PagerDuty Integration

1. Create a service in PagerDuty
2. Get the Integration Key
3. Update `alertmanager.yml`:

```yaml
receivers:
  - name: 'critical'
    pagerduty_configs:
      - service_key: 'YOUR_PAGERDUTY_SERVICE_KEY'
        description: '{{ .GroupLabels.alertname }}: {{ .CommonAnnotations.summary }}'
```

4. Restart AlertManager: `docker compose restart alertmanager`

### Webhook Integration

For custom integrations (MS Teams, Discord, custom services):

```yaml
receivers:
  - name: 'webhook'
    webhook_configs:
      - url: 'http://your-service:5000/alerts'
        send_resolved: true
        http_config:
          basic_auth:
            username: 'alertmanager'
            password: 'secret'
```

## Testing Alerts

### View Active Alerts

```bash
# Check Prometheus alerts status
curl http://localhost:9091/api/v1/alerts

# Check AlertManager alerts
curl http://localhost:9093/api/v2/alerts
```

### Send Test Alert

```bash
# Using amtool (AlertManager CLI)
docker exec -it alertmanager amtool alert add test \
  alertname=TestAlert \
  severity=warning \
  component=test \
  summary="This is a test alert"

# View the test alert
docker exec -it alertmanager amtool alert query
```

### Validate Configuration

```bash
# Check AlertManager configuration
docker exec -it alertmanager amtool check-config /etc/alertmanager/alertmanager.yml

# Check Prometheus configuration
docker exec -it prometheus promtool check config /etc/prometheus/prometheus.yml

# Check alert rules
docker exec -it prometheus promtool check rules /etc/prometheus/alerts.yml
```

## Silencing Alerts

### Create Silence (Maintenance Window)

```bash
# Silence alerts for 2 hours
docker exec -it alertmanager amtool silence add \
  alertname=HighErrorRate \
  --duration=2h \
  --author="DevOps Team" \
  --comment="Maintenance window"

# Silence by component
docker exec -it alertmanager amtool silence add \
  component=database \
  --duration=1h \
  --author="DBA Team" \
  --comment="Database migration"
```

### Via Web UI

1. Go to http://localhost:9093
2. Click on an alert
3. Click "Silence" button
4. Set duration and add comment

## Advanced Routing

### Route by Component

Uncomment and customize in `alertmanager.yml`:

```yaml
routes:
  - match:
      component: database
    receiver: 'database-team'

  - match:
      component: auth
    receiver: 'security-team'
```

### Route by Time of Day

```yaml
routes:
  - match:
      severity: warning
    receiver: 'daytime'
    active_time_intervals:
      - business_hours

time_intervals:
  - name: business_hours
    time_intervals:
      - times:
          - start_time: '09:00'
            end_time: '17:00'
        weekdays: ['monday:friday']
```

## Monitoring AlertManager

### Metrics

AlertManager exposes metrics at http://localhost:9093/metrics:

- `alertmanager_alerts`: Number of active alerts
- `alertmanager_notifications_total`: Total notifications sent
- `alertmanager_notifications_failed_total`: Failed notifications
- `alertmanager_silences`: Active silences

### Health Check

```bash
# Check AlertManager health
curl http://localhost:9093/-/healthy

# Check readiness
curl http://localhost:9093/-/ready
```

## Troubleshooting

### Alerts Not Appearing

1. **Check Prometheus is sending alerts**:
   ```bash
   docker compose logs prometheus | grep alertmanager
   ```

2. **Check AlertManager is receiving**:
   ```bash
   docker compose logs alertmanager
   ```

3. **Verify connectivity**:
   ```bash
   docker compose exec prometheus wget -O- http://alertmanager:9093/-/healthy
   ```

### Notifications Not Sending

1. **Check receiver configuration**:
   ```bash
   docker exec -it alertmanager amtool check-config
   ```

2. **Test notification manually**:
   - Send test alert (see Testing section)
   - Check logs for errors: `docker compose logs alertmanager`

3. **Common issues**:
   - Slack: Verify webhook URL is correct
   - Email: Check SMTP credentials and TLS settings
   - Webhook: Ensure target service is accessible from container

### Configuration Errors

```bash
# Validate before restarting
docker run --rm -v $(pwd)/alertmanager.yml:/tmp/config.yml \
  prom/alertmanager:latest \
  amtool check-config /tmp/config.yml
```

## Best Practices

1. **Start Simple**: Begin with UI-only, add channels incrementally
2. **Test Thoroughly**: Use test alerts before relying on notifications
3. **Group Wisely**: Balance between too much grouping (miss alerts) and too little (alert fatigue)
4. **Set Repeat Intervals**: Critical: 4h, Warning: 12h (adjust based on urgency)
5. **Use Inhibition**: Prevent cascading alerts from overwhelming receivers
6. **Document Receivers**: Clearly document which team/channel receives which alerts
7. **Monitor AlertManager**: Set up alerts for AlertManager itself (meta-alerting)
8. **Backup Configuration**: Keep alertmanager.yml in version control
9. **Silence During Maintenance**: Use silences instead of disabling alerts
10. **Review Regularly**: Audit alert rules and routing quarterly

## Security Considerations

1. **Webhook Authentication**: Always use basic auth or tokens for webhooks
2. **SMTP Credentials**: Use app passwords, not actual passwords
3. **API Access**: Consider restricting AlertManager UI access (reverse proxy + auth)
4. **Secret Management**: Use Docker secrets or environment variables for sensitive data
5. **TLS**: Enable TLS for production deployments

## Resources

- [Official AlertManager Documentation](https://prometheus.io/docs/alerting/latest/alertmanager/)
- [Configuration Reference](https://prometheus.io/docs/alerting/latest/configuration/)
- [Notification Template Reference](https://prometheus.io/docs/alerting/latest/notifications/)
- [AlertManager Best Practices](https://prometheus.io/docs/practices/alerting/)
- [amtool CLI Reference](https://github.com/prometheus/alertmanager#amtool)
