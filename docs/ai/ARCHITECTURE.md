# AI Pipeline Architecture

This document describes the new capability-based, composable pipeline architecture for AI workflows.

## Overview

The AI pipeline system provides a flexible, production-ready architecture for executing AI workflows with:

- **Composable Pipelines**: Build workflows using a fluent DSL
- **Capability-Based Routing**: Discover providers by capability, not by name
- **Automatic Fallbacks**: Resilient execution with fallback chains
- **Saga Compensation**: Rollback completed steps on failure
- **Real-Time Events**: WebSocket streaming of progress updates
- **Full Observability**: OpenTelemetry tracing + Prometheus metrics
- **Budget Enforcement**: Per-tenant cost tracking and limits

## Architecture Layers

```
┌─────────────────────────────────────────────────────────────────────────┐
│                            API Layer                                     │
│  ┌─────────────────┐  ┌─────────────────┐  ┌───────────────────────┐   │
│  │  REST Endpoints │  │  WebSocket      │  │  GraphQL (optional)   │   │
│  │  /ai/pipelines  │  │  Event Stream   │  │                       │   │
│  └────────┬────────┘  └────────┬────────┘  └───────────────────────┘   │
└───────────┼─────────────────────┼───────────────────────────────────────┘
            │                     │
┌───────────┴─────────────────────┴───────────────────────────────────────┐
│                     Orchestration Layer                                  │
│  ┌──────────────────────────────────────────────────────────────────┐  │
│  │                  InstrumentedOrchestrator                         │  │
│  │  • Pre-execution budget checks                                    │  │
│  │  • Distributed tracing (OpenTelemetry)                           │  │
│  │  • Prometheus metrics recording                                   │  │
│  │  • Post-execution spend tracking                                  │  │
│  └────────────────────────────┬─────────────────────────────────────┘  │
│                               │                                          │
│  ┌────────────────────────────┴─────────────────────────────────────┐  │
│  │                     SagaCoordinator                               │  │
│  │  • Step-by-step execution                                         │  │
│  │  • Event emission for each step                                   │  │
│  │  • Compensation on failure                                        │  │
│  └────────────────────────────┬─────────────────────────────────────┘  │
└───────────────────────────────┼─────────────────────────────────────────┘
                                │
┌───────────────────────────────┴─────────────────────────────────────────┐
│                       Pipeline Layer                                     │
│  ┌────────────────────┐  ┌────────────────────┐  ┌──────────────────┐  │
│  │  PipelineDefinition│  │   PipelineBuilder  │  │  PipelineExecutor│  │
│  │  (declarative spec)│  │   (fluent DSL)     │  │  (execution)     │  │
│  └────────────────────┘  └────────────────────┘  └────────┬─────────┘  │
│                                                            │            │
│  ┌─────────────────────────────────────────────────────────┴──────────┐│
│  │  Predefined Pipelines: transcription, call_analysis, pii_detection ││
│  └────────────────────────────────────────────────────────────────────┘│
└───────────────────────────────┬─────────────────────────────────────────┘
                                │
┌───────────────────────────────┴─────────────────────────────────────────┐
│                      Capability Layer                                    │
│  ┌──────────────────────────────────────────────────────────────────┐  │
│  │                    CapabilityRegistry                             │  │
│  │  • Provider registration with capability metadata                 │  │
│  │  • Capability-to-provider index                                   │  │
│  │  • Fallback chain construction                                    │  │
│  │  • Cost estimation                                                │  │
│  └──────────────────────────────────────────────────────────────────┘  │
│                                                                          │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐  ┌────────────┐  │
│  │ OpenAIAdapter│  │AnthropicAdapt│  │DeepgramAdapter│  │AccentAdapter│  │
│  └──────────────┘  └──────────────┘  └──────────────┘  └────────────┘  │
└─────────────────────────────────────────────────────────────────────────┘
```

## Core Components

### 1. Capability Registry (`capabilities/`)

The registry is the central hub for provider discovery:

```python
from example_service.infra.ai.capabilities import (
    Capability,
    CapabilityRegistry,
    get_registry,
)

# Get providers for a capability
registry = get_registry()
providers = registry.get_providers_for_capability(Capability.TRANSCRIPTION)

# Build fallback chain
chain = registry.build_fallback_chain(
    Capability.TRANSCRIPTION,
    primary_provider="deepgram",
    max_fallbacks=2,
)
```

**Capabilities:**
- `TRANSCRIPTION` - Basic speech-to-text
- `TRANSCRIPTION_DIARIZATION` - Transcription with speaker separation
- `LLM_GENERATION` - Text generation (summarization, coaching)
- `PII_REDACTION` - Personal information masking
- `SENTIMENT_ANALYSIS` - Emotion detection
- `SUMMARIZATION` - Text summarization

### 2. Pipeline Builder (`pipelines/`)

Fluent DSL for building composable pipelines:

```python
from example_service.infra.ai.pipelines.builder import Pipeline
from example_service.infra.ai.capabilities.types import Capability

pipeline = (
    Pipeline("call_analysis")
    .version("1.0.0")
    .description("Full call analysis with insights")
    .timeout(600)

    .step("transcribe")
        .capability(Capability.TRANSCRIPTION_DIARIZATION)
        .prefer_providers("deepgram", "openai")
        .output_as("transcript")
        .with_fallback(max_fallbacks=2)
        .with_retry(max_attempts=3)
        .done()

    .step("redact")
        .capability(Capability.PII_REDACTION)
        .input_from("transcript")
        .output_as("redacted")
        .done()

    .step("summarize")
        .capability(Capability.SUMMARIZATION)
        .when(lambda ctx: len(ctx.get("redacted", {}).get("text", "")) > 500)
        .input_from("redacted")
        .output_as("summary")
        .optional()
        .done()

    .build()
)
```

**Step Configuration:**
- `.capability(cap)` - Required capability
- `.prefer_providers(...)` - Provider preference order
- `.with_fallback(...)` - Fallback configuration
- `.with_retry(...)` - Retry policy
- `.when(condition)` - Conditional execution
- `.optional()` - Mark step as non-critical
- `.compensate_with(fn)` - Saga rollback action

### 3. Event System (`events/`)

Real-time event emission for WebSocket/SSE streaming:

```python
from example_service.infra.ai.events import (
    EventType,
    EventStore,
    get_event_store,
)

# Subscribe to execution events
store = get_event_store()
async for event in store.subscribe(execution_id):
    match event.event_type:
        case EventType.STEP_COMPLETED:
            print(f"Step {event.step_name} completed")
        case EventType.PROGRESS_UPDATE:
            print(f"Progress: {event.progress_percent}%")
        case EventType.COST_INCURRED:
            print(f"Cost: ${event.cost_usd}")
```

**Event Types:**
- `WORKFLOW_STARTED/COMPLETED/FAILED/CANCELLED`
- `STEP_STARTED/COMPLETED/FAILED/SKIPPED/RETRYING`
- `PROGRESS_UPDATE` - Granular progress (25+ points)
- `COST_INCURRED` - Real cost tracking
- `COMPENSATION_STARTED/COMPLETED/FAILED`

### 4. Observability (`observability/`)

Full production observability:

```python
from example_service.infra.ai.observability import (
    get_ai_tracer,
    get_ai_metrics,
    get_budget_service,
)

# Tracing
tracer = get_ai_tracer()
async with tracer.pipeline_span(pipeline, context):
    # Execution is traced
    pass

# Metrics
metrics = get_ai_metrics()
metrics.record_pipeline_execution(
    pipeline_name="call_analysis",
    status="success",
    duration_seconds=45.2,
    total_cost_usd=Decimal("0.15"),
)

# Budget
budget = get_budget_service()
check = await budget.check_budget(tenant_id)
if not check.allowed:
    raise BudgetExceededException(check.message)
```

**Metrics Exported:**
- `ai_pipeline_executions_total` - Pipeline execution count
- `ai_pipeline_duration_seconds` - Execution duration histogram
- `ai_pipeline_cost_usd` - Cost per execution
- `ai_step_executions_total` - Step-level metrics
- `ai_budget_exceeded_total` - Budget violations

### 5. Orchestrator (`instrumented_orchestrator.py`)

Production entry point integrating all components:

```python
from example_service.infra.ai import InstrumentedOrchestrator
from example_service.infra.ai.pipelines import get_pipeline

orchestrator = InstrumentedOrchestrator(
    api_keys={
        "openai": "sk-...",
        "anthropic": "sk-ant-...",
        "deepgram": "...",
    },
)

result = await orchestrator.execute(
    pipeline=get_pipeline("call_analysis"),
    input_data={"audio_url": "https://..."},
    tenant_id="tenant-123",
)

# Result includes full details
print(f"Success: {result.success}")
print(f"Cost: ${result.total_cost_usd}")
print(f"Duration: {result.total_duration_ms}ms")
print(f"Output: {result.output}")
```

## API Endpoints

### REST API (`/api/v1/ai/pipelines`)

| Endpoint                 | Method | Description              |
| ------------------------ | ------ | ------------------------ |
| `/execute`               | POST   | Execute a pipeline       |
| `/`                      | GET    | List available pipelines |
| `/{execution_id}`        | GET    | Get execution progress   |
| `/{execution_id}/result` | GET    | Get execution result     |
| `/{execution_id}`        | DELETE | Cancel execution         |
| `/capabilities`          | GET    | List capabilities        |
| `/providers`             | GET    | List providers           |
| `/budget/status`         | GET    | Get budget status        |
| `/budget/spend`          | GET    | Get spend summary        |
| `/health`                | GET    | Health check             |

### WebSocket (`/api/v1/ai/pipelines/{execution_id}/events`)

Stream real-time events:
```javascript
const ws = new WebSocket('/api/v1/ai/pipelines/exec-123/events');
ws.onmessage = (event) => {
    const data = JSON.parse(event.data);
    console.log(`Event: ${data.event_type}`, data);
};
```

## Data Flow

```
1. Client sends POST /ai/pipelines/execute
   └─> { pipeline_name: "call_analysis", input_data: {...} }

2. Router validates request, creates execution ID
   └─> Checks budget, returns 202 Accepted

3. InstrumentedOrchestrator.execute() starts
   ├─> Pre-execution budget check
   ├─> Creates pipeline span (OpenTelemetry)
   └─> Delegates to SagaCoordinator

4. SagaCoordinator executes steps
   ├─> Emits WORKFLOW_STARTED event
   ├─> For each step:
   │   ├─> Emits STEP_STARTED event
   │   ├─> Gets fallback chain from registry
   │   ├─> Tries providers until success
   │   ├─> Records cost, duration
   │   └─> Emits STEP_COMPLETED/FAILED event
   └─> On failure: runs compensation

5. Events stream to WebSocket clients
   └─> Client shows real-time progress

6. Orchestrator records final metrics
   └─> Tracks spend in budget service

7. Client polls /result or receives via WebSocket
```

## Cost Tracking

Real costs are calculated from actual usage:

```python
# LLM costs (per token)
cost = (input_tokens / 1000) * input_cost_per_1k + \
       (output_tokens / 1000) * output_cost_per_1k

# Transcription costs (per minute)
cost = (duration_seconds / 60) * cost_per_minute

# PII costs (per character)
cost = character_count * cost_per_char
```

Budget policies:
- `WARN` - Log warning, allow execution
- `SOFT_BLOCK` - Warn, allow if under estimated cost
- `HARD_BLOCK` - Reject if over limit

## Migration from Legacy API

**Before (workflow-based):**
```python
orchestrator = AIOrchestrator(session, provider_factory)
result = await orchestrator.execute_workflow(
    WorkflowRequest(
        workflow_type=WorkflowType.TRANSCRIBE_AND_SUMMARIZE,
        audio_url="...",
    )
)
```

**After (pipeline-based):**
```python
orchestrator = get_instrumented_orchestrator()
result = await orchestrator.execute(
    pipeline=get_pipeline("call_analysis"),
    input_data={"audio_url": "..."},
    tenant_id="tenant-123",
)
```

## Testing

```bash
# Run all AI tests
pytest tests/unit/test_infra/test_ai/ -v

# Run specific test module
pytest tests/unit/test_infra/test_ai/test_capability_registry.py -v
pytest tests/unit/test_infra/test_ai/test_pipeline_builder.py -v
pytest tests/unit/test_infra/test_ai/test_orchestrator.py -v
```

## Configuration

Environment variables:
```bash
# Provider API keys
OPENAI_API_KEY=sk-...
ANTHROPIC_API_KEY=sk-ant-...
DEEPGRAM_API_KEY=...

# Budget defaults
AI_DEFAULT_MONTHLY_BUDGET_USD=100.00
AI_BUDGET_POLICY=soft_block

# Observability
OTEL_SERVICE_NAME=example-service
OTEL_EXPORTER_OTLP_ENDPOINT=http://jaeger:4317
```

## File Structure

```
example_service/infra/ai/
├── capabilities/
│   ├── types.py          # Capability, QualityTier, CostUnit enums
│   ├── registry.py       # CapabilityRegistry singleton
│   ├── adapters/
│   │   ├── base.py       # ProviderAdapter ABC
│   │   ├── openai.py     # OpenAI adapter
│   │   ├── anthropic.py  # Anthropic adapter
│   │   ├── deepgram.py   # Deepgram adapter
│   │   └── accent.py     # Internal PII service
│   └── builtin_providers.py
├── pipelines/
│   ├── types.py          # PipelineDefinition, PipelineStep
│   ├── builder.py        # Fluent DSL
│   ├── executor.py       # PipelineExecutor
│   └── predefined.py     # Pre-built pipelines
├── events/
│   ├── types.py          # Event types and schemas
│   ├── store.py          # EventStore with pub/sub
│   └── saga.py           # SagaCoordinator
├── observability/
│   ├── tracing.py        # OpenTelemetry integration
│   ├── metrics.py        # Prometheus metrics
│   └── budget.py         # Budget tracking
├── orchestrator.py       # Legacy orchestrator (preserved)
└── instrumented_orchestrator.py  # New production entry point

example_service/features/ai/
├── router.py             # Legacy REST endpoints
├── schemas.py            # Legacy Pydantic schemas
└── pipeline/             # Pipeline-based AI API
    ├── router.py         # Pipeline REST endpoints
    └── schemas.py        # Pipeline Pydantic schemas
```
