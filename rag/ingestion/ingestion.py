"""
Ingestion Pipeline — Shared Stages
==================================
Provides generic chunking, embedding, and logical database storage methods used 
by all generic upstream data sources (FRED, SEC, etc.).

Pipeline Stages:
1. Chunking: Splits NLP narratives into isolated sentences with contextual text windows.
2. Embedding: Batches sequences to OpenRouter embedding models for latency reduction.
3. Storage: Handles deduplicated idempotent inserting via deterministic SHA-256 chunk hashes.
"""

import re
import hashlib
import logging
from datetime import datetime
from typing import Generator

from dotenv import load_dotenv
from dataclasses import dataclass, field
from sqlalchemy.dialects.postgresql import insert
from llama_index.core import Settings

from db_setup import engine, financial_documents
from .models import FinancialDoc

load_dotenv()

logger = logging.getLogger(__name__)

@dataclass
class Chunk:
    content:        str
    window_text:    str 
    doc_title:      str
    entity:         str
    entity_type:    str
    date:           str
    source:         str
    chunk_hash:     str
    meta:           dict = field(default_factory=dict)

ABBREVS_PATTERN = r"\b(Mr|Mrs|Ms|Dr|Prof|Inc|Corp|Ltd|Co|Jr|Sr|vs|etc|approx|est|vol|avg|no)\."
SENT_END_RE = re.compile(
    r"(?<=[.!?])"
    r"\s+"
    r"(?=[A-Z\"])"
)

def split_into_sentences(text: str) -> list[str]:
    protected = re.sub(ABBREVS_PATTERN, r"\1<DOT>", text)
    parts = SENT_END_RE.split(protected)
    return [s.replace("<DOT>", ".").strip() for s in parts if len(s.strip()) >= 15]


def make_chunk_hash(content: str, entity: str, date: str) -> str:
    raw = f"{content}|{entity}|{date}"
    return hashlib.sha256(raw.encode()).hexdigest()


def chunk_with_sentence_window(doc: FinancialDoc, window_size: int = 2) -> Generator[Chunk, None, None]:
    if doc.source in ("earnings", "transcript"):
        section_key = doc.meta.get("section", "full")
        
        yield Chunk(
            content=doc.body,
            window_text=doc.body,
            doc_title=doc.title,
            entity=doc.entity,
            entity_type=doc.entity_type,
            date=doc.date,
            source=doc.source,
            chunk_hash=make_chunk_hash(section_key, doc.entity, doc.date),
            meta=doc.meta,
        )
        return

    sentences = split_into_sentences(doc.body)
    if not sentences:
        return

    for i, sentence in enumerate(sentences):
        start = max(0, i - window_size)
        end   = min(len(sentences), i + window_size + 1)
        window = " ".join(sentences[start:end])

        yield Chunk(
            content=sentence,
            window_text=window,
            doc_title=doc.title,
            entity=doc.entity,
            entity_type=doc.entity_type,
            date=doc.date,
            source=doc.source,
            chunk_hash=make_chunk_hash(sentence, doc.entity, doc.date),
            meta=doc.meta,
        )


EMBED_BATCH_SIZE = 64
DB_EMBEDDING_DIM = 2048


def validate_embedding_dim(embedding: list[float], target_dim: int = DB_EMBEDDING_DIM) -> list[float]:
    current_dim = len(embedding)
    if current_dim == target_dim:
        return embedding

    raise ValueError(
        f"Embedding dimension mismatch: got {current_dim}, expected {target_dim}. "
        "Update DB/model config and re-embed."
    )

def embed_chunks(chunks: list[Chunk]) -> list[tuple[Chunk, list[float]]]:
    if not chunks:
        return []

    if not getattr(Settings, "embed_model", None):
        raise RuntimeError("Embedding model is not initialized. Call init_llms() first.")

    results: list[tuple[Chunk, list[float]]] = []
    for i in range(0, len(chunks), EMBED_BATCH_SIZE):
        batch = chunks[i : i + EMBED_BATCH_SIZE]
        texts = [chunk.content for chunk in batch]

        if hasattr(Settings.embed_model, "get_text_embedding_batch"):
            embeddings = Settings.embed_model.get_text_embedding_batch(texts)
        else:
            embeddings = [Settings.embed_model.get_text_embedding(text) for text in texts]

        for chunk, embedding in zip(batch, embeddings):
            results.append((chunk, embedding))

    return results


def store_in_db(embedded_chunks: list[tuple[Chunk, list[float]]]) -> int:
    if not embedded_chunks:
        return 0

    rows = []
    for chunk, embedding in embedded_chunks:
        report_date = None
        if chunk.date:
            try:
                report_date = datetime.strptime(chunk.date[:10], "%Y-%m-%d").date()
            except ValueError:
                logger.warning("Invalid date for chunk %s: %s", chunk.chunk_hash, chunk.date)

        rows.append(
            {
                "chunk_hash": chunk.chunk_hash,
                "document_title": chunk.doc_title,
                "content": chunk.content,
                "window_text": chunk.window_text,
                "embedding": validate_embedding_dim(embedding),
                "entity": chunk.entity,
                "entity_type": chunk.entity_type,
                "source": chunk.source,
                "report_date": report_date,
                "metadata": chunk.meta or {},
            }
        )

    stmt = insert(financial_documents).values(rows)
    stmt = stmt.on_conflict_do_nothing(index_elements=["chunk_hash"])

    with engine.begin() as conn:
        result = conn.execute(stmt)
        return result.rowcount or 0