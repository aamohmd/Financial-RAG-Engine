from fastapi import FastAPI
from pydantic import BaseModel
from llm_setup import init_settings
from query_rewriter import rewrite_query

app = FastAPI()

class QuestionRequest(BaseModel):
    question: str

class QuestionResponse(BaseModel):
    answer: str

def startup_event():
    init_settings()

@app.post("/rag/query", response_model=QuestionResponse)
async def query_endpoint(request: QuestionRequest):
    return 

@app.post("/rag/ingest")
async def ingest_endpoint():
    return "nice"

@app.post("/test")
async def rewrite():
    startup_event()
    rewriten = rewrite_query("what is?")
    return rewriten