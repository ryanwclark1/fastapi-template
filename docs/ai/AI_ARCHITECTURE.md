# AI Services Architecture

## Overview

This document describes the AI services architecture implemented in the fastapi-template. The system provides flexible, tenant-aware AI capabilities including transcription, PII redaction, summarization, sentiment analysis, and coaching analysis.

## Architecture Principles

1. **Hybrid Processing**: API handles orchestration, Taskiq workers handle heavy AI processing
2. **Tenant Isolation**: Complete separation of configs, costs, and data per tenant
3. **Provider Flexibility**: Easy switching between AI providers (OpenAI, Deepgram, etc.)
4. **Cost Tracking**: Full visibility into AI usage and costs
5. **Feature Flags**: Tenant-level control over AI capabilities

## Components

### 1. Settings (`core/settings/ai.py`)

Comprehensive AI configuration with environment variables:
- Provider defaults (LLM, transcription)
- API keys (service-level defaults)
- Cost tracking settings
- Feature toggles
- Processing limits

```python
from example_service.core.settings import get_ai_settings

settings = get_ai_settings()
# Access: settings.default_llm_provider, settings.openai_api_key, etc.
```

### 2. Database Models (`features/ai/models.py`)

Four core tables for AI services:

#### TenantAIConfig
- Stores tenant-specific provider configurations
- **Encrypted API keys** for security
- Per-provider, per-type configuration
- Supports overriding service defaults

#### AIJob
- Tracks async AI processing jobs
- Progress tracking (0-100%)
- Input/output data storage (JSONB)
- Error handling and retry support

#### AIUsageLog
- Detailed cost and usage metrics
- Tracks tokens, duration, costs per operation
- Provider and model attribution
- Success/failure tracking

#### TenantAIFeature
- Per-tenant feature flags
- AI capability toggles
- Cost controls (monthly budgets)
- Processing limits

### 3. Provider Abstraction (`infra/ai/providers/`)

#### Base Interfaces (`base.py`)
Three main protocols:
- **TranscriptionProvider**: Speech-to-text operations
- **LLMProvider**: Text generation and structured output
- **PIIRedactionProvider**: PII detection and masking

#### Concrete Implementations

**OpenAI Provider** (`openai_provider.py`):
- OpenAITranscriptionProvider: Whisper API
- OpenAILLMProvider: GPT-4, GPT-4o-mini, etc.
- Supports structured output via instructor
- Dual-channel transcription support

**Deepgram Provider** (`deepgram_provider.py`):
- High-accuracy transcription
- **Speaker diarization** support
- Word-level timestamps
- 100+ language support

**Accent Redaction** (`accent_redaction_client.py`):
- HTTP client for accent-redaction service
- Multiple entity types (PERSON, EMAIL, SSN, etc.)
- Configurable redaction methods
- Segment-level redaction for transcripts

### 4. Configuration Management (`infra/ai/config_manager.py`)

**AIConfigManager** provides cascading configuration:
1. Check tenant-specific config (database)
2. Fall back to service defaults (settings)
3. Decrypt API keys
4. Validate feature flags

```python
from example_service.infra.ai.config_manager import AIConfigManager

async with session_factory() as session:
    config_mgr = AIConfigManager(session)

    # Get transcription config for tenant
    config = await config_mgr.get_transcription_config(
        tenant_id="tenant-123",
        provider_override="deepgram"  # Optional
    )
```

### 5. Provider Factory (`infra/ai/providers/factory.py`)

**ProviderFactory** creates configured provider instances:

```python
from example_service.infra.ai.providers.factory import ProviderFactory

async with session_factory() as session:
    factory = ProviderFactory(session)

    # Create transcription provider
    provider = await factory.create_transcription_provider(
        tenant_id="tenant-123",
        provider_name="deepgram"  # Optional override
    )

    # Use provider
    result = await provider.transcribe(audio_data, speaker_diarization=True)
```

## Configuration Hierarchy

The system supports multi-level configuration:

```
Tenant-Specific Config (database)
        ↓ (if not found)
Service Defaults (settings)
        ↓ (if not found)
Provider Defaults (hardcoded)
```

### Example: Transcription Provider Selection

1. Check `TenantAIConfig` for tenant's transcription provider
2. If not found, use `settings.default_transcription_provider`
3. If not configured, error

### Example: API Key Resolution

1. Check `TenantAIConfig.encrypted_api_key` (decrypted)
2. If not found, use `settings.openai_api_key` (service default)
3. If not found, error

## Usage Patterns

### 1. Basic Transcription

```python
from example_service.infra.ai.providers.factory import ProviderFactory

async def transcribe_audio(session, tenant_id: str, audio: bytes):
    factory = ProviderFactory(session)
    provider = await factory.create_transcription_provider(tenant_id)

    result = await provider.transcribe(
        audio=audio,
        language="en",
        speaker_diarization=True
    )

    return result.text, result.segments
```

### 2. Dual-Channel Transcription

```python
async def transcribe_call(session, tenant_id: str, agent_audio: bytes, customer_audio: bytes):
    factory = ProviderFactory(session)
    provider = await factory.create_transcription_provider(tenant_id)

    result = await provider.transcribe_dual_channel(
        channel1=agent_audio,  # Agent
        channel2=customer_audio,  # Customer
        language="en"
    )

    # Result has speaker-attributed segments
    for segment in result.segments:
        print(f"{segment.speaker}: {segment.text}")
```

### 3. PII Redaction

```python
async def redact_transcript(session, tenant_id: str, text: str):
    factory = ProviderFactory(session)
    provider = await factory.create_pii_provider(tenant_id)

    result = await provider.redact_pii(
        text=text,
        entity_types=["PERSON", "EMAIL_ADDRESS", "PHONE_NUMBER"],
        redaction_method="mask"
    )

    return result.redacted_text, result.entities
```

### 4. LLM Generation with Structured Output

```python
from pydantic import BaseModel

class Summary(BaseModel):
    overview: str
    key_points: list[str]
    action_items: list[str]

async def summarize(session, tenant_id: str, transcript: str):
    factory = ProviderFactory(session)
    provider = await factory.create_llm_provider(tenant_id)

    messages = [
        {"role": "system", "content": "You are a call summarization expert."},
        {"role": "user", "content": f"Summarize this call: {transcript}"}
    ]

    # Get structured output
    summary = await provider.generate_structured(
        messages=messages,
        response_model=Summary
    )

    return summary
```

## Database Schema

### Table: `tenants`
```sql
CREATE TABLE tenants (
    id VARCHAR(255) PRIMARY KEY,
    name VARCHAR(255) NOT NULL,
    is_active BOOLEAN DEFAULT true,
    created_at TIMESTAMP DEFAULT now(),
    updated_at TIMESTAMP DEFAULT now()
);
```

### Table: `tenant_ai_configs`
```sql
CREATE TABLE tenant_ai_configs (
    id UUID PRIMARY KEY,
    tenant_id VARCHAR(255) REFERENCES tenants(id) ON DELETE CASCADE,
    provider_type aiprovidertype NOT NULL,  -- LLM | TRANSCRIPTION | etc.
    provider_name VARCHAR(100) NOT NULL,     -- openai | deepgram | etc.
    model_name VARCHAR(255),
    encrypted_api_key TEXT,                  -- Encrypted with app key
    config_json JSONB,
    is_active BOOLEAN DEFAULT true,
    created_at TIMESTAMP DEFAULT now(),
    updated_at TIMESTAMP DEFAULT now(),
    created_by_id UUID REFERENCES users(id)
);

CREATE INDEX ON tenant_ai_configs(tenant_id, provider_type, provider_name);
```

### Table: `ai_jobs`
```sql
CREATE TABLE ai_jobs (
    id UUID PRIMARY KEY,
    tenant_id VARCHAR(255) REFERENCES tenants(id) ON DELETE CASCADE,
    job_type aijobtype NOT NULL,             -- TRANSCRIPTION | SUMMARY | etc.
    status aijobstatus DEFAULT 'PENDING',    -- PENDING | PROCESSING | COMPLETED | FAILED
    input_data JSONB NOT NULL,
    result_data JSONB,
    error_message TEXT,
    progress_percentage INT DEFAULT 0,
    current_step VARCHAR(255),
    started_at TIMESTAMP,
    completed_at TIMESTAMP,
    duration_seconds FLOAT,
    created_at TIMESTAMP DEFAULT now(),
    updated_at TIMESTAMP DEFAULT now(),
    created_by_id UUID REFERENCES users(id)
);

CREATE INDEX ON ai_jobs(tenant_id, status);
CREATE INDEX ON ai_jobs(status, created_at);
```

### Table: `ai_usage_logs`
```sql
CREATE TABLE ai_usage_logs (
    id UUID PRIMARY KEY,
    tenant_id VARCHAR(255) REFERENCES tenants(id) ON DELETE CASCADE,
    job_id UUID REFERENCES ai_jobs(id) ON DELETE SET NULL,
    provider_name VARCHAR(100) NOT NULL,
    model_name VARCHAR(255) NOT NULL,
    operation_type VARCHAR(100) NOT NULL,
    input_tokens INT,
    output_tokens INT,
    audio_seconds FLOAT,
    characters_processed INT,
    cost_usd FLOAT NOT NULL,
    cost_calculation_method VARCHAR(50),
    duration_seconds FLOAT NOT NULL,
    success BOOLEAN DEFAULT true,
    error_message TEXT,
    metadata_json JSONB,
    created_at TIMESTAMP DEFAULT now()
);

CREATE INDEX ON ai_usage_logs(tenant_id, created_at);
CREATE INDEX ON ai_usage_logs(job_id);
```

### Table: `tenant_ai_features`
```sql
CREATE TABLE tenant_ai_features (
    tenant_id VARCHAR(255) PRIMARY KEY REFERENCES tenants(id) ON DELETE CASCADE,
    transcription_enabled BOOLEAN DEFAULT true,
    pii_redaction_enabled BOOLEAN DEFAULT true,
    summary_enabled BOOLEAN DEFAULT true,
    sentiment_enabled BOOLEAN DEFAULT false,
    coaching_enabled BOOLEAN DEFAULT false,
    pii_entity_types JSONB,
    pii_confidence_threshold FLOAT,
    max_audio_duration_seconds INT,
    max_concurrent_jobs INT,
    monthly_budget_usd FLOAT,
    enable_cost_alerts BOOLEAN DEFAULT true,
    created_at TIMESTAMP DEFAULT now(),
    updated_at TIMESTAMP DEFAULT now()
);
```

## Security

### API Key Encryption

Tenant API keys are encrypted at rest using `EncryptedString` type:

```python
from example_service.infra.ai.config_manager import create_tenant_ai_config

# Create config with encrypted API key
config = await create_tenant_ai_config(
    session=session,
    tenant_id="tenant-123",
    provider_type=AIProviderType.LLM,
    provider_name="openai",
    api_key="sk-proj-...",  # Automatically encrypted
    model_name="gpt-4o-mini"
)
```

Decryption happens automatically in `AIConfigManager`:
```python
config = await config_mgr.get_llm_config(tenant_id)
# config.api_key is decrypted automatically
```

## Cost Tracking

Every AI operation logs usage metrics:

```python
from example_service.features.ai.models import AIUsageLog

usage = AIUsageLog(
    tenant_id="tenant-123",
    job_id=job.id,
    provider_name="openai",
    model_name="gpt-4o-mini",
    operation_type="summarization",
    input_tokens=2000,
    output_tokens=500,
    cost_usd=0.003,  # Calculated from token usage
    duration_seconds=3.5,
    success=True
)
```

Query tenant costs:
```python
# Total spend this month
stmt = select(func.sum(AIUsageLog.cost_usd)).where(
    AIUsageLog.tenant_id == tenant_id,
    AIUsageLog.created_at >= start_of_month
)
total_cost = await session.scalar(stmt)
```

## Future Enhancements

- [ ] Pydantic-AI agents for orchestration
- [ ] Taskiq background tasks
- [ ] REST API endpoints
- [ ] Cost alerting system
- [ ] Provider performance metrics
- [ ] Caching layer for repeated requests
- [ ] Streaming support for real-time transcription
- [ ] Custom vocabulary support
- [ ] Multi-language support improvements

## Migration Path

For existing systems:

1. **Run migration**: `alembic upgrade head`
2. **Configure settings**: Set `AI_*` environment variables
3. **Create tenant configs**: Use `create_tenant_ai_config()` helper
4. **Update code**: Replace direct API calls with ProviderFactory
5. **Test thoroughly**: Verify provider switching works
6. **Monitor costs**: Check `ai_usage_logs` table

## References

- [OpenAI API Documentation](https://platform.openai.com/docs)
- [Deepgram API Documentation](https://developers.deepgram.com)
- [Pydantic AI Documentation](https://ai.pydantic.dev)
- [Taskiq Documentation](https://taskiq-python.github.io)
