from llama_index.core import Settings, PromptTemplate, QueryBundle
from llama_index.core.indices.query.query_transform import HyDEQueryTransform
from llama_index.core.query_engine import TransformQueryEngine

HYDE_PROMPT = """You are an expert financial analyst. Generate a passage 
that would appear in an SEC 10-K or earnings transcript 
that directly answers this question. Use precise financial 
terminology, include realistic figures, mention fiscal periods, 
and write in the formal style of investor relations documents.

Question: {question}

Hypothetical passage:"""


def generate_hypothetical_document(user_query: str):
    prompt = PromptTemplate(HYDE_PROMPT)
    hypothetical_document = Settings.llm.predict(prompt, question=user_query)
    return hypothetical_document

def get_hyde_query_bundle(user_query: str):
    hypothetical_doc = generate_hypothetical_document(user_query)
    doc_embedding = Settings.embed_model.get_text_embedding(hypothetical_doc)
    return QueryBundle(
        query_str=user_query,
        custom_embedding_strs=[hypothetical_doc],
        embedding=doc_embedding
    )