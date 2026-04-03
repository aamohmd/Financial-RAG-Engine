CREATE TABLE IF NOT EXISTS financial_documents (
    id SERIAL PRIMARY KEY,
    document_title VARCHAR(255) NOT NULL,
    content TEXT NOT NULL,
    company_ticker VARCHAR(10),
    report_date DATE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);