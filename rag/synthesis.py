from llama_index.core import Settings
from llama_index.core import PromptTemplate

SYNTHESIS_PROMPT_TMPL = (
    "You are a Senior Investment Analyst. Answer the following question based ONLY on the "
    "provided context from SEC filings, earnings transcripts, and financial news.\n\n"
    "RULES:\n"
    "- Use a professional, objective, and analytical tone.\n"
    "- Use conversation history only to resolve references like pronouns or follow-up phrasing.\n"
    "- If the question asks for a specific figure (e.g., revenue, guidance), provide it and cite the source.\n"
    "- Mention specific fiscal periods (e.g., 'In Q4 2025...') and entity names.\n"
    "- Prioritize 'window_text' context for detailed narratives.\n"
    "- If the provided context does not contain enough information to answer, state what is missing.\n"
    "- Structure your answer with clear bullet points if appropriate.\n\n"
    "CONVERSATION HISTORY:\n"
    "{history_str}\n\n"
    "CONTEXT:\n"
    "{context_str}\n\n"
    "QUESTION: {query_str}\n\n"
    "EXPERT ANALYSIS:"
)


def _format_history(history: list | None, max_turns: int = 6) -> str:
    if not history:
        return "None"

    recent_turns = history[-max_turns:]
    lines = []

    for turn in recent_turns:
        if isinstance(turn, dict):
            role = str(turn.get("role", "")).lower().strip()
            content = str(turn.get("content", "")).strip()
        else:
            role = str(getattr(turn, "role", "")).lower().strip()
            content = str(getattr(turn, "content", "")).strip()

        if role not in {"user", "assistant"} or not content:
            continue

        content = " ".join(content.split())
        if len(content) > 320:
            content = f"{content[:317]}..."

        speaker = "User" if role == "user" else "Assistant"
        lines.append(f"{speaker}: {content}")

    return "\n".join(lines) if lines else "None"


def generate_financial_answer(question: str, reranked_results: list, history: list | None = None) -> str:
    if not reranked_results:
        return "No relevant financial documents were found to answer this question."

    context_parts = []
    for i, res in enumerate(reranked_results, 1):
        text = res.get("window_text") or res.get("content") or ""
        source = res.get("source", "unknown")
        entity = res.get("entity", "unknown")
        date = res.get("report_date", "unknown")
        
        context_parts.append(
            f"--- Source {i} [{source.upper()} | {entity} | {date}] ---\n{text}"
        )
    
    context_str = "\n\n".join(context_parts)
    history_str = _format_history(history)
    
    prompt = PromptTemplate(SYNTHESIS_PROMPT_TMPL)
    answer = Settings.llm.predict(
        prompt,
        context_str=context_str,
        history_str=history_str,
        query_str=question,
    )
    
    return answer.strip()
