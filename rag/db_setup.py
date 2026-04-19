import os
from sqlalchemy import create_engine, MetaData, Table, Column, Integer, String, Text, Date, DateTime, func, text
from sqlalchemy.dialects.postgresql import JSONB
from pgvector.sqlalchemy import VECTOR

DB_USER = os.getenv("DB_USER")
DB_PASS = os.getenv("DB_PASSWORD")
DB_HOST = os.getenv("DB_HOST")
DB_PORT = os.getenv("DB_PORT")
DB_NAME = os.getenv("DB_NAME")

DATABASE_URL = f"postgresql://{DB_USER}:{DB_PASS}@{DB_HOST}:{DB_PORT}/{DB_NAME}"

engine = create_engine(DATABASE_URL)
metadata = MetaData()

financial_documents = Table(
    "financial_documents",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("chunk_hash", String(64), unique=True, nullable=False),
    Column("document_title", String(255), nullable=False),
    Column("content", Text, nullable=False),                         # sentence (embedded)
    Column("window_text", Text),                                     # ±2 surrounding sentences
    Column("embedding", VECTOR(4096)),
    Column("entity", String(20), index=True),                        # "GDP", "CPIAUCSL", "AAPL"
    Column("entity_type", String(20), index=True),                   # "macro", "equity", "rate", "index"
    Column("source", String(20), index=True),                        # "fred", "bea", "sec", etc.
    Column("report_date", Date, index=True),
    Column("metadata", JSONB, server_default="{}"),
    Column("created_at", DateTime, server_default=func.now()),
)

def init_db():
    """Initializes extensions, creates tables, and sets up BM25 index."""
    try:
        with engine.connect() as conn:
            conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector;"))
            conn.commit()
            
            metadata.create_all(engine)

            conn.execute(text("""
                CREATE INDEX IF NOT EXISTS documents_bm25
                ON financial_documents
                USING bm25 (id, content)
                WITH (key_field = 'id');
            """))
            conn.commit()
            print("Database initialized (pgvector + ParadeDB BM25).")
            
    except Exception as e:
        print(f"Error initializing database: {e}")
        raise e
