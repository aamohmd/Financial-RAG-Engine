import os
import logging
from rerankers import Reranker

logger = logging.getLogger(__name__)
ranker = Reranker('flashrank')

def to_dict(row) -> dict:
    if isinstance(row, dict):
        return row
    asdict_fn = getattr(row, "_asdict", None)
    if callable(asdict_fn):
        return asdict_fn()
    row_keys = getattr(row, "keys", None)
    if row_keys:
        keys = list(row_keys() if callable(row_keys) else row_keys)
        try:
            return {key: row[key] for key in keys}
        except Exception:
            return {key: getattr(row, key) for key in keys}
    return {"value": str(row)}

def format_row(row) -> str:
    m = to_dict(row)
    source = m.get("source", "?")
    entity = m.get("entity", "?")
    entity_type = m.get("entity_type", "?")
    report_date = m.get("report_date", "?")
    title = (m.get("document_title") or "")[:120]
    metadata = m.get("metadata") or {}

    if not isinstance(metadata, dict):
        metadata = {}

    text = (m.get("window_text") or m.get("content") or "")[:1500].replace("\n", " ")
    lines = [
        f"source={source} entity={entity} type={entity_type}",
        f"date={report_date}",
        f"title={title}",
    ]

    if source == "transcript":
        lines.append(f"beat_miss={metadata.get('beat_miss', '?')} guidance={metadata.get('guidance_tone', '?')}")
    elif source == "sec":
        lines.append(f"form={metadata.get('form_type', '?')} period={metadata.get('fiscal_period', '?')} section={metadata.get('section', '?')}")
    elif source == "fred":
        lines.append(f"value={metadata.get('latest_value', '?')} unit={metadata.get('unit', '?')}")
    elif source == "news":
        lines.append(f"event={metadata.get('event_type', '?')} sentiment={metadata.get('sentiment_tone', '?')}")

    lines.append(f"preview={text}...")
    return "\n".join(lines)

def rerank_results(question: str, rows: list, final_k: int = 8) -> list:
    if not rows:
        return []

    logger.info(f"Reranking {len(rows)} documents avec FlashRank...")
    rows = list(rows)
    if final_k <= 0:
        return []

    if len(rows) <= final_k:
        return [dict(to_dict(r), rerank_score=1.0) for r in rows]

    documents = [format_row(row) for row in rows]
    try:
        results = ranker.rank(query=question, docs=documents)
        top_results = results.top_k(final_k)
        
        top = []
        for res in top_results:
            row_text = res.document.text if hasattr(res.document, 'text') else str(res.document)
            try:
                orig_idx = documents.index(row_text)
                row_dict = to_dict(rows[orig_idx])
                row_dict["rerank_score"] = float(res.score)
                top.append(row_dict)
            except ValueError:
                continue
        return top

    except Exception as e:
        logger.error(f"Reranking failed: {e}. Falling back to default order.")
        return [to_dict(r) for r in rows[:final_k]]