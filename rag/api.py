from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
import traceback
import os
import logging
from pydantic import BaseModel, Field
from typing import Literal

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(name)-25s | %(levelname)-7s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)

from llm_setup import init_llms
from db_setup import init_db
from ingestion.ingestion import orchestrate_ingestion
from query_rewriter import rewrite_query
from hyde import get_hyde_query_bundle
from hybrid_search import get_hybrid_retriever
from reranker import rerank_results
from synthesis import generate_financial_answer
from contextual_query import build_contextual_query

@asynccontextmanager
async def lifespan(app: FastAPI):
    init_llms()
    init_db()
    yield

app = FastAPI(lifespan=lifespan)
logger = logging.getLogger(__name__)

frontend_origins = os.getenv(
    "FRONTEND_ORIGINS",
    "http://localhost:5173,http://127.0.0.1:5173",
)
allowed_origins = [origin.strip() for origin in frontend_origins.split(",") if origin.strip()]

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class ChatTurn(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(..., max_length=5000)

class QuestionRequest(BaseModel):
    question: str = Field(..., min_length=1, max_length=2000)
    history: list[ChatTurn] = Field(default_factory=list, max_length=20)

class QuestionResponse(BaseModel):
    answer: str
    metadata: dict | None = None


@app.get("/health")
async def health_check():
    return {"status": "ok"}



@app.post("/rag/ingest")
async def ingest_endpoint(source: str | None = None):
    try:
        stats = orchestrate_ingestion(source)
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
        contextual_query = build_contextual_query(request.question, request.history)
        rewritten = rewrite_query(contextual_query)
        hyde_bundle = get_hyde_query_bundle(rewritten)
        retrieved_rows = get_hybrid_retriever(hyde_bundle, top_k=20)
        reranked_dicts = rerank_results(contextual_query, retrieved_rows, final_k=6)
        answer = generate_financial_answer(request.question, reranked_dicts, history=request.history)
        
        return QuestionResponse(
            answer=answer,
            metadata={
                "rewritten_query": rewritten,
                "sources_count": len(reranked_dicts),
                "history_turns_used": min(len(request.history), 6),
            }
        )
    except Exception as e:
        trace = traceback.format_exc()
        raise HTTPException(status_code=500, detail=f"Query failed: {str(e)}\n{trace}")