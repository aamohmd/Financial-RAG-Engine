from fastapi import FastAPI, HTTPException
import traceback
from pydantic import BaseModel

from llm_setup import init_llms
from db_setup import init_db
from ingestion.ingestion import orchestrate_ingestion
from query_rewriter import rewrite_query
from hyde import get_hyde_query_bundle
from hybrid_search import get_hybrid_retriever
from reranker import rerank_results
from synthesis import generate_financial_answer

app = FastAPI()

class QuestionRequest(BaseModel):
    question: str

class QuestionResponse(BaseModel):
    answer: str
    metadata: dict | None = None


@app.on_event("startup")
def startup_event():
    init_llms()
    init_db()


@app.post("/rag/ingest")
async def ingest_endpoint():
    try:
        stats = orchestrate_ingestion()
        return {
            "status": "success",
            "ingested_chunks": stats
        }
    except Exception as e:
        logger_error = traceback.format_exc()
        raise HTTPException(status_code=500, detail=f"Ingestion failed: {str(e)}\n{logger_error}")


@app.post("/rag/query", response_model=QuestionResponse)
async def query_endpoint(request: QuestionRequest):
    try:
        rewritten = rewrite_query(request.question)
        hyde_bundle = get_hyde_query_bundle(rewritten)
        retrieved_rows = get_hybrid_retriever(hyde_bundle, top_k=20)
        reranked_dicts = rerank_results(request.question, retrieved_rows, final_k=6)
        answer = generate_financial_answer(request.question, reranked_dicts)
        
        return QuestionResponse(
            answer=answer,
            metadata={
                "rewritten_query": rewritten,
                "sources_count": len(reranked_dicts)
            }
        )
    except Exception as e:
        trace = traceback.format_exc()
        raise HTTPException(status_code=500, detail=f"Query failed: {str(e)}\n{trace}")