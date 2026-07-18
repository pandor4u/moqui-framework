# Moqui Framework: Replace OpenSearch with PostgreSQL Search Backend

## Overview

Replace all OpenSearch/ElasticSearch dependencies in Moqui with a **configurable PostgreSQL-native implementation** using JSONB + tsvector + GIN indexes (and optionally `pg_textsearch` for BM25 ranking). The system remains backward-compatible — each `<cluster>` in `elastic-facade` config can be typed as `"postgres"` or `"elastic"`, so both backends coexist.

**Motivation:** Simplify the stack to a single database. As outlined in [It's 2026, Just Use Postgres](https://www.tigerdata.com/blog/its-2026-just-use-postgres), PostgreSQL extensions now use the same or better algorithms as specialized databases — `pg_textsearch` provides true BM25 ranking (the same algorithm behind ElasticSearch), `pg_trgm` handles fuzzy/typo-tolerant search, and native JSONB + GIN indexes match document store capabilities.

**Approach:** Implement a new `PostgresElasticClient` class that fulfills the existing `ElasticFacade.ElasticClient` interface (all ~35 methods) but talks to PostgreSQL instead of an ES REST API. This means **zero changes** to `SearchServices.xml`, `EntityDataFeed`, or any calling code — the swap is transparent at the facade level.

---

## Architecture

### Current Flow (OpenSearch)

```
Entity CUD → EntityDataFeed (tx sync) → DataDocument builder → SearchServices.index#DataDocuments
  → ElasticClient.bulkIndexDataDocument() → HTTP REST → OpenSearch cluster
  
Search query → SearchServices.search#DataDocuments → ElasticClient.search() → HTTP REST → OpenSearch
  → parse hits → return documentList

Logging → ElasticSearchLogger → queue → ElasticClient.bulkIndex() → HTTP REST → OpenSearch (moqui_logs)
HTTP Log → ElasticRequestLogFilter → queue → ElasticClient.bulkIndex() → HTTP REST → OpenSearch (moqui_http_log)
```

### New Flow (PostgreSQL)

```
Entity CUD → EntityDataFeed (tx sync) → DataDocument builder → SearchServices.index#DataDocuments
  → PostgresElasticClient.bulkIndexDataDocument() → SQL INSERT...ON CONFLICT → PostgreSQL (moqui_document table)

Search query → SearchServices.search#DataDocuments → PostgresElasticClient.search() 
  → ElasticQueryTranslator (ES DSL → SQL) → PostgreSQL full-text query → return documentList

Logging → PostgresSearchLogger → queue → batch INSERT → PostgreSQL (moqui_logs table)
HTTP Log → PostgresRequestLogFilter → queue → batch INSERT → PostgreSQL (moqui_http_log table)
```

### Key Architectural Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Integration point | Replace `ElasticClient` internals | Zero changes to SearchServices.xml or callers; maximum backward compatibility |
| Document storage | JSONB + tsvector columns | Supports real-time indexing (matches DataFeed push model), avoids materialized view refresh overhead |
| Configuration | Per-cluster `type` attribute | Allows mixed deployments during migration; `type="elastic"` (default) or `type="postgres"` |
| Query translation | ES DSL → SQL translator | Absorbs complexity so existing service code works without modification |
| Full-text ranking | `pg_textsearch` BM25 (optional), `tsvector`/`ts_rank_cd` (baseline) | BM25 gives ES-equivalent relevance; tsvector available on all Postgres installs |
| Logging entity group | Remap to standard SQL datasource | Simpler than building a custom entity datasource factory |

---

## Files Inventory

### Existing Files That Reference OpenSearch/ElasticSearch

| File | Role | Change Needed |
|------|------|---------------|
| `framework/src/main/java/org/moqui/context/ElasticFacade.java` | Public interface — `ElasticClient` with ~35 methods | **None** (interface stays) |
| `framework/src/main/groovy/org/moqui/impl/context/ElasticFacadeImpl.groovy` | Implementation — HTTP REST client to ES/OpenSearch | **Modify** init() to dispatch by `type` |
| `framework/src/main/groovy/org/moqui/impl/util/ElasticSearchLogger.groovy` | Log4j2 → ES bulk index (moqui_logs) | **None** (still used for `type="elastic"`) |
| `framework/src/main/groovy/org/moqui/impl/webapp/ElasticRequestLogFilter.groovy` | HTTP request → ES bulk index (moqui_http_log) | **None** (still used for `type="elastic"`) |
| `framework/src/main/groovy/org/moqui/impl/entity/elastic/ElasticDatasourceFactory.groovy` | ES as entity store for "logging" group | **None** (bypassed when postgres) |
| `framework/src/main/groovy/org/moqui/impl/entity/elastic/ElasticEntityFind.java` | Entity find → ES search | **None** |
| `framework/src/main/groovy/org/moqui/impl/entity/elastic/ElasticEntityValue.java` | Entity CRUD → ES | **None** |
| `framework/src/main/groovy/org/moqui/impl/entity/elastic/ElasticEntityListIterator.java` | Paginated ES iteration | **None** |
| `framework/src/main/groovy/org/moqui/impl/entity/EntityDataDocument.groovy` | Builds document Maps from entity data | **None** |
| `framework/src/main/groovy/org/moqui/impl/entity/EntityDataFeed.groovy` | Real-time entity CUD → DataFeed push | **None** |
| `framework/service/org/moqui/search/SearchServices.xml` | 7 search/index services | **None** (calls go through ElasticClient interface) |
| `framework/service/org/moqui/search/ElasticSearchServices.xml` | Backward-compat shim | **None** |
| `framework/src/main/resources/MoquiDefaultConf.xml` | elastic-facade + logging datasource config | **Modify** add postgres example |
| `framework/xsd/moqui-conf-3.xsd` | XSD schema for <cluster> element | **Modify** add `type` attribute |
| `framework/src/start/java/MoquiStart.java` | Auto-starts embedded OpenSearch | **None** (already skips if no runtime/opensearch dir) |
| `framework/src/main/groovy/org/moqui/impl/context/ExecutionContextFactoryImpl.groovy` | Initializes ElasticFacadeImpl | **None** |
| `docker/moqui-postgres-compose.yml` | Docker Compose with OpenSearch | **Create variant** without OpenSearch |

### New Files to Create

| File | Purpose |
|------|---------|
| `framework/src/main/groovy/org/moqui/impl/context/PostgresElasticClient.groovy` | `ElasticClient` implementation backed by PostgreSQL |
| `framework/src/main/groovy/org/moqui/impl/context/ElasticQueryTranslator.groovy` | Translates ES query DSL JSON to PostgreSQL SQL WHERE clauses |
| `framework/src/main/groovy/org/moqui/impl/util/PostgresSearchLogger.groovy` | Log4j2 events → PostgreSQL `moqui_logs` table |
| `framework/src/main/groovy/org/moqui/impl/webapp/PostgresRequestLogFilter.groovy` | HTTP request logging → PostgreSQL `moqui_http_log` table |
| `framework/entity/SearchEntities.xml` | Entity definitions for `moqui_document`, `moqui_search_index`, `moqui_logs`, `moqui_http_log` |
| `docker/moqui-postgres-only-compose.yml` | Docker Compose — Postgres + Moqui only, no OpenSearch |
| `POSTGRES_SEARCH_PLAN.md` | This document |

---

## PostgreSQL Schema Design

### moqui_document (DataDocument storage)

```sql
CREATE TABLE moqui_document (
    document_id     TEXT NOT NULL,       -- maps to ES _id
    index_name      TEXT NOT NULL,        -- maps to ES index name
    doc_type        TEXT,                 -- maps to ES _type (dataDocumentId)
    document        JSONB NOT NULL,       -- the full document
    content_text    TEXT,                 -- concatenated text fields for FTS
    content_tsv     TSVECTOR              -- generated tsvector for search
        GENERATED ALWAYS AS (to_tsvector('english', coalesce(content_text, ''))) STORED,
    created_stamp   TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_stamp   TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT pk_moqui_document PRIMARY KEY (index_name, document_id)
);

-- GIN index on tsvector for full-text search
CREATE INDEX idx_moqui_doc_tsv ON moqui_document USING GIN (content_tsv);

-- GIN index on JSONB for arbitrary field queries
CREATE INDEX idx_moqui_doc_json ON moqui_document USING GIN (document jsonb_path_ops);

-- Trigram index for fuzzy/LIKE queries on content
CREATE INDEX idx_moqui_doc_trgm ON moqui_document USING GIN (content_text gin_trgm_ops);

-- Index for doc_type filtering
CREATE INDEX idx_moqui_doc_type ON moqui_document (doc_type);

-- Optional: BM25 index (requires pg_textsearch extension)
-- CREATE INDEX idx_moqui_doc_bm25 ON moqui_document USING bm25(content_text)
--   WITH (text_config = 'english');
```

### moqui_search_index (Index metadata / mappings)

```sql
CREATE TABLE moqui_search_index (
    index_name      TEXT PRIMARY KEY,
    alias_name      TEXT,
    doc_type        TEXT,                 -- dataDocumentId if applicable
    mapping         JSONB,                -- ES-compatible mapping stored for reference
    settings        JSONB,
    created_stamp   TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_moqui_sidx_alias ON moqui_search_index (alias_name);
```

### moqui_logs (Application logging)

```sql
CREATE TABLE moqui_logs (
    log_id          BIGSERIAL PRIMARY KEY,
    log_timestamp   TIMESTAMPTZ NOT NULL,
    log_level       TEXT,
    thread_name     TEXT,
    thread_id       BIGINT,
    thread_priority INTEGER,
    logger_name     TEXT,
    message         TEXT,
    source_host     TEXT,
    user_id         TEXT,
    visitor_id      TEXT,
    mdc             JSONB,
    thrown          JSONB     -- {name, message, stackTrace, artifactStack, cause, suppressed}
);

-- BRIN index for efficient time-range queries/cleanup
CREATE INDEX idx_moqui_logs_ts ON moqui_logs USING BRIN (log_timestamp);
CREATE INDEX idx_moqui_logs_level ON moqui_logs (log_level);
```

### moqui_http_log (HTTP request logging)

```sql
CREATE TABLE moqui_http_log (
    log_id          BIGSERIAL PRIMARY KEY,
    log_timestamp   TIMESTAMPTZ NOT NULL,
    remote_ip       INET,
    remote_user     TEXT,
    server_ip       TEXT,
    content_type    TEXT,
    request_method  TEXT,
    request_scheme  TEXT,
    request_host    TEXT,
    request_path    TEXT,
    request_query   TEXT,
    http_version    TEXT,
    response_code   INTEGER,
    time_initial_ms BIGINT,
    time_final_ms   BIGINT,
    bytes_sent      BIGINT,
    referrer        TEXT,
    agent           TEXT,
    session_id      TEXT,
    visitor_id      TEXT
);

CREATE INDEX idx_moqui_httplog_ts ON moqui_http_log USING BRIN (log_timestamp);
CREATE INDEX idx_moqui_httplog_path ON moqui_http_log (request_path);
```

### Required Extensions

```sql
CREATE EXTENSION IF NOT EXISTS pg_trgm;           -- fuzzy search, always available
-- Optional, for true BM25 ranking:
-- CREATE EXTENSION IF NOT EXISTS pg_textsearch;   -- requires pg_textsearch extension installed
```

---

## ES Query DSL → PostgreSQL Translation Reference

The `ElasticQueryTranslator` must handle the following ES query types used by Moqui:

| ES Query DSL | PostgreSQL SQL | Notes |
|---|---|---|
| `{query_string: {query: "foo bar", lenient: true}}` | `content_tsv @@ websearch_to_tsquery('english', 'foo bar')` | Primary search method. `websearch_to_tsquery` handles AND/OR/NOT/quotes. Lucene-specific syntax (field:value, wildcards) parsed and translated separately. |
| `{bool: {must: [q1, q2]}}` | `(translated_q1) AND (translated_q2)` | |
| `{bool: {should: [q1, q2]}}` | `(translated_q1) OR (translated_q2)` | |
| `{bool: {must_not: [q1]}}` | `NOT (translated_q1)` | |
| `{bool: {filter: [q1]}}` | Same as `must` | No scoring distinction in SQL |
| `{term: {field: value}}` | `document->>'field' = 'value'` | Nested paths: `document->'obj'->>'field'` |
| `{terms: {field: [v1, v2]}}` | `document->>'field' IN ('v1', 'v2')` | |
| `{range: {field: {gte: v1, lte: v2}}}` | `(document->>'field')::type >= v1 AND ...` | Cast based on mapping type (timestamp, numeric) |
| `{match_all: {}}` | `TRUE` | |
| `{exists: {field: "f"}}` | `document ? 'f'` | JSONB key existence |
| `{nested: {path: "p", query: q}}` | `EXISTS (SELECT 1 FROM jsonb_array_elements(document->'p') elem WHERE ...)` | Translate inner query against `elem` |

### Sorting

| ES Sort | PostgreSQL ORDER BY |
|---|---|
| `[{"field": {"order": "asc"}}]` | `ORDER BY document->>'field' ASC` |
| `[{"field.keyword": {"order": "desc"}}]` | `ORDER BY document->>'field' DESC` (strip `.keyword`) |
| Numeric/date fields | Cast: `(document->>'field')::numeric`, `(document->>'field')::timestamptz` |

### Highlighting

| ES Highlight | PostgreSQL |
|---|---|
| `{highlight: {fields: {field: {}}}}` | `ts_headline('english', document->>'field', query, 'StartSel=<em>, StopSel=</em>')` |

### Scoring / Ranking

| Scenario | Implementation |
|---|---|
| Baseline (all Postgres) | `ts_rank_cd(content_tsv, query)` — term frequency / inverse document frequency approximation |
| With `pg_textsearch` | `-(content_text <@> 'query terms')` — true BM25 scoring, same algorithm as ElasticSearch |
| With `pg_trgm` (fuzzy) | `similarity(content_text, 'query')` for typo tolerance |

### Response Format

The `PostgresElasticClient.search()` method must return a Map matching ES response structure:

```json
{
  "hits": {
    "total": {"value": 42, "relation": "eq"},
    "hits": [
      {
        "_index": "indexname",
        "_id": "docid",
        "_source": { ... document ... },
        "_score": 1.5,
        "highlight": {"field": ["text with <em>match</em>"]}
      }
    ]
  }
}
```

This ensures `SearchServices.search#DataDocuments` can parse the response without changes.

---

## Configuration

### Switching to PostgreSQL backend

In your `MoquiConf.xml` (or environment override):

```xml
<elastic-facade>
    <!-- Use PostgreSQL as the search backend -->
    <cluster name="default" type="postgres" url="transactional"/>
</elastic-facade>
```

The `url="transactional"` tells `PostgresElasticClient` to use the main Moqui transactional datasource connection pool. Alternatively, specify a group-name for a separate connection pool.

### Keeping OpenSearch (default, backward-compatible)

```xml
<elastic-facade>
    <cluster name="default" type="elastic" url="${elasticsearch_url}" 
             user="${elasticsearch_user}" password="${elasticsearch_password}"/>
</elastic-facade>
```

### Mixed mode (search on Postgres, logging on ES)

```xml
<elastic-facade>
    <cluster name="default" type="postgres" url="transactional"/>
    <cluster name="logger" type="elastic" url="http://opensearch:9200"/>
</elastic-facade>
```

### Logging entity group

When using `type="postgres"`, override the logging datasource in `MoquiConf.xml`:

```xml
<!-- Use standard SQL for logging entities instead of ElasticDatasourceFactory -->
<entity-facade>
    <datasource group-name="logging" 
                object-factory="org.moqui.impl.entity.EntityDatasourceFactoryImpl">
        <inline-jdbc pool-name="logging_ds"/>
    </datasource>
</entity-facade>
```

Or simply point it to the transactional group.

---

## Tasks

### Phase 1: Configuration & Schema Foundation

- [x] **TASK-01:** Extend XSD schema — add `type` attribute to `<cluster>` element
- [x] **TASK-02:** Create `SearchEntities.xml` — Moqui entity definitions for `moqui_document`, `moqui_search_index`, `moqui_logs`, `moqui_http_log`
- [x] **TASK-03:** Update `MoquiDefaultConf.xml` — add commented-out postgres cluster example, add postgres-aware logging datasource option

### Phase 2: Core Implementation

- [x] **TASK-04:** Create `ElasticQueryTranslator.groovy` — ES query DSL to PostgreSQL SQL translator
- [x] **TASK-05:** Create `PostgresElasticClient.groovy` — full `ElasticClient` implementation backed by PostgreSQL
  - [x] TASK-05a: Index management methods (`indexExists`, `aliasExists`, `createIndex`, `putMapping`, `deleteIndex`)
  - [x] TASK-05b: Document CRUD methods (`index`, `update`, `delete`, `get`, `getSource`)
  - [x] TASK-05c: Search methods (`search`, `searchHits`, `validateQuery`, `count`, `countResponse`)
  - [x] TASK-05d: Bulk methods (`bulk`, `bulkIndex`, `bulkIndexDataDocument`)
  - [x] TASK-05e: DataDocument helpers (`checkCreateDataDocumentIndexes`, `putDataDocumentMappings`, `verifyDataDocumentIndexes`)
  - [x] TASK-05f: Utility methods (`deleteByQuery`, `getPitId`/`deletePit` via keyset pagination, `objectToJson`/`jsonToObject`)
  - [x] TASK-05g: tsvector population — extract all text from JSONB, weight by field type, generate `content_text` for FTS

### Phase 3: Wire Into ElasticFacade

- [x] **TASK-06:** Modify `ElasticFacadeImpl.groovy` `init()` — dispatch to `PostgresElasticClient` when `type="postgres"`

### Phase 4: Logging Replacements

- [x] **TASK-07:** Create `PostgresSearchLogger.groovy` — Log4j2 events → `moqui_logs` table (queue + batch INSERT)
- [x] **TASK-08:** Modify `ElasticRequestLogFilter.groovy` to work with both backends — HTTP requests route through `ElasticClient.bulkIndex` to `moqui_document` table
- [x] **TASK-09:** Modify `ElasticFacadeImpl.groovy` logger initialization — use Postgres loggers when cluster type is postgres

### Phase 5: Docker & Deployment

- [x] **TASK-10:** Create `docker/moqui-postgres-only-compose.yml` — Postgres + Moqui only, pg_trgm enabled, no OpenSearch
- [ ] **TASK-11:** Document environment variables and runtime configuration for postgres search mode

### Phase 6: Testing & Verification

- [x] **TASK-12:** Integration tests — `PostgresElasticClientTests` (~37 tests) cover createIndex, index/get/update/delete, bulkIndex, search (match_all/term/terms/bool/FTS/pagination), count, deleteByQuery, validateQuery, bulkIndexDataDocument — all passing
- [x] **TASK-13:** DataFeed pipeline test — `bulkIndexDataDocument` test verifies entity metadata stripped, documents indexed with tsvector populated
- [ ] **TASK-14:** Logging test — verify `moqui_logs` and `moqui_http_log` receive entries
- [ ] **TASK-15:** Toggle test — switch between `type="elastic"` and `type="postgres"`, verify both work
- [x] **TASK-16:** Run existing Moqui test suite — no regressions from our changes; 14 pre-existing failures (EntityNoSqlCrud needs ES, EntityFindTests cache flakiness, ToolsScreenRenderTests data issues)
- [ ] **TASK-17:** Search quality test — compare search results between ES and Postgres for sample queries

### Phase 7: Optional Enhancements

- [ ] **TASK-18:** `pg_textsearch` BM25 integration — detect extension at startup, create BM25 index, use `<@>` operator for ranking when available
- [ ] **TASK-19:** Lucene query syntax parser — translate field-specific queries (`field:value`), wildcards (`term*`), phrase queries (`"exact phrase"`) to PostgreSQL equivalents
- [ ] **TASK-20:** Log retention via `pg_cron` — schedule `DELETE FROM moqui_logs WHERE log_timestamp < now() - interval '30 days'` (replaces ES `delete#Documents` jobs)

---

## Task Dependency Graph

```
TASK-01 (XSD schema) ──────────────────────┐
TASK-02 (Entity definitions) ──────────────┤
TASK-03 (Config update) ──────────────────┤
                                           ▼
TASK-04 (Query Translator) ──────► TASK-05 (PostgresElasticClient)
                                           │
                                           ▼
                                   TASK-06 (Wire into ElasticFacade)
                                           │
                     ┌─────────────────────┼─────────────────────┐
                     ▼                     ▼                     ▼
             TASK-07 (Logger)      TASK-08 (HTTP Log)    TASK-10 (Docker)
                     │                     │
                     └──────────┬──────────┘
                                ▼
                        TASK-09 (Logger init)
                                │
                                ▼
                    TASK-12 through TASK-17 (Testing)
                                │
                                ▼
                    TASK-18 through TASK-20 (Enhancements)
```

---

## ElasticClient Interface — Full Method Mapping

For reference, every method on `ElasticFacade.ElasticClient` and its Postgres implementation strategy:

```
┌──────────────────────────────────┬────────────────────────────────────────────────────┐
│ ElasticClient Method             │ PostgresElasticClient Implementation               │
├──────────────────────────────────┼────────────────────────────────────────────────────┤
│ getClusterName()                 │ Return configured cluster name                     │
│ getClusterLocation()             │ Return JDBC URL or "postgres:transactional"        │
│ getServerInfo()                  │ Return PG version via SELECT version()             │
│ indexExists(index)               │ SELECT 1 FROM moqui_search_index WHERE index_name= │
│ aliasExists(alias)               │ SELECT 1 FROM moqui_search_index WHERE alias_name= │
│ createIndex(index, mapping, al.) │ INSERT INTO moqui_search_index + ensure tables     │
│ putMapping(index, mapping)       │ UPDATE moqui_search_index SET mapping=             │
│ deleteIndex(index)               │ DELETE search_index + DELETE documents              │
│ index(index, _id, document)      │ INSERT...ON CONFLICT DO UPDATE + set content_text  │
│ update(index, _id, fragment)     │ UPDATE SET document = document || fragment          │
│ delete(index, _id)               │ DELETE FROM moqui_document WHERE ...                │
│ deleteByQuery(index, queryMap)   │ DELETE WHERE + translated query                    │
│ bulk(index, actionSourceList)    │ Batch INSERT/UPDATE/DELETE in transaction           │
│ bulkIndex(index, idField, docs)  │ Batch INSERT...ON CONFLICT via multi-VALUES        │
│ bulkIndex(5-arg variant)         │ Same + optional refresh (no-op, PG is consistent)  │
│ get(index, _id)                  │ SELECT document + wrap as {_source, _index, _id}   │
│ getSource(index, _id)            │ SELECT document                                    │
│ get(index, _idList)              │ SELECT ... WHERE doc_id IN (...)                   │
│ search(index, searchMap)         │ ElasticQueryTranslator → SQL query → format result │
│ searchHits(index, searchMap)     │ Call search(), return hits.hits[*]._source          │
│ validateQuery(index, queryMap)   │ Try translating, return {valid: true/false}        │
│ count(index, countMap)           │ SELECT COUNT(*) with translated query              │
│ countResponse(index, countMap)   │ Return {count: N}                                  │
│ getPitId(index, keepAlive)       │ Return "pg::{last_seen_id}::{timestamp}" token     │
│ deletePit(pitId)                 │ No-op (keyset pagination is stateless)             │
│ call(method, index, path, ...)   │ UnsupportedOperationException (log warning)        │
│ callFuture(...)                  │ UnsupportedOperationException (log warning)        │
│ makeRestClient(...)              │ UnsupportedOperationException (log warning)        │
│ checkCreateDataDocumentIndexes() │ Read DataDocument entities, call createIndex       │
│ checkCreateDataDocumentIndex()   │ Single DataDocument → createIndex if needed        │
│ putDataDocumentMappings()        │ Store mapping in moqui_search_index                │
│ verifyDataDocumentIndexes(docs)  │ Ensure indexes exist for all doc types in list     │
│ bulkIndexDataDocument(docs)      │ Group by _index, batch insert, populate tsvector   │
│ objectToJson(obj)                │ Jackson ObjectMapper.writeValueAsString            │
│ jsonToObject(json)               │ Jackson ObjectMapper.readValue                     │
└──────────────────────────────────┴────────────────────────────────────────────────────┘
```

---

## Estimated Effort

| Phase | Tasks | Estimated Effort |
|-------|-------|-----------------|
| Phase 1: Config & Schema | TASK-01 to TASK-03 | 1 day |
| Phase 2: Core Implementation | TASK-04 to TASK-05 | 3-5 days |
| Phase 3: Wire Into Facade | TASK-06 | 0.5 day |
| Phase 4: Logging | TASK-07 to TASK-09 | 1-2 days |
| Phase 5: Docker | TASK-10 to TASK-11 | 0.5 day |
| Phase 6: Testing | TASK-12 to TASK-17 | 2-3 days |
| Phase 7: Enhancements | TASK-18 to TASK-20 | 1-2 days |
| **Total** | **20 tasks** | **~9-14 days** |

---

## Risk Mitigation

| Risk | Mitigation |
|------|------------|
| `pg_textsearch` not available on target Postgres version | Baseline uses standard `tsvector`/`ts_rank_cd` — available in all Postgres 10+. BM25 is optional enhancement. |
| Lucene query syntax incompatibility | `websearch_to_tsquery` handles most common patterns (AND/OR/NOT/quotes). Complex Lucene syntax (regex, fuzzy `~`, boost `^`) gets a best-effort translator; unsupported features logged as warnings. |
| Performance gap for high-volume logging | Batch inserts with `UNLOGGED` table option or partitioned tables (monthly) with BRIN indexes. Comparable throughput to ES bulk API for typical Moqui workloads. |
| Nested document queries | `jsonb_array_elements` + subquery handles nested paths, matching ES `include_in_root:true` behavior. Root-level fields already flattened by DataDocument builder. |
| Breaking existing ES-mode users | Default `type="elastic"` preserves current behavior. No changes to any ES codepath. |
| ES `call()`/`makeRestClient()` raw API usage in add-on components | These throw `UnsupportedOperationException` in postgres mode. Document clearly. Audit known components before deployment. |
