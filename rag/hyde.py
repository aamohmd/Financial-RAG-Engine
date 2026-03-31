from llama_index.core import Settings, PromptTemplate, QueryBundle
from llama_index.core.indices.query.query_transform import HyDEQueryTransform
from llama_index.core.query_engine import TransformQueryEngine

HYDE_PROMPT = """You are a financial analyst writing excerpts from SEC filings, earnings call transcripts, and financial news reports.

Given the following question, generate a hypothetical passage that would appear in a real financial document and directly answer it. 

Rules:
- Write as if you are extracting text from an actual SEC 10-K, 10-Q, earnings press release, or financial news article
- Use precise financial language: include metrics (revenue, EPS, gross margin, EBITDA), fiscal periods (Q3 FY2024), and ticker symbols where relevant
- Be specific with numbers even if fabricated — the goal is embedding similarity, not factual accuracy
- Write 3-5 sentences max
- Do NOT include any preamble like "Here is a passage..." — output the passage only

Question: {question}

Hypothetical passage:"""


def generate_hypothetical_document(user_query: str):
    prompt = PromptTemplate(HYDE_PROMPT)
    hypothetical_document = Settings.llm.predict(prompt, question=user_query)
    return hypothetical_document

def get_hyde_query_bundle(user_query: str):
    hypothetical_doc = generate_hypothetical_document(user_query)
    return QueryBundle(
        query_str=user_query,
        custom_embedding_strs=[hypothetical_doc],
    )