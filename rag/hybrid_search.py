from sqlalchemy import select, cast, func, text, Float
from pgvector.sqlalchemy import HALFVEC, HalfVector
from db_setup import engine, financial_documents

def vector_search(embedding, top_k: int = 5):
    distance = (
        financial_documents.c.embedding.op("<=>")(HalfVector(embedding))
    ).cast(Float).label("distance")

    stmt = (
        select(
            financial_documents.c.id,
            financial_documents.c.content,
            distance,
        )
        .order_by(distance)
        .limit(top_k)
    )

    with engine.connect() as conn:
        return conn.execute(stmt).fetchall()

def keyword_search(query: str, top_k: int = 5):
    score = func.paradedb.score(financial_documents.c.id).label("score")

    stmt = (
        select(
            financial_documents.c.id,
            financial_documents.c.content,
            score,
        )
        .where(
            financial_documents.c.content.op("@@@")(query)
        )
        .order_by(score.desc())
        .limit(top_k)
    )

    with engine.connect() as conn:
        return conn.execute(stmt).fetchall()

RRF_K = 60

def apply_rrf(vector_results, keyword_results, top_k: int = 5):
    ranks = {}
    for results in (vector_results, keyword_results):
        for rank, row in enumerate(results, 1):
            ranks.setdefault(row.id, []).append(rank)

    scored = [
        (doc_id, sum(1 / (RRF_K + r) for r in doc_ranks))
        for doc_id, doc_ranks in ranks.items()
    ]
    scored.sort(key=lambda x: x[1], reverse=True)
    return scored[:top_k]


def get_hybrid_retriever(query_bundle, top_k: int = 5):
    embedding = query_bundle.embedding
    if hasattr(embedding, "tolist"):
        embedding = embedding.tolist()

    candidate_k = top_k * 3
    v_results = vector_search(embedding, top_k=candidate_k)
    k_results = keyword_search(query_bundle.query_str, top_k=candidate_k)

    rrf_results = apply_rrf(v_results, k_results, top_k=top_k)
    top_ids = [doc_id for doc_id, _ in rrf_results]

    with engine.connect() as conn:
        rows = conn.execute(
            select(financial_documents).where(financial_documents.c.id.in_(top_ids))
        ).fetchall()
    order = {doc_id: i for i, doc_id in enumerate(top_ids)}
    return sorted(rows, key=lambda row: order[row.id])