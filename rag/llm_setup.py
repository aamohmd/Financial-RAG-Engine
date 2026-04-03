
from llama_index.llms.openai_like import OpenAILike
from llama_index.embeddings.fastembed import FastEmbedEmbedding
from llama_index.core import Settings
from dotenv import load_dotenv
import os
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(PROJECT_ROOT / ".env")

def init_llms():
    groq_api_key = os.getenv("GROQ_API_KEY")
    groq_api_base = os.getenv("GROQ_API_BASE")
    groq_model = os.getenv("GROQ_MODEL")
    embedding_model = os.getenv("EMBEDDING_MODEL")
    missing = [
        name
        for name, value in {
            "GROQ_API_KEY": groq_api_key,
            "GROQ_API_BASE": groq_api_base,
            "GROQ_MODEL": groq_model,
            "EMBEDDING_MODEL": embedding_model,
        }.items()
        if not value
    ]
    if missing:
        raise ValueError(f"Missing required environment variables: {', '.join(missing)}")

    Settings.llm = OpenAILike(
        model=groq_model,
        api_base=groq_api_base,
        api_key=groq_api_key,
        context_window=128000,
        is_chat_model=True,
        is_function_calling_model=False,
    )


    Settings.embed_model = FastEmbedEmbedding(
        model_name=embedding_model
    )