from llama_index.llms.openai_like import OpenAILike
from llama_index.embeddings.fastembed import FastEmbedEmbedding
from llama_index.core import Settings
from dotenv import load_dotenv
import os
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(PROJECT_ROOT / ".env")

def init_llms():
    openrouter_api_key = os.getenv("OPENROUTER_API_KEY")
    openrouter_api_base = os.getenv("OPENROUTER_API_BASE")
    openrouter_model = os.getenv("OPENROUTER_MODEL")
    embedding_model = os.getenv("EMBEDDING_MODEL")
    missing = [
        name
        for name, value in {
            "OPENROUTER_API_KEY": openrouter_api_key,
            "OPENROUTER_API_BASE": openrouter_api_base,
            "OPENROUTER_MODEL": openrouter_model,
            "EMBEDDING_MODEL": embedding_model,
        }.items()
        if not value
    ]
    if missing:
        raise ValueError(f"Missing required environment variables: {', '.join(missing)}")

    Settings.llm = OpenAILike(
        model=openrouter_model,
        api_key=openrouter_api_key,
        api_base=openrouter_api_base,
        is_chat_model=True
    )


    Settings.embed_model = FastEmbedEmbedding(
        model_name=embedding_model
    )