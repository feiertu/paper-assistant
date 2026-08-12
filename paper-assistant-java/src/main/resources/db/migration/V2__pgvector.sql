CREATE EXTENSION IF NOT EXISTS vector;

ALTER TABLE papers ADD COLUMN IF NOT EXISTS embedding vector(1024);

CREATE INDEX IF NOT EXISTS idx_papers_embedding ON papers
    USING ivfflat (embedding vector_cosine_ops)
    WITH (lists = 100);
