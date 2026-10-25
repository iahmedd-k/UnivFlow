from dataclasses import dataclass

import sqlalchemy as sa
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.document_chunk import DocumentChunk


@dataclass(frozen=True)
class RetrievedChunk:
    """A document chunk with a retrieval similarity/rank score."""

    chunk_id: int
    document_id: int
    content: str
    page_number: int
    page_numbers: list[int]
    content_type: str
    metadata: dict
    score: float


class DocumentChunkRepository:

    def __init__(self, db: Session):
        self.db = db

    def create(
        self,
        document_id: int,
        user_id: int,
        page_number: int,
        page_numbers: list[int],
        content: str,
        content_type: str,
        metadata: dict,
        embedding: list[float],
    ) -> DocumentChunk:
        chunk = DocumentChunk(
            document_id=document_id,
            user_id=user_id,
            page_number=page_number,
            page_numbers=page_numbers,
            content=content,
            content_type=content_type,
            metadata_=metadata,
            embedding=embedding,
        )

        self.db.add(chunk)
        self.db.commit()
        self.db.refresh(chunk)

        return chunk

    def create_many(
        self,
        chunks: list[dict],
    ) -> list[DocumentChunk]:
        models = [
            DocumentChunk(
                document_id=chunk["document_id"],
                user_id=chunk["user_id"],
                page_number=chunk["page_number"],
                page_numbers=chunk["page_numbers"],
                content=chunk["content"],
                content_type=chunk["content_type"],
                metadata_=chunk["metadata"],
                embedding=chunk["embedding"],
            )
            for chunk in chunks
        ]
        self.db.add_all(models)
        self.db.commit()
        for model in models:
            self.db.refresh(model)

        return models

    def list_by_document(
        self,
        document_id: int,
    ) -> list[DocumentChunk]:
        statement = (
            select(DocumentChunk)
            .where(DocumentChunk.document_id == document_id)
            .order_by(DocumentChunk.id)
        )

        return list(self.db.scalars(statement))

    def list_by_user(
        self,
        user_id: int,
    ) -> list[DocumentChunk]:
        statement = (
            select(DocumentChunk)
            .where(DocumentChunk.user_id == user_id)
            .order_by(DocumentChunk.id)
        )

        return list(self.db.scalars(statement))

    def delete_by_document(self, document_id: int) -> None:
        statement = select(DocumentChunk).where(
            DocumentChunk.document_id == document_id
        )
        for chunk in self.db.scalars(statement):
            self.db.delete(chunk)
        self.db.commit()

    def count_by_document(self, document_id: int) -> int:
        statement = select(DocumentChunk).where(
            DocumentChunk.document_id == document_id
        )
        return len(list(self.db.scalars(statement)))

    def search_by_embedding(
        self,
        user_id: int,
        query_vector: list[float],
        top_k: int,
        document_ids: list[int] | None = None,
    ) -> list[RetrievedChunk]:
        """Return the top-K chunks closest to ``query_vector`` for a user.

        Uses pgvector cosine distance (``<=>``); results are ordered by
        ascending distance (most similar first). The ``user_id`` filter
        guarantees a user can only retrieve their own chunks. Optionally
        filter to specific documents via ``document_ids``.
        """
        distance = DocumentChunk.embedding.cosine_distance(query_vector)
        statement = (
            select(
                DocumentChunk,
                distance.label("distance"),
            )
            .where(DocumentChunk.user_id == user_id)
        )

        if document_ids:
            statement = statement.where(
                DocumentChunk.document_id.in_(document_ids),
            )

        statement = statement.order_by("distance").limit(top_k)

        rows = self.db.execute(statement).all()
        return [
            self._to_retrieved_chunk(chunk, 1.0 - float(distance))
            for chunk, distance in rows
        ]

    def search_by_text(
        self,
        user_id: int,
        query: str,
        top_k: int,
        language: str = "english",
        document_ids: list[int] | None = None,
    ) -> list[RetrievedChunk]:
        """Return the top-K chunks matching ``query`` via PostgreSQL full-text search.

        Uses ``websearch_to_tsquery`` with the configured language to parse a
        user query, filters strictly to the given ``user_id`` (ownership), and
        ranks results with ``ts_rank`` descending. Optionally filter to
        specific documents via ``document_ids``.
        """
        search_col = sa.column("search_vector", type_=sa.dialects.postgresql.TSVECTOR)
        tsquery = sa.func.websearch_to_tsquery(language, query)
        statement = (
            select(
                DocumentChunk,
                sa.func.ts_rank(
                    search_col,
                    tsquery,
                ).label("rank"),
            )
            .where(DocumentChunk.user_id == user_id)
            .where(search_col.op("@@")(tsquery))
        )

        if document_ids:
            statement = statement.where(
                DocumentChunk.document_id.in_(document_ids),
            )

        statement = statement.order_by(sa.desc("rank")).limit(top_k)

        rows = self.db.execute(statement).all()
        return [
            self._to_retrieved_chunk(chunk, float(rank))
            for chunk, rank in rows
        ]

    @staticmethod
    def _to_retrieved_chunk(chunk: DocumentChunk, score: float) -> RetrievedChunk:
        return RetrievedChunk(
            chunk_id=chunk.id,
            document_id=chunk.document_id,
            content=chunk.content,
            page_number=chunk.page_number,
            page_numbers=list(chunk.page_numbers or []),
            content_type=chunk.content_type,
            metadata=chunk.metadata_,
            score=score,
        )
