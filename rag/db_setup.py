import os
from sqlalchemy import create_engine, MetaData, Table, Column, Integer, String, Text, Date, DateTime, func, text
from pgvector.sqlalchemy import VECTOR

# Database Connection details
DB_USER = "myuser"
DB_PASS = "mypassword"
DB_HOST = os.getenv("DB_HOST", "db")
DB_PORT = "5432"
DB_NAME = "mydatabase"

DATABASE_URL = f"postgresql://{DB_USER}:{DB_PASS}@{DB_HOST}:{DB_PORT}/{DB_NAME}"

# 1. Initialize Engine and Metadata
engine = create_engine(DATABASE_URL)
metadata = MetaData()

# 2. Define the Table Schema (matches db/init.sql)
financial_documents = Table(
    "financial_documents",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("document_title", String(255), nullable=False),
    Column("content", Text, nullable=False),
    Column("embedding", VECTOR(4096)), # pgvector type
    Column("company_ticker", String(10)),
    Column("report_date", Date),
    Column("created_at", DateTime, server_default=func.now()),
)

def init_db():
    """Initializes the vector extension and creates the table if it doesn't exist."""
    try:
        with engine.connect() as conn:
            # Enable pgvector extension
            conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector;"))
            conn.commit()
            
            # Create table
            metadata.create_all(engine)
            print("Database initialized successfully with SQLAlchemy (pgvector enabled).")
            
    except Exception as e:
        print(f"Error initializing database: {e}")
        raise e
