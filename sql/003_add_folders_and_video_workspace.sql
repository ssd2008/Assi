BEGIN;

CREATE TABLE IF NOT EXISTS folders (
    id UUID PRIMARY KEY,
    name VARCHAR(120) NOT NULL,
    is_system BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT folders_name_check CHECK (BTRIM(name) <> '')
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_folders_name_unique ON folders (LOWER(name));

INSERT INTO folders (id, name, is_system)
VALUES ('00000000-0000-0000-0000-000000000001', 'Без папки', TRUE)
ON CONFLICT (id) DO UPDATE SET name = EXCLUDED.name, is_system = TRUE;

ALTER TABLE documents ADD COLUMN IF NOT EXISTS folder_id UUID;
UPDATE documents
SET folder_id = '00000000-0000-0000-0000-000000000001'
WHERE folder_id IS NULL;
ALTER TABLE documents ALTER COLUMN folder_id SET NOT NULL;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'documents_folder_id_fkey'
    ) THEN
        ALTER TABLE documents
            ADD CONSTRAINT documents_folder_id_fkey
            FOREIGN KEY (folder_id) REFERENCES folders(id);
    END IF;
END;
$$;

DROP INDEX IF EXISTS idx_documents_specialty;
ALTER TABLE documents DROP COLUMN IF EXISTS specialty;
CREATE INDEX IF NOT EXISTS idx_documents_folder_id ON documents (folder_id);

-- Qdrant payload/collection schema changed. Existing extracted content stays in PostgreSQL,
-- but every legacy document must be reindexed into document_chunks_v2.
UPDATE documents
SET status = 'uploaded', chunk_count = 0, error_message = NULL;

DROP TRIGGER IF EXISTS folders_set_updated_at ON folders;
CREATE TRIGGER folders_set_updated_at BEFORE UPDATE ON folders
FOR EACH ROW EXECUTE FUNCTION set_row_updated_at();

COMMIT;
