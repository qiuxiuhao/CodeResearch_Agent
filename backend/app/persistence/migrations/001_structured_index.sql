BEGIN IMMEDIATE;

CREATE TABLE IF NOT EXISTS repositories (
    repo_id TEXT PRIMARY KEY,
    identity_mode TEXT NOT NULL CHECK(identity_mode IN ('explicit', 'task_scoped')),
    repository_key TEXT,
    display_name TEXT,
    active_version_id TEXT REFERENCES index_versions(index_version_id) ON DELETE SET NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    CHECK(
        (identity_mode = 'explicit' AND repository_key IS NOT NULL)
        OR (identity_mode = 'task_scoped' AND repository_key IS NULL)
    )
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_repositories_explicit_key
ON repositories(repository_key)
WHERE identity_mode = 'explicit' AND repository_key IS NOT NULL;

CREATE TABLE IF NOT EXISTS index_versions (
    index_version_id TEXT PRIMARY KEY,
    repo_id TEXT NOT NULL REFERENCES repositories(repo_id) ON DELETE CASCADE,
    sequence INTEGER NOT NULL,
    input_hash TEXT NOT NULL,
    status TEXT NOT NULL CHECK(status IN ('building', 'ready', 'active', 'superseded', 'failed')),
    retry_count INTEGER NOT NULL DEFAULT 0,
    lease_owner TEXT,
    lease_expires_at TEXT,
    error_json TEXT,
    created_at TEXT NOT NULL,
    ready_at TEXT,
    activated_at TEXT,
    failed_at TEXT,
    UNIQUE(repo_id, sequence),
    UNIQUE(repo_id, input_hash)
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_index_versions_active_repo
ON index_versions(repo_id) WHERE status = 'active';

CREATE UNIQUE INDEX IF NOT EXISTS uq_index_versions_building_repo
ON index_versions(repo_id) WHERE status IN ('building', 'ready');

CREATE TABLE IF NOT EXISTS indexed_files (
    index_version_id TEXT NOT NULL REFERENCES index_versions(index_version_id) ON DELETE CASCADE,
    path TEXT NOT NULL,
    kind TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    size_bytes INTEGER NOT NULL,
    parse_status TEXT NOT NULL,
    entity_count INTEGER NOT NULL,
    edge_count INTEGER NOT NULL,
    chunk_count INTEGER NOT NULL,
    errors_json TEXT NOT NULL,
    PRIMARY KEY(index_version_id, path)
);

CREATE TABLE IF NOT EXISTS code_entities (
    index_version_id TEXT NOT NULL REFERENCES index_versions(index_version_id) ON DELETE CASCADE,
    entity_id TEXT NOT NULL,
    repo_id TEXT NOT NULL,
    entity_type TEXT NOT NULL,
    path TEXT NOT NULL,
    name TEXT NOT NULL,
    qualified_name TEXT NOT NULL,
    module_name TEXT,
    parent_id TEXT,
    start_line INTEGER,
    end_line INTEGER,
    signature TEXT,
    source_code TEXT,
    docstring TEXT,
    content_hash TEXT NOT NULL,
    evidence_refs_json TEXT NOT NULL,
    metadata_json TEXT NOT NULL,
    PRIMARY KEY(index_version_id, entity_id)
);

CREATE TABLE IF NOT EXISTS paper_entities (
    index_version_id TEXT NOT NULL REFERENCES index_versions(index_version_id) ON DELETE CASCADE,
    entity_id TEXT NOT NULL,
    paper_id TEXT NOT NULL,
    entity_type TEXT NOT NULL,
    title TEXT,
    text TEXT NOT NULL,
    page_number INTEGER,
    bbox_json TEXT,
    figure_path TEXT,
    keywords_json TEXT NOT NULL,
    module_names_json TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    evidence_refs_json TEXT NOT NULL,
    metadata_json TEXT NOT NULL,
    PRIMARY KEY(index_version_id, entity_id)
);

CREATE TABLE IF NOT EXISTS knowledge_edges (
    index_version_id TEXT NOT NULL REFERENCES index_versions(index_version_id) ON DELETE CASCADE,
    edge_id TEXT NOT NULL,
    repo_id TEXT NOT NULL,
    source_id TEXT NOT NULL,
    target_id TEXT,
    edge_type TEXT NOT NULL,
    confidence REAL NOT NULL,
    resolution_type TEXT NOT NULL,
    unresolved_symbol TEXT,
    evidence_refs_json TEXT NOT NULL,
    metadata_json TEXT NOT NULL,
    PRIMARY KEY(index_version_id, edge_id)
);

CREATE TABLE IF NOT EXISTS evidence_refs (
    index_version_id TEXT NOT NULL REFERENCES index_versions(index_version_id) ON DELETE CASCADE,
    evidence_id TEXT NOT NULL,
    source_type TEXT NOT NULL,
    entity_id TEXT,
    file_path TEXT,
    start_line INTEGER,
    end_line INTEGER,
    paper_id TEXT,
    page_number INTEGER,
    figure_id TEXT,
    bbox_json TEXT,
    content_hash TEXT,
    PRIMARY KEY(index_version_id, evidence_id)
);

CREATE TABLE IF NOT EXISTS symbol_chunks (
    index_version_id TEXT NOT NULL REFERENCES index_versions(index_version_id) ON DELETE CASCADE,
    chunk_id TEXT NOT NULL,
    repo_id TEXT NOT NULL,
    entity_id TEXT NOT NULL,
    entity_kind TEXT NOT NULL,
    chunk_type TEXT NOT NULL,
    path TEXT,
    page_number INTEGER,
    start_line INTEGER,
    end_line INTEGER,
    ordinal INTEGER NOT NULL,
    text TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    char_count INTEGER NOT NULL,
    metadata_json TEXT NOT NULL,
    PRIMARY KEY(index_version_id, chunk_id)
);

CREATE INDEX IF NOT EXISTS idx_indexed_files_path ON indexed_files(path);
CREATE INDEX IF NOT EXISTS idx_indexed_files_hash ON indexed_files(content_hash);
CREATE INDEX IF NOT EXISTS idx_indexed_files_status ON indexed_files(parse_status);
CREATE INDEX IF NOT EXISTS idx_code_entities_path ON code_entities(repo_id, path);
CREATE INDEX IF NOT EXISTS idx_code_entities_qualified ON code_entities(repo_id, qualified_name);
CREATE INDEX IF NOT EXISTS idx_code_entities_type ON code_entities(repo_id, entity_type);
CREATE INDEX IF NOT EXISTS idx_code_entities_hash ON code_entities(content_hash);
CREATE INDEX IF NOT EXISTS idx_paper_entities_page ON paper_entities(paper_id, page_number);
CREATE INDEX IF NOT EXISTS idx_paper_entities_type ON paper_entities(paper_id, entity_type);
CREATE INDEX IF NOT EXISTS idx_edges_source ON knowledge_edges(source_id, edge_type);
CREATE INDEX IF NOT EXISTS idx_edges_target ON knowledge_edges(target_id, edge_type);
CREATE INDEX IF NOT EXISTS idx_edges_resolution ON knowledge_edges(resolution_type);
CREATE INDEX IF NOT EXISTS idx_evidence_file ON evidence_refs(file_path, start_line);
CREATE INDEX IF NOT EXISTS idx_evidence_paper ON evidence_refs(paper_id, page_number);
CREATE INDEX IF NOT EXISTS idx_chunks_entity ON symbol_chunks(entity_id, chunk_type);
CREATE INDEX IF NOT EXISTS idx_chunks_path ON symbol_chunks(path);
CREATE INDEX IF NOT EXISTS idx_chunks_hash ON symbol_chunks(content_hash);

PRAGMA user_version = 1;
COMMIT;
