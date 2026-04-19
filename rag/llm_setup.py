from llama_index.llms.openai_like import OpenAILike
from llama_index.core.embeddings import BaseEmbedding
import requests
from typing import List, Any
from llama_index.core import Settings
from dotenv import load_dotenv
import os
from pathlib import Path

class OpenRouterEmbedding(BaseEmbedding):
    model_name: str
    api_key: str

    def __init__(self, model_name: str, api_key: str, **kwargs: Any) -> None:
        super().__init__(model_name=model_name, api_key=api_key, **kwargs)

    def get_query_embedding(self, query: str) -> List[float]:
        return self.get_text_embedding(query)

    def get_text_embedding(self, text: str) -> List[float]:
        res = requests.post(
            "https://openrouter.ai/api/v1/embeddings",
            headers={"Authorization": f"Bearer {self.api_key}"},
            json={"model": self.model_name, "input": [text]}
        ).json()
        if "data" not in res or not res["data"]:
            raise ValueError(f"OpenRouter Error: {res}")
        return res["data"][0]["embedding"]
    
    async def aget_query_embedding(self, query: str) -> List[float]:
        return self.get_query_embedding(query)
    
    async def aget_text_embedding(self, text: str) -> List[float]:
        return self.get_text_embedding(text)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(PROJECT_ROOT / ".env")

def init_llms():
    openrouter_api_key = os.getenv("OPENROUTER_API_KEY")
    openrouter_api_base = os.getenv("OPENROUTER_API_BASE")
    openrouter_model = os.getenv("OPENROUTER_MODEL")
    embed_model_name = os.getenv("EMBEDDING_MODEL")

    missing = [
        name
        for name, value in {
            "OPENROUTER_API_KEY": openrouter_api_key,
            "OPENROUTER_API_BASE": openrouter_api_base,
            "OPENROUTER_MODEL": openrouter_model,
            "EMBEDDING_MODEL": embed_model_name,
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

    Settings.embed_model = OpenRouterEmbedding(
        model_name=embed_model_name,
        api_key=openrouter_api_key
    )