"""Pre-built agent types for common use cases.

This module provides ready-to-use agent configurations for:
- RAG (Retrieval-Augmented Generation) agents
- Code generation and analysis agents
- Data analysis and reporting agents
- Customer support agents
- Content creation agents

Each agent type comes with:
- Pre-configured prompts and system messages
- Tool definitions for common operations
- Memory configuration optimized for the use case
- Structured output schemas

Example:
    from example_service.infra.ai.agents.prebuilt import (
        create_rag_agent,
        create_code_agent,
        create_data_analysis_agent,
    )

    # Create a RAG agent with document search
    rag_agent = create_rag_agent(
        name="docs_assistant",
        retriever=my_retriever,
        llm_provider="openai",
    )

    # Execute a query
    result = await rag_agent.run("What is the refund policy?")
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Protocol, runtime_checkable

from pydantic import BaseModel, Field

from example_service.infra.ai.agents.memory import (
    BufferMemory,
    ConversationMemory,
    WindowMemory,
    create_memory,
)
from example_service.infra.ai.agents.structured_output import (
    StructuredOutputParser,
)
from example_service.infra.ai.agents.workflows import (
    FunctionNode,
    Workflow,
    WorkflowBuilder,
)


# =============================================================================
# Agent Type Enums
# =============================================================================


class AgentType(str, Enum):
    """Pre-built agent types."""

    RAG = "rag"
    CODE_GENERATION = "code_generation"
    DATA_ANALYSIS = "data_analysis"
    CUSTOMER_SUPPORT = "customer_support"
    CONTENT_CREATION = "content_creation"
    RESEARCH = "research"
    TASK_AUTOMATION = "task_automation"


# =============================================================================
# Tool Protocols
# =============================================================================


@runtime_checkable
class Retriever(Protocol):
    """Protocol for document retrievers."""

    async def retrieve(
        self,
        query: str,
        top_k: int = 5,
        filters: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        """Retrieve relevant documents.

        Args:
            query: Search query
            top_k: Number of results to return
            filters: Optional metadata filters

        Returns:
            List of document dictionaries with 'content' and 'metadata' keys
        """
        ...


@runtime_checkable
class CodeExecutor(Protocol):
    """Protocol for code execution."""

    async def execute(
        self,
        code: str,
        language: str = "python",
        timeout_seconds: int = 30,
    ) -> dict[str, Any]:
        """Execute code in a sandbox.

        Args:
            code: Code to execute
            language: Programming language
            timeout_seconds: Execution timeout

        Returns:
            Dict with 'output', 'error', 'execution_time' keys
        """
        ...


@runtime_checkable
class DataSource(Protocol):
    """Protocol for data sources."""

    async def query(
        self,
        query: str,
        parameters: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        """Query the data source.

        Args:
            query: Query string (SQL, GraphQL, etc.)
            parameters: Query parameters

        Returns:
            List of result dictionaries
        """
        ...


# =============================================================================
# Structured Output Schemas
# =============================================================================


class RAGResponse(BaseModel):
    """Structured response from RAG agent."""

    answer: str = Field(..., description="The answer to the user's question")
    confidence: float = Field(
        ..., ge=0, le=1, description="Confidence score (0-1)"
    )
    sources: list[str] = Field(
        default_factory=list, description="Source document references"
    )
    citations: list[dict[str, str]] = Field(
        default_factory=list, description="Inline citations with quotes"
    )
    needs_clarification: bool = Field(
        False, description="Whether the question needs clarification"
    )
    follow_up_questions: list[str] = Field(
        default_factory=list, description="Suggested follow-up questions"
    )


class CodeGenerationResponse(BaseModel):
    """Structured response from code generation agent."""

    code: str = Field(..., description="Generated code")
    language: str = Field(..., description="Programming language")
    explanation: str = Field(..., description="Explanation of the code")
    test_cases: list[str] = Field(
        default_factory=list, description="Test cases for the code"
    )
    dependencies: list[str] = Field(
        default_factory=list, description="Required dependencies"
    )
    complexity: str = Field(
        "medium", description="Estimated complexity (low/medium/high)"
    )
    security_notes: list[str] = Field(
        default_factory=list, description="Security considerations"
    )


class DataAnalysisResponse(BaseModel):
    """Structured response from data analysis agent."""

    summary: str = Field(..., description="Summary of the analysis")
    insights: list[str] = Field(
        default_factory=list, description="Key insights discovered"
    )
    statistics: dict[str, Any] = Field(
        default_factory=dict, description="Computed statistics"
    )
    visualizations: list[dict[str, Any]] = Field(
        default_factory=list, description="Visualization specifications"
    )
    recommendations: list[str] = Field(
        default_factory=list, description="Action recommendations"
    )
    data_quality_notes: list[str] = Field(
        default_factory=list, description="Data quality observations"
    )


class CustomerSupportResponse(BaseModel):
    """Structured response from customer support agent."""

    response: str = Field(..., description="Response to the customer")
    sentiment: str = Field(
        ..., description="Detected customer sentiment (positive/neutral/negative)"
    )
    intent: str = Field(..., description="Detected customer intent")
    resolution_status: str = Field(
        ..., description="Resolution status (resolved/pending/escalate)"
    )
    suggested_actions: list[str] = Field(
        default_factory=list, description="Suggested follow-up actions"
    )
    related_articles: list[str] = Field(
        default_factory=list, description="Related help articles"
    )
    escalation_reason: str | None = Field(
        None, description="Reason for escalation if needed"
    )


class ContentCreationResponse(BaseModel):
    """Structured response from content creation agent."""

    content: str = Field(..., description="Generated content")
    title: str = Field(..., description="Suggested title")
    meta_description: str = Field(..., description="Meta description for SEO")
    keywords: list[str] = Field(
        default_factory=list, description="SEO keywords"
    )
    tone: str = Field(..., description="Content tone")
    word_count: int = Field(..., description="Word count")
    reading_time_minutes: int = Field(..., description="Estimated reading time")
    suggested_images: list[str] = Field(
        default_factory=list, description="Suggested image descriptions"
    )


# =============================================================================
# Agent Configuration
# =============================================================================


@dataclass
class AgentConfig:
    """Configuration for a pre-built agent."""

    name: str
    agent_type: AgentType
    description: str
    system_prompt: str
    tools: list[dict[str, Any]] = field(default_factory=list)
    memory_type: str = "conversation"
    memory_config: dict[str, Any] = field(default_factory=dict)
    output_schema: type[BaseModel] | None = None
    llm_provider: str = "openai"
    llm_model: str | None = None
    temperature: float = 0.7
    max_tokens: int = 2048
    metadata: dict[str, Any] = field(default_factory=dict)


# =============================================================================
# Pre-built Agent Factory
# =============================================================================


class PrebuiltAgent:
    """Base class for pre-built agents.

    Provides a unified interface for executing agent tasks with
    built-in memory, tools, and structured output.
    """

    def __init__(
        self,
        config: AgentConfig,
        llm_client: Any = None,
    ) -> None:
        """Initialize the agent.

        Args:
            config: Agent configuration
            llm_client: Optional LLM client (creates default if not provided)
        """
        self.config = config
        self.llm_client = llm_client
        self.memory = create_memory(
            config.memory_type,
            **config.memory_config,
        )
        self.output_parser = (
            StructuredOutputParser(config.output_schema)
            if config.output_schema
            else None
        )
        self._tools: dict[str, Any] = {}
        self._setup_tools()

    def _setup_tools(self) -> None:
        """Set up tools from configuration."""
        for tool_config in self.config.tools:
            tool_name = tool_config.get("name", "")
            self._tools[tool_name] = tool_config

    def add_tool(self, name: str, func: Any, description: str = "") -> None:
        """Add a custom tool to the agent.

        Args:
            name: Tool name
            func: Tool function (sync or async)
            description: Tool description
        """
        self._tools[name] = {
            "name": name,
            "function": func,
            "description": description,
        }

    async def run(
        self,
        query: str,
        context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Execute the agent with a query.

        Args:
            query: User query or task
            context: Optional context data

        Returns:
            Agent response dictionary
        """
        # Add query to memory
        self.memory.add_message({"role": "user", "content": query})

        # Build messages for LLM
        messages = [
            {"role": "system", "content": self.config.system_prompt},
            *self.memory.get_messages(),
        ]

        # Add context if provided
        if context:
            context_msg = f"Context: {context}"
            messages.insert(1, {"role": "system", "content": context_msg})

        # This is a placeholder - actual implementation would use LLM client
        response = await self._execute_llm(messages)

        # Add response to memory
        self.memory.add_message({"role": "assistant", "content": response})

        # Parse structured output if configured
        if self.output_parser:
            parsed = self.output_parser.parse(response)
            return {"raw": response, "parsed": parsed}

        return {"raw": response}

    async def _execute_llm(self, messages: list[dict]) -> str:
        """Execute LLM call (placeholder for actual implementation)."""
        # This would be replaced with actual LLM client call
        return "Agent response placeholder"

    def get_conversation_history(self) -> list[dict]:
        """Get the conversation history."""
        return self.memory.get_messages()

    def clear_memory(self) -> None:
        """Clear the agent's memory."""
        self.memory.clear()


# =============================================================================
# RAG Agent
# =============================================================================


def create_rag_agent(
    name: str = "rag_assistant",
    retriever: Retriever | None = None,
    llm_provider: str = "openai",
    llm_model: str | None = None,
    system_prompt: str | None = None,
    top_k: int = 5,
    include_sources: bool = True,
) -> PrebuiltAgent:
    """Create a RAG (Retrieval-Augmented Generation) agent.

    Args:
        name: Agent name
        retriever: Document retriever (optional)
        llm_provider: LLM provider name
        llm_model: Specific model to use
        system_prompt: Custom system prompt
        top_k: Number of documents to retrieve
        include_sources: Whether to include source citations

    Returns:
        Configured RAG agent

    Example:
        agent = create_rag_agent(
            name="docs_assistant",
            retriever=my_retriever,
        )
        result = await agent.run("What is the return policy?")
    """
    default_prompt = """You are a helpful assistant that answers questions based on the provided context.

Instructions:
1. Answer questions based ONLY on the provided context
2. If the context doesn't contain enough information, say so
3. Always cite your sources when possible
4. Be concise but thorough
5. If you're not sure, express uncertainty

When citing sources, use the format: [Source: document_name]
"""

    config = AgentConfig(
        name=name,
        agent_type=AgentType.RAG,
        description="Retrieval-Augmented Generation agent for document Q&A",
        system_prompt=system_prompt or default_prompt,
        tools=[
            {
                "name": "search_documents",
                "description": "Search for relevant documents",
                "parameters": {
                    "query": "string",
                    "top_k": "integer",
                    "filters": "object",
                },
            },
        ],
        memory_type="conversation",
        memory_config={"max_short_term": 20},
        output_schema=RAGResponse if include_sources else None,
        llm_provider=llm_provider,
        llm_model=llm_model,
        temperature=0.3,  # Lower temperature for factual responses
        metadata={"top_k": top_k, "include_sources": include_sources},
    )

    agent = PrebuiltAgent(config)

    # Add retriever tool if provided
    if retriever:
        async def search_tool(query: str, top_k: int = top_k) -> list[dict]:
            return await retriever.retrieve(query, top_k=top_k)

        agent.add_tool(
            "search_documents",
            search_tool,
            "Search for relevant documents",
        )

    return agent


# =============================================================================
# Code Generation Agent
# =============================================================================


def create_code_agent(
    name: str = "code_assistant",
    executor: CodeExecutor | None = None,
    llm_provider: str = "openai",
    llm_model: str | None = None,
    languages: list[str] | None = None,
    include_tests: bool = True,
    include_docs: bool = True,
) -> PrebuiltAgent:
    """Create a code generation and analysis agent.

    Args:
        name: Agent name
        executor: Code executor for testing (optional)
        llm_provider: LLM provider name
        llm_model: Specific model to use
        languages: Supported programming languages
        include_tests: Whether to generate test cases
        include_docs: Whether to generate documentation

    Returns:
        Configured code agent

    Example:
        agent = create_code_agent(
            name="python_dev",
            languages=["python"],
        )
        result = await agent.run("Write a function to sort a list")
    """
    supported_langs = languages or ["python", "javascript", "typescript", "go", "rust"]
    langs_str = ", ".join(supported_langs)

    default_prompt = f"""You are an expert software engineer specializing in {langs_str}.

Your capabilities:
1. Write clean, efficient, and well-documented code
2. Explain code and algorithms clearly
3. Debug and fix issues
4. Suggest improvements and best practices
5. Generate comprehensive test cases

Guidelines:
- Always follow the language's best practices and conventions
- Include error handling where appropriate
- Write self-documenting code with clear variable names
- Add comments for complex logic
- Consider edge cases and potential issues
- Suggest relevant design patterns when appropriate

Security:
- Never generate code that could be harmful or malicious
- Always sanitize user inputs
- Follow secure coding practices
- Note any potential security concerns
"""

    config = AgentConfig(
        name=name,
        agent_type=AgentType.CODE_GENERATION,
        description="Code generation and analysis assistant",
        system_prompt=default_prompt,
        tools=[
            {
                "name": "execute_code",
                "description": "Execute code in a sandbox",
                "parameters": {
                    "code": "string",
                    "language": "string",
                    "timeout": "integer",
                },
            },
            {
                "name": "analyze_code",
                "description": "Analyze code for issues and improvements",
                "parameters": {"code": "string", "language": "string"},
            },
        ],
        memory_type="window",
        memory_config={"window_size": 15},
        output_schema=CodeGenerationResponse,
        llm_provider=llm_provider,
        llm_model=llm_model,
        temperature=0.2,  # Lower temperature for precise code
        metadata={
            "languages": supported_langs,
            "include_tests": include_tests,
            "include_docs": include_docs,
        },
    )

    agent = PrebuiltAgent(config)

    # Add executor tool if provided
    if executor:
        async def execute_tool(code: str, language: str = "python") -> dict:
            return await executor.execute(code, language)

        agent.add_tool(
            "execute_code",
            execute_tool,
            "Execute code in a sandbox environment",
        )

    return agent


# =============================================================================
# Data Analysis Agent
# =============================================================================


def create_data_analysis_agent(
    name: str = "data_analyst",
    data_source: DataSource | None = None,
    llm_provider: str = "openai",
    llm_model: str | None = None,
    include_visualizations: bool = True,
    max_rows: int = 1000,
) -> PrebuiltAgent:
    """Create a data analysis agent.

    Args:
        name: Agent name
        data_source: Data source for queries (optional)
        llm_provider: LLM provider name
        llm_model: Specific model to use
        include_visualizations: Whether to suggest visualizations
        max_rows: Maximum rows to analyze

    Returns:
        Configured data analysis agent

    Example:
        agent = create_data_analysis_agent(
            name="sales_analyst",
            data_source=my_database,
        )
        result = await agent.run("Analyze Q4 sales trends")
    """
    default_prompt = """You are an expert data analyst with skills in:
- Statistical analysis and hypothesis testing
- Data visualization and storytelling
- SQL and data querying
- Pattern recognition and anomaly detection
- Business intelligence and reporting

Your approach:
1. Understand the business question or goal
2. Identify relevant data and metrics
3. Perform appropriate analysis
4. Generate insights and recommendations
5. Suggest visualizations to communicate findings

Guidelines:
- Always explain your methodology
- Note data quality issues or limitations
- Provide actionable recommendations
- Use appropriate statistical methods
- Consider business context in interpretations
- Be clear about confidence levels and uncertainty
"""

    config = AgentConfig(
        name=name,
        agent_type=AgentType.DATA_ANALYSIS,
        description="Data analysis and insights agent",
        system_prompt=default_prompt,
        tools=[
            {
                "name": "query_data",
                "description": "Query the data source",
                "parameters": {"query": "string", "parameters": "object"},
            },
            {
                "name": "compute_statistics",
                "description": "Compute descriptive statistics",
                "parameters": {"data": "array", "columns": "array"},
            },
            {
                "name": "create_visualization",
                "description": "Create a visualization specification",
                "parameters": {"type": "string", "data": "object", "options": "object"},
            },
        ],
        memory_type="buffer",
        memory_config={"max_messages": 30},
        output_schema=DataAnalysisResponse if include_visualizations else None,
        llm_provider=llm_provider,
        llm_model=llm_model,
        temperature=0.4,
        metadata={
            "include_visualizations": include_visualizations,
            "max_rows": max_rows,
        },
    )

    agent = PrebuiltAgent(config)

    # Add data source tool if provided
    if data_source:
        async def query_tool(query: str, parameters: dict | None = None) -> list:
            return await data_source.query(query, parameters)

        agent.add_tool(
            "query_data",
            query_tool,
            "Query the data source",
        )

    return agent


# =============================================================================
# Customer Support Agent
# =============================================================================


def create_customer_support_agent(
    name: str = "support_agent",
    retriever: Retriever | None = None,
    llm_provider: str = "openai",
    llm_model: str | None = None,
    company_name: str = "Our Company",
    escalation_enabled: bool = True,
) -> PrebuiltAgent:
    """Create a customer support agent.

    Args:
        name: Agent name
        retriever: Knowledge base retriever (optional)
        llm_provider: LLM provider name
        llm_model: Specific model to use
        company_name: Company name for personalization
        escalation_enabled: Whether to enable escalation

    Returns:
        Configured customer support agent

    Example:
        agent = create_customer_support_agent(
            name="support_bot",
            company_name="Acme Corp",
        )
        result = await agent.run("I need to return my order")
    """
    default_prompt = f"""You are a helpful customer support representative for {company_name}.

Your goals:
1. Help customers resolve their issues quickly and efficiently
2. Provide accurate information based on company policies
3. Maintain a friendly, professional, and empathetic tone
4. Escalate to human agents when appropriate

Guidelines:
- Always acknowledge the customer's concern
- Ask clarifying questions when needed
- Provide step-by-step instructions when helpful
- Offer alternative solutions when possible
- End interactions with clear next steps
- Never share sensitive customer information

Escalation criteria:
- Customer requests to speak with a human
- Complex issues requiring manual intervention
- Complaints about serious issues
- Legal or compliance concerns
- Repeated failed resolution attempts
"""

    config = AgentConfig(
        name=name,
        agent_type=AgentType.CUSTOMER_SUPPORT,
        description="Customer support and assistance agent",
        system_prompt=default_prompt,
        tools=[
            {
                "name": "search_knowledge_base",
                "description": "Search the knowledge base",
                "parameters": {"query": "string"},
            },
            {
                "name": "get_order_status",
                "description": "Get order status by order ID",
                "parameters": {"order_id": "string"},
            },
            {
                "name": "create_ticket",
                "description": "Create a support ticket",
                "parameters": {"subject": "string", "description": "string"},
            },
        ],
        memory_type="conversation",
        memory_config={"max_short_term": 25},
        output_schema=CustomerSupportResponse,
        llm_provider=llm_provider,
        llm_model=llm_model,
        temperature=0.5,
        metadata={
            "company_name": company_name,
            "escalation_enabled": escalation_enabled,
        },
    )

    agent = PrebuiltAgent(config)

    # Add retriever tool if provided
    if retriever:
        async def search_tool(query: str) -> list[dict]:
            return await retriever.retrieve(query, top_k=3)

        agent.add_tool(
            "search_knowledge_base",
            search_tool,
            "Search the knowledge base for relevant articles",
        )

    return agent


# =============================================================================
# Content Creation Agent
# =============================================================================


def create_content_agent(
    name: str = "content_creator",
    llm_provider: str = "openai",
    llm_model: str | None = None,
    content_types: list[str] | None = None,
    brand_voice: str | None = None,
    seo_optimized: bool = True,
) -> PrebuiltAgent:
    """Create a content creation agent.

    Args:
        name: Agent name
        llm_provider: LLM provider name
        llm_model: Specific model to use
        content_types: Supported content types
        brand_voice: Brand voice guidelines
        seo_optimized: Whether to optimize for SEO

    Returns:
        Configured content creation agent

    Example:
        agent = create_content_agent(
            name="blog_writer",
            content_types=["blog_posts", "social_media"],
            brand_voice="professional yet approachable",
        )
        result = await agent.run("Write a blog post about AI trends")
    """
    types = content_types or ["blog_posts", "articles", "social_media", "emails"]
    types_str = ", ".join(types)

    voice_guide = brand_voice or "professional, helpful, and engaging"

    default_prompt = f"""You are an expert content creator specializing in {types_str}.

Brand voice: {voice_guide}

Your capabilities:
1. Create compelling, original content
2. Adapt tone and style to target audience
3. Optimize content for SEO when appropriate
4. Structure content for readability
5. Generate headlines and meta descriptions

Guidelines:
- Start with a hook that captures attention
- Use clear, concise language
- Break up text with headers and lists
- Include calls-to-action where appropriate
- Ensure accuracy of any facts or claims
- Maintain consistent brand voice
- Consider the target audience throughout
"""

    if seo_optimized:
        default_prompt += """
SEO Guidelines:
- Include target keywords naturally
- Write compelling meta descriptions
- Use header tags appropriately
- Optimize content length for the platform
- Include internal/external linking suggestions
"""

    config = AgentConfig(
        name=name,
        agent_type=AgentType.CONTENT_CREATION,
        description="Content creation and copywriting agent",
        system_prompt=default_prompt,
        tools=[
            {
                "name": "research_topic",
                "description": "Research a topic for content creation",
                "parameters": {"topic": "string"},
            },
            {
                "name": "check_seo",
                "description": "Check SEO optimization",
                "parameters": {"content": "string", "keywords": "array"},
            },
        ],
        memory_type="buffer",
        memory_config={"max_messages": 20},
        output_schema=ContentCreationResponse,
        llm_provider=llm_provider,
        llm_model=llm_model,
        temperature=0.7,  # Higher temperature for creativity
        metadata={
            "content_types": types,
            "brand_voice": voice_guide,
            "seo_optimized": seo_optimized,
        },
    )

    return PrebuiltAgent(config)


# =============================================================================
# Exports
# =============================================================================


__all__ = [
    # Enums
    "AgentType",
    # Protocols
    "CodeExecutor",
    "DataSource",
    "Retriever",
    # Schemas
    "CodeGenerationResponse",
    "ContentCreationResponse",
    "CustomerSupportResponse",
    "DataAnalysisResponse",
    "RAGResponse",
    # Configuration
    "AgentConfig",
    "PrebuiltAgent",
    # Factory functions
    "create_code_agent",
    "create_content_agent",
    "create_customer_support_agent",
    "create_data_analysis_agent",
    "create_rag_agent",
]
