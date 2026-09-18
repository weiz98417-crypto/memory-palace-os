-- Install pgvector as the PostgreSQL bootstrap superuser. The application
-- user owns tables but must not need superuser privileges at runtime.
CREATE EXTENSION IF NOT EXISTS vector;
