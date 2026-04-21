import os
import logging
import requests

logger = logging.getLogger(__name__)

HF_API_URL = "https://router.huggingface.co/hf-inference/models"
HF_API_KEY = os.getenv("HF_API_KEY", "")
RERANKER_MODEL = os.getenv("RERANKER_MODEL", "BAAI/bge-reranker-v2-m3")


def hf_rerank(query: str, documents: list[str]) -> list[float]:
    resp = requests.post(
        f"{HF_API_URL}/{RERANKER_MODEL}",
        headers={"Authorization": f"Bearer {HF_API_KEY}"},
        json={"inputs": {"source_sentence": query, "sentences": documents}},
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()


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
        lines.append(
            f"beat_miss={metadata.get('beat_miss', '?')} "
            f"guidance={metadata.get('guidance_tone', '?')}"
        )
    elif source == "sec":
        lines.append(
            f"form={metadata.get('form_type', '?')} "
            f"period={metadata.get('fiscal_period', '?')} "
            f"section={metadata.get('section', '?')}"
        )
    elif source == "fred":
        lines.append(
            f"value={metadata.get('latest_value', '?')} "
            f"unit={metadata.get('unit', '?')}"
        )
    elif source == "news":
        lines.append(
            f"event={metadata.get('event_type', '?')} "
            f"sentiment={metadata.get('sentiment_tone', '?')}"
        )

    lines.append(f"preview={text}...")
    return "\n".join(lines)


def rerank_results(question: str, rows: list, final_k: int = 5) -> list:
    if not rows:
        return []

    rows = list(rows)
    if final_k <= 0:
        return []

    if len(rows) <= final_k:
        return rows

    if not HF_API_KEY:
        logger.warning("HF_API_KEY not set — skipping reranker, using retrieval order")
        return [to_dict(r) for r in rows[:final_k]]

    documents = [format_row(row) for row in rows]

    try:
        scores = hf_rerank(question, documents)
    except Exception as e:
        logger.error("Reranker API failed: %s — using retrieval order", e)
        return [to_dict(r) for r in rows[:final_k]]

    if not isinstance(scores, list) or len(scores) != len(rows):
        logger.error("Reranker returned unexpected shape — using retrieval order")
        return [to_dict(r) for r in rows[:final_k]]

    scored = sorted(
        enumerate(scores),
        key=lambda x: float(x[1]),
        reverse=True,
    )

    top = []
    for idx, score in scored[:final_k]:
        row_dict = to_dict(rows[idx])
        row_dict["rerank_score"] = float(score)
        top.append(row_dict)

    return top