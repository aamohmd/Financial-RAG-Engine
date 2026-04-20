from llama_index.core import Settings
from llama_index.core import PromptTemplate

SYNTHESIS_PROMPT_TMPL = (
    "You are a Senior Investment Analyst. Answer the following question based ONLY on the "
    "provided context from SEC filings, earnings transcripts, and financial news.\n\n"
    "RULES:\n"
    "- Use a professional, objective, and analytical tone.\n"
    "- If the question asks for a specific figure (e.g., revenue, guidance), provide it and cite the source.\n"
    "- Mention specific fiscal periods (e.g., 'In Q4 2025...') and entity names.\n"
    "- Prioritize 'window_text' context for detailed narratives.\n"
    "- If the provided context does not contain enough information to answer, state what is missing.\n"
    "- Structure your answer with clear bullet points if appropriate.\n\n"
    "CONTEXT:\n"
    "{context_str}\n\n"
    "QUESTION: {query_str}\n\n"
    "EXPERT ANALYSIS:"
)

def generate_financial_answer(question: str, reranked_results: list) -> str:
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
    
    prompt = PromptTemplate(SYNTHESIS_PROMPT_TMPL)
    answer = Settings.llm.predict(prompt, context_str=context_str, query_str=question)
    
    return answer.strip()
