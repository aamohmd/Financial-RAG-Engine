from llama_index.core import Settings
from llama_index.core import PromptTemplate

# A specialized prompt to rewrite the user's query for financial RAG
REWRITE_PROMPT_TMPL = (
    "You are an expert search assistant. Rewrite the user's question into a focused, optimized query "
    "for a vector database search over financial documents (10-Ks, earnings transcripts).\n\n"
    "RULES:\n"
    "- Output ONLY the rewritten query string. Nothing else.\n"
    "- Keep it extremely CONCISE (maximum 10 words). Extract the core entities, tickers, metrics, and years.\n"
    "- DO NOT spam endless synonyms or variations.\n\n"
    "Original Query: {query_str}\n"
    "Rewritten Query:"
)

def rewrite_query(original_query: str) -> str:
    prompt = PromptTemplate(REWRITE_PROMPT_TMPL)
    response = Settings.llm.predict(prompt, query_str=original_query)
    rewritten = response.strip().strip('"').strip("'")
    
    return rewritten