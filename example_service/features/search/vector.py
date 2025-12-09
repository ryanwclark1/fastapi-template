"""Semantic/vector search using embeddings.

Provides embedding-based semantic search capabilities:
- Vector similarity search with pgvector
- Hybrid search combining FTS and vector
- Embedding generation helpers
- Index management

Note: Requires pgvector extension and an embedding provider.

Usage:
    vector_search = VectorSearchService(session)

    # Search by vector
    results = await vector_search.search_similar(
        embedding=[0.1, 0.2, ...],
        entity_type="posts",
        limit=10,
    )

    # Hybrid search
    results = await vector_search.hybrid_search(
        query="python tutorial",
        embedding=[0.1, 0.2, ...],
        fts_weight=0.6,
        vector_weight=0.4,
    )
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import StrEnum
import logging
from typing import TYPE_CHECKING, Any, Sequence

from sqlalchemy import Float, Integer, String, func, select, text
from sqlalchemy.orm import Mapped, mapped_column

from example_service.core.database import TimestampedBase

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


class DistanceMetric(StrEnum):
    """Vector distance metrics for similarity search."""

    COSINE = "cosine"  # Cosine similarity (1 - cosine distance)
    L2 = "l2"  # Euclidean distance
    INNER_PRODUCT = "inner_product"  # Inner product (for normalized vectors)


@dataclass
class VectorSearchConfig:
    """Configuration for vector search."""

    enabled: bool = False  # Disabled by default (requires setup)
    embedding_dimensions: int = 384  # Default for many models
    default_metric: DistanceMetric = DistanceMetric.COSINE
    default_limit: int = 10
    min_similarity: float = 0.5  # Minimum similarity threshold
    use_ivfflat_index: bool = True  # Use IVFFlat index for performance
    ivfflat_lists: int = 100  # Number of lists for IVFFlat


@dataclass
class VectorSearchResult:
    """A single vector search result."""

    entity_type: str
    entity_id: str
    similarity: float
    distance: float
    data: dict[str, Any] | None = None


@dataclass
class HybridSearchResult:
    """Combined FTS and vector search result."""

    entity_type: str
    entity_id: str
    fts_rank: float
    vector_similarity: float
    combined_score: float
    data: dict[str, Any] | None = None


class EmbeddingProvider(ABC):
    """Abstract base class for embedding providers."""

    @property
    @abstractmethod
    def dimensions(self) -> int:
        """Get the embedding dimensions."""
        ...

    @abstractmethod
    async def embed_text(self, text: str) -> list[float]:
        """Generate embedding for text.

        Args:
            text: Text to embed.

        Returns:
            Embedding vector.
        """
        ...

    @abstractmethod
    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """Generate embeddings for multiple texts.

        Args:
            texts: List of texts to embed.

        Returns:
            List of embedding vectors.
        """
        ...


class MockEmbeddingProvider(EmbeddingProvider):
    """Mock embedding provider for testing.

    Generates deterministic pseudo-embeddings based on text.
    """

    def __init__(self, dimensions: int = 384) -> None:
        """Initialize the mock provider.

        Args:
            dimensions: Embedding dimensions.
        """
        self._dimensions = dimensions

    @property
    def dimensions(self) -> int:
        """Get the embedding dimensions."""
        return self._dimensions

    async def embed_text(self, text: str) -> list[float]:
        """Generate a mock embedding.

        Creates a deterministic embedding based on text hash.
        """
        import hashlib

        # Create deterministic hash-based embedding
        text_hash = hashlib.sha256(text.encode()).hexdigest()

        # Convert hash to floats
        embedding = []
        for i in range(0, min(len(text_hash), self._dimensions * 2), 2):
            hex_pair = text_hash[i : i + 2]
            value = int(hex_pair, 16) / 255.0  # Normalize to 0-1
            embedding.append(value * 2 - 1)  # Scale to -1 to 1

        # Pad if needed
        while len(embedding) < self._dimensions:
            embedding.append(0.0)

        return embedding[: self._dimensions]

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """Generate mock embeddings for multiple texts."""
        return [await self.embed_text(text) for text in texts]


class VectorSearchService:
    """Service for semantic/vector search.

    Uses pgvector for efficient similarity search with optional
    hybrid ranking combining FTS and vector scores.

    Example:
        service = VectorSearchService(session, embedding_provider)

        # Generate embedding for query
        embedding = await embedding_provider.embed_text("python tutorial")

        # Search similar content
        results = await service.search_similar(
            embedding=embedding,
            entity_type="posts",
            limit=10,
        )
    """

    def __init__(
        self,
        session: AsyncSession,
        embedding_provider: EmbeddingProvider | None = None,
        config: VectorSearchConfig | None = None,
    ) -> None:
        """Initialize the vector search service.

        Args:
            session: Database session.
            embedding_provider: Provider for generating embeddings.
            config: Vector search configuration.
        """
        self.session = session
        self.embedding_provider = embedding_provider or MockEmbeddingProvider()
        self.config = config or VectorSearchConfig()

    async def is_available(self) -> bool:
        """Check if vector search is available.

        Verifies pgvector extension is installed.

        Returns:
            True if vector search is available.
        """
        if not self.config.enabled:
            return False

        try:
            result = await self.session.execute(
                text("SELECT 1 FROM pg_extension WHERE extname = 'vector'")
            )
            return result.scalar() is not None
        except Exception as e:
            logger.debug("Vector search not available: %s", e)
            return False

    async def search_similar(
        self,
        embedding: list[float],
        entity_type: str | None = None,
        limit: int | None = None,
        min_similarity: float | None = None,
        metric: DistanceMetric | None = None,
    ) -> list[VectorSearchResult]:
        """Search for similar content using vector similarity.

        Args:
            embedding: Query embedding vector.
            entity_type: Filter by entity type.
            limit: Maximum results.
            min_similarity: Minimum similarity threshold.
            metric: Distance metric to use.

        Returns:
            List of similar results.
        """
        if not await self.is_available():
            logger.warning("Vector search not available")
            return []

        limit = limit or self.config.default_limit
        min_similarity = min_similarity or self.config.min_similarity
        metric = metric or self.config.default_metric

        # Build the similarity query based on metric
        embedding_str = f"[{','.join(str(x) for x in embedding)}]"

        if metric == DistanceMetric.COSINE:
            # Cosine similarity: 1 - cosine distance
            distance_op = "<=>"
            similarity_expr = f"1 - (embedding {distance_op} '{embedding_str}'::vector)"
        elif metric == DistanceMetric.L2:
            # L2 distance (lower is more similar)
            distance_op = "<->"
            # Convert distance to similarity (inverse)
            similarity_expr = f"1 / (1 + (embedding {distance_op} '{embedding_str}'::vector))"
        else:  # INNER_PRODUCT
            distance_op = "<#>"
            similarity_expr = f"-(embedding {distance_op} '{embedding_str}'::vector)"

        # Build query (assumes a generic embeddings table exists)
        # In practice, each entity would have its own embedding column
        query = f"""
            SELECT
                entity_type,
                entity_id,
                {similarity_expr} as similarity,
                (embedding {distance_op} '{embedding_str}'::vector) as distance
            FROM search_embeddings
            WHERE {similarity_expr} >= {min_similarity}
        """

        if entity_type:
            query += f" AND entity_type = '{entity_type}'"

        query += f"""
            ORDER BY distance
            LIMIT {limit}
        """

        try:
            result = await self.session.execute(text(query))
            rows = result.all()

            return [
                VectorSearchResult(
                    entity_type=row[0],
                    entity_id=row[1],
                    similarity=float(row[2]),
                    distance=float(row[3]),
                )
                for row in rows
            ]
        except Exception as e:
            logger.warning("Vector search failed: %s", e)
            return []

    async def hybrid_search(
        self,
        query: str,
        embedding: list[float] | None = None,
        entity_type: str | None = None,
        fts_weight: float = 0.6,
        vector_weight: float = 0.4,
        limit: int | None = None,
    ) -> list[HybridSearchResult]:
        """Perform hybrid search combining FTS and vector similarity.

        Args:
            query: Text query for FTS.
            embedding: Query embedding (generated if not provided).
            entity_type: Filter by entity type.
            fts_weight: Weight for FTS score (0-1).
            vector_weight: Weight for vector score (0-1).
            limit: Maximum results.

        Returns:
            Combined search results.
        """
        if not await self.is_available():
            logger.warning("Vector search not available for hybrid search")
            return []

        # Generate embedding if not provided
        if embedding is None:
            embedding = await self.embedding_provider.embed_text(query)

        limit = limit or self.config.default_limit

        # Normalize weights
        total_weight = fts_weight + vector_weight
        fts_weight = fts_weight / total_weight
        vector_weight = vector_weight / total_weight

        embedding_str = f"[{','.join(str(x) for x in embedding)}]"

        # Hybrid query combining FTS rank and vector similarity
        # This assumes a table with both search_vector and embedding columns
        hybrid_query = f"""
            WITH fts_results AS (
                SELECT
                    entity_type,
                    entity_id,
                    ts_rank(search_vector, websearch_to_tsquery('english', $1)) as fts_rank
                FROM search_embeddings
                WHERE search_vector @@ websearch_to_tsquery('english', $1)
            ),
            vector_results AS (
                SELECT
                    entity_type,
                    entity_id,
                    1 - (embedding <=> '{embedding_str}'::vector) as vector_similarity
                FROM search_embeddings
            )
            SELECT
                COALESCE(f.entity_type, v.entity_type) as entity_type,
                COALESCE(f.entity_id, v.entity_id) as entity_id,
                COALESCE(f.fts_rank, 0) as fts_rank,
                COALESCE(v.vector_similarity, 0) as vector_similarity,
                (COALESCE(f.fts_rank, 0) * {fts_weight} +
                 COALESCE(v.vector_similarity, 0) * {vector_weight}) as combined_score
            FROM fts_results f
            FULL OUTER JOIN vector_results v
                ON f.entity_type = v.entity_type AND f.entity_id = v.entity_id
            WHERE COALESCE(f.fts_rank, 0) > 0 OR COALESCE(v.vector_similarity, 0) > 0.5
            ORDER BY combined_score DESC
            LIMIT {limit}
        """

        try:
            result = await self.session.execute(text(hybrid_query), {"query": query})
            rows = result.all()

            return [
                HybridSearchResult(
                    entity_type=row[0],
                    entity_id=row[1],
                    fts_rank=float(row[2]),
                    vector_similarity=float(row[3]),
                    combined_score=float(row[4]),
                )
                for row in rows
            ]
        except Exception as e:
            logger.warning("Hybrid search failed: %s", e)
            return []

    async def index_embedding(
        self,
        entity_type: str,
        entity_id: str,
        text: str,
        embedding: list[float] | None = None,
    ) -> bool:
        """Index an embedding for an entity.

        Args:
            entity_type: Type of entity.
            entity_id: Entity ID.
            text: Text content (for FTS).
            embedding: Pre-computed embedding or None to generate.

        Returns:
            True if indexed successfully.
        """
        if not await self.is_available():
            return False

        # Generate embedding if not provided
        if embedding is None:
            embedding = await self.embedding_provider.embed_text(text)

        embedding_str = f"[{','.join(str(x) for x in embedding)}]"

        # Upsert the embedding
        upsert_query = """
            INSERT INTO search_embeddings (entity_type, entity_id, content, search_vector, embedding)
            VALUES ($1, $2, $3, to_tsvector('english', $3), $4::vector)
            ON CONFLICT (entity_type, entity_id)
            DO UPDATE SET
                content = EXCLUDED.content,
                search_vector = EXCLUDED.search_vector,
                embedding = EXCLUDED.embedding,
                updated_at = NOW()
        """

        try:
            await self.session.execute(
                text(upsert_query),
                {
                    "entity_type": entity_type,
                    "entity_id": entity_id,
                    "content": text,
                    "embedding": embedding_str,
                },
            )
            await self.session.flush()
            return True
        except Exception as e:
            logger.warning("Failed to index embedding: %s", e)
            return False

    async def delete_embedding(
        self,
        entity_type: str,
        entity_id: str,
    ) -> bool:
        """Delete an embedding.

        Args:
            entity_type: Type of entity.
            entity_id: Entity ID.

        Returns:
            True if deleted successfully.
        """
        try:
            await self.session.execute(
                text("DELETE FROM search_embeddings WHERE entity_type = $1 AND entity_id = $2"),
                {"entity_type": entity_type, "entity_id": entity_id},
            )
            await self.session.flush()
            return True
        except Exception as e:
            logger.warning("Failed to delete embedding: %s", e)
            return False


def get_vector_setup_sql(
    dimensions: int = 384,
    use_ivfflat: bool = True,
    ivfflat_lists: int = 100,
) -> str:
    """Generate SQL for setting up vector search.

    Args:
        dimensions: Embedding dimensions.
        use_ivfflat: Whether to use IVFFlat index.
        ivfflat_lists: Number of lists for IVFFlat.

    Returns:
        SQL statements for setup.
    """
    sql = f"""
-- Enable pgvector extension
CREATE EXTENSION IF NOT EXISTS vector;

-- Create embeddings table
CREATE TABLE IF NOT EXISTS search_embeddings (
    id SERIAL PRIMARY KEY,
    entity_type VARCHAR(100) NOT NULL,
    entity_id VARCHAR(255) NOT NULL,
    content TEXT,
    search_vector TSVECTOR,
    embedding VECTOR({dimensions}),
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(entity_type, entity_id)
);

-- Create GIN index for full-text search
CREATE INDEX IF NOT EXISTS idx_search_embeddings_fts
    ON search_embeddings USING GIN(search_vector);

-- Create index for entity lookup
CREATE INDEX IF NOT EXISTS idx_search_embeddings_entity
    ON search_embeddings(entity_type, entity_id);
"""

    if use_ivfflat:
        sql += f"""
-- Create IVFFlat index for vector similarity (cosine)
CREATE INDEX IF NOT EXISTS idx_search_embeddings_vector_cosine
    ON search_embeddings USING ivfflat (embedding vector_cosine_ops)
    WITH (lists = {ivfflat_lists});
"""
    else:
        sql += """
-- Create HNSW index for vector similarity (more accurate but slower to build)
CREATE INDEX IF NOT EXISTS idx_search_embeddings_vector_hnsw
    ON search_embeddings USING hnsw (embedding vector_cosine_ops);
"""

    return sql


__all__ = [
    "DistanceMetric",
    "EmbeddingProvider",
    "HybridSearchResult",
    "MockEmbeddingProvider",
    "VectorSearchConfig",
    "VectorSearchResult",
    "VectorSearchService",
    "get_vector_setup_sql",
]
