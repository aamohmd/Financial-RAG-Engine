from llama_index.core import Settings
from llama_index.core import PromptTemplate

# A specialized prompt to rewrite the user's query for financial RAG
REWRITE_PROMPT_TMPL = (
    "You are an expert financial search assistant. Your task is to rewrite the "
    "following user question to be more precise, comprehensive, and optimized "
    "for a vector database search over financial documents (like 10-Ks, earnings transcripts, etc.). "
    "Include relevant synonyms and expand acronyms where it makes sense.\n\n"
    "DO NOT answer the question. Only output the rewritten query.\n\n"
    "Original Query: {query_str}\n"
    "Rewritten Query:"
)

def rewrite_query(original_query: str) -> str:
    prompt = PromptTemplate(REWRITE_PROMPT_TMPL)
    response = Settings.llm.predict(prompt, query_str=original_query)
    rewritten = response.strip().strip('"').strip("'")
    
    return rewritten