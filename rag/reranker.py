import logging
from llm_setup import get_reranker

logger = logging.getLogger(__name__)


def to_dict(row) -> dict:
    if isinstance(row, dict):
        return dict(row)

    row_keys = getattr(row, "keys", None)
    if callable(row_keys):
        try:
            keys = list(row_keys())
            try:
                return {key: row[key] for key in keys}
            except Exception:
                return {key: getattr(row, key) for key in keys}
        except Exception:
            pass

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

    reranker = get_reranker()
    if reranker is None:
        return rows[:final_k]

    documents = [format_row(row) for row in rows]
    pairs = [[question, doc] for doc in documents]

    try:
        scores = reranker.predict(pairs)
    except Exception as e:
        logger.error("Reranker model call failed: %s", e)
        return rows[:final_k]

    if hasattr(scores, "tolist"):
        scores = scores.tolist()

    scored = []
    for i, score in enumerate(scores):
        score_value = score[0] if isinstance(score, (list, tuple)) else score
        scored.append({"index": i, "score": float(score_value)})

    scored.sort(key=lambda x: x["score"], reverse=True)

    top = []
    for item in scored[:final_k]:
        row_dict = to_dict(rows[item["index"]])
        row_dict["rerank_score"] = item["score"]
        top.append(row_dict)

    return top