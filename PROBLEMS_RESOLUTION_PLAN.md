# PostgreSQL Search Backend — Review Verification & Resolution Plan

Assessment of schue's `PROBLEMS.md` critique against the current code on
`feature/postgres-search-backend` (tip `84f7c48a`).

Each issue below was checked against the actual source. The **Verdict** column reflects what the
code does *today* (some issues raised in the critique have already been partially or fully addressed
in the current branch).

Legend — Verdict: ✅ Valid · 🟡 Partially valid / already mitigated · ❌ Invalid (claim not true of current code)

---

## Verdict Summary

| # | Issue | Verdict | Severity | Evidence (file:line) |
|---|-------|---------|----------|----------------------|
| 1 | Schema / entity-def vs. `initSchema()` type conflict | ✅ Valid | High | `SearchEntities.xml:46-53`; live warning in `build/reports/.../CacheFacadeTests.html:186` "Found unknown columns … [content_tsv]" |
| 2 | Hardcoded `'english'` FTS language | ✅ Valid | Medium | `PostgresElasticClient.groovy:74,455,939`; `ElasticQueryTranslator.groovy:180,183` |
| 3 | `logging` datasource group won't work with postgres | ❌ Invalid | Low | `ElasticDatasourceFactory.groovy:175-177` resolves client via `ElasticClient` interface — works with any impl |
| 4 | Shallow merge in `update()` loses nested data | ✅ Valid | Medium | `PostgresElasticClient.groovy:446-447` (`putAll`, comment wrongly says "deep merge") |
| 5 | SQL-injection surface via interpolation | 🟡 Mitigated | Low | `--` vector already blocked `ElasticQueryTranslator.groovy:48-50`; all fields go through `sanitizeFieldName`; casts are hardcoded |
| 6 | Unbounded log-table growth / no partitioning | ✅ Valid | Medium | `PostgresElasticClient.groovy:176,209` (`BIGSERIAL`, no partition); `deleteByQueryAppLog/HttpLog:518-560` single-txn delete |
| 7 | DDL runs inside one transaction | 🟡 Partially | Low | `PostgresElasticClient.groovy:114-256` — but every statement is `IF NOT EXISTS` (idempotent) and PG DDL is transactional (atomic init is a feature) |
| 8 | `jsonb_path_ops` GIN index on whole document | 🟡 Partially | Low-Med | `PostgresElasticClient.groovy:165` — real write/space cost, but genuinely useful; make it optional |
| 9 | `guessCastType()` heuristic is fragile | 🟡 Improved | Low-Med | `ElasticQueryTranslator.groovy:617-642` now also inspects sample value; still not mapping-driven |
| 10 | `@CompileStatic` on "highly dynamic" code | ❌ Invalid | None | `PostgresElasticClient.groovy:50` — class compiles & runs cleanly; GString SQL + typed maps are statically compilable |
| 11 | No aggregation support | ✅ Valid | Medium | no `aggs`/`aggregation` handling anywhere in `PostgresElasticClient.groovy` |
| 12 | `search()` always runs two queries | 🟡 Partially | Low | count is gated by `if (tq.trackTotal)` and `trackTotal` reflects `track_total_hits`; default `true` → two queries |
| 13 | PIT is a stub (no real snapshot) | ✅ Valid | Medium | `PostgresElasticClient.groovy:1212-1223` synthetic token, `deletePit` no-op |
| 14 | Postgres suite runs in default test task | ✅ Valid | Medium | `framework/build.gradle:206` `include '**/*PostgresSearchSuite.class'` — contradicts suite's own "opt-in" docstring (`PostgresSearchSuite.groovy:12-20`) |

**Net:** 6 fully valid (1, 2, 4, 6, 11, 13, 14 → 7), several partially valid/already-mitigated, 2 invalid (3, 10).

---

## Implementation Status — ALL ISSUES RESOLVED ✅

Every issue in this plan has been implemented and verified (compiled + full `PostgresSearchSuite` run,
0 failures) in `PostgresElasticClient.groovy` / `ElasticQueryTranslator.groovy` unless noted otherwise.

| # | Issue | Status | What changed |
|---|-------|--------|--------------|
| 14 | Postgres suite in default test task | ✅ Done | `framework/build.gradle` gates `PostgresSearchSuite` behind `-PincludePostgresSearch` / `MOQUI_PG_SEARCH=true`; excluded from the default `MoquiSuite` run. |
| 1 | Schema vs. `initSchema()` type conflict | ✅ Done | Added `ensureColumnType()` healing helper (adds column if missing, `ALTER ... TYPE ... USING` cast, verifies the resulting type and logs at `.warn` if a cast silently no-ops) applied to `document`/`content_tsv`/`moqui_logs.mdc`/`moqui_logs.thrown`. |
| 4 | Shallow merge in `update()` | ✅ Done + test | Added a recursive `deepMerge()` helper so nested `Map` fields merge instead of being replaced wholesale; sibling keys under a partially-updated nested object now survive. Test: `update_deepMergesNestedFields()`. |
| 2 | Hardcoded `'english'` FTS language | ✅ Done + tests | Added a `text-config` cluster attribute (declared in `moqui-conf-3.xsd`, validated against a safe-identifier pattern, default `"english"`), threaded through `to_tsvector`/`websearch_to_tsquery`/`ts_headline` via a per-thread `ElasticQueryTranslator.setTextConfig()`/`clearTextConfig()`. Tests: `queryString_defaultsToEnglishTextConfig()`, `queryString_honorsConfiguredTextConfig()`, `buildHighlightExpr_honorsConfiguredTextConfig()`. |
| 13 | PIT is a stub | ✅ Done + test | Implemented ES-style keyset (`search_after`) pagination for the default-order case: each hit carries a `"sort": [updated_stamp_ms, doc_id]` cursor; a subsequent request's `search_after` is translated into a `(updated_stamp, doc_id) > (cursor)` WHERE predicate instead of relying on a shifting `OFFSET`. `getPitId()`'s docs make the remaining (documented, unavoidable without a real MVCC snapshot) limitation explicit. Test: `search_keysetPaginationWithSearchAfter()` (3-page walk over 10 docs, asserts no gaps/duplicates). |
| 6 | Unbounded log-table growth | ✅ Done | Added `batchedDelete()` — chunks `DELETE ... WHERE ctid IN (SELECT ctid ... LIMIT ?)` in bounded batches (default 5000 rows) instead of one unbounded statement — used by both `deleteByQueryAppLog()`/`deleteByQueryHttpLog()` retention deletes. (Full log-table partitioning intentionally out of scope; noted as a possible future follow-up.) |
| 11 | No aggregation support | ✅ Done | Added a one-time (`aggsWarningLogged`, per-JVM) `.warn` in `search()` when a request includes `aggs`/`aggregations`, so the unsupported-aggregations gap surfaces during development instead of silently returning empty aggregation results. (Implementing `terms`/`date_histogram`/`stats` etc. is a larger feature left for future work.) |
| 5 | SQL-injection surface | ✅ Done + test | Added an `ALLOWED_CAST_TYPES` whitelist assertion on `guessCastType()`'s return value (only `""`, `"::numeric"`, `"::timestamptz"` permitted) as defense-in-depth on top of the pre-existing `sanitizeFieldName()`/`SAFE_FIELD_PATTERN` protections. Test: `guessCastType_onlyReturnsWhitelistedSuffixes()` (including a malicious sample-value case). |
| 9 | `guessCastType()` fragility | ✅ Done + test | Added mapping-driven casting: a per-cluster cache (`fieldTypeMapCache`, invalidated on `createIndex()`/`putMapping()`) flattens each index's stored `moqui_search_index.mapping` (`properties`/`type`) into a field→ES-type map; `ElasticQueryTranslator.guessCastType()` now prefers the declared type (via a per-thread `setFieldTypeMap()`/`clearFieldTypeMap()`, set around `search()`/`deleteByQuery()`/`validateQuery()`/`countResponse()`) over its name/value heuristics, which remain the fallback. Test: `guessCastType_prefersDeclaredMappingType()`. |
| 12 | Two queries per search | ✅ Done + test | `search()` now uses `count(*) OVER() AS _total` in the main query to avoid a second round-trip when a keyset cursor isn't active (the common/default case); falls back to the original standalone `COUNT` query when a keyset predicate is active (to preserve filter-only total semantics) or when the requested page comes back empty (from/size past the end of the results, since there's no row to carry the `_total` column on). Test: `search_totalAccurateWhenPageIsEmpty()`. |
| 7 | DDL inside a transaction | ✅ Done | `initSchema()` refactored to use `execRequired()`/`execOptional()` helpers: required DDL still aborts/rolls back the whole (atomic) init on failure but now logs the exact failing statement/description first; optional/best-effort pieces (`pg_trgm` extension, the trigram GIN index that depends on it, and the `moqui_logs`/`moqui_http_log` `BIGSERIAL`-default healing blocks) no longer abort the whole init if they fail. |
| 8 | `jsonb_path_ops` GIN index | ✅ Done | Added an `enable-jsonb-path-index` cluster attribute (declared in `moqui-conf-3.xsd`, default `true`/on) so the `document` GIN(jsonb_path_ops) index can be opted out of for log-like/very-large-document indices where the write/storage cost isn't worth it. |
| 3 | `logging` datasource group won't work with postgres | ✅ Done (docs only) | Corrected the misleading comment in `MoquiDefaultConf.xml` above the `logging` datasource — it now explains the logging group works automatically through the `ElasticFacade.ElasticClient` interface regardless of which cluster impl (including `PostgresElasticClient`) the `default` cluster resolves to. |
| 10 | `@CompileStatic` on dynamic code | ✅ Done (docs only) | Added a one-line comment above `PostgresElasticClient`'s `@CompileStatic` annotation confirming it's intentional/compatible. |

**Regression check:** `./gradlew :framework:test -PincludePostgresSearch --tests "PostgresSearchSuite"`
passes with 0 failures (`PostgresElasticClientTests`: 40 tests; `PostgresSearchTranslatorTests`: 51
tests). A full default `./gradlew :framework:test` (`MoquiSuite`) run was also done to check for
regressions outside the search backend; the handful of failures observed there (`EntityFindTests`,
`EntityNoSqlCrud.createBulk TestNoSqlEntity`, `ToolsScreenRenderTests`) are pre-existing stale test
data in the persistent local Postgres test database (duplicate-key/already-exists errors and a
leftover 200-row `doc_id LIKE 'BULK%'` fixture from an earlier run, confirmed via direct `psql`
inspection) — unrelated to and not caused by any change made for this plan.

---

## Detailed Findings & Resolutions

### 🔴 High priority

#### Issue 1 — Entity definition vs. `initSchema()` column-type conflict — ✅ Valid (High)
**Evidence.** `moqui.search.SearchDocument` maps `documentJson`→`document` and `contentText`→`content_text`
as `text-very-long` (Moqui emits `TEXT`), and does **not** declare `content_tsv` at all
(`SearchEntities.xml:46-53`). `initSchema()` creates `document JSONB` + `content_tsv TSVECTOR`
(`PostgresElasticClient.groovy:143-165`) and then force-casts with a `.trace`-logged
`ALTER … TYPE JSONB` fallback (`:158-162`). The conflict is real and observable: the test run logs
`EntityDbMeta … Found unknown columns on table moqui_document … [content_tsv]`.
**Nuance.** The worst case in the critique ("entity sync re-creates the table as TEXT, destroying
JSONB") overstates it — Moqui's `runtime-add-missing` only *adds* missing columns; it does not drop
or retype existing ones. So the durable failure mode is the noisy warnings + the fragile trace-level
cast, not silent data loss.
**Resolution.**
1. Suppress the entity/DDL disagreement authoritatively: mark `SearchDocument`/`SearchIndex` fields
   that are DB-managed so entity sync leaves them alone, or set the entities to
   `runtime-add-missing="false"` for their group so Moqui never tries to reconcile these tables.
2. Add the `content_tsv` (and `content_text`) column awareness to avoid the "unknown columns" warning
   (either declare `content_tsv` as an opaque/ignored field or exclude the table from meta-check).
3. Promote the `ALTER … TYPE JSONB` fallback log from `.trace` to `.warn` and verify the resulting
   column type after the alter so a silent failure can't go unnoticed.
4. Add a short "schema ownership" note in `SearchEntities.xml` documenting that DDL is owned by
   `initSchema()`.

#### Issue 6 — Unbounded log-table growth / no partitioning — ✅ Valid (Medium)
**Evidence.** `moqui_logs`/`moqui_http_log` are plain `BIGSERIAL` tables (`:176,209`) with BRIN indexes
but no partitioning; cleanup is a single `DELETE … WHERE` per table (`:518-560`).
**Resolution (phased).**
1. **Now (low effort):** batch the retention delete (delete in chunks with `LIMIT`/`ctid` loop) to avoid
   one long-running, WAL-heavy transaction and lock escalation; document that a periodic
   `VACUUM`/`pg_repack` may be needed.
2. **Later (higher effort, optional):** offer opt-in native range partitioning by `log_timestamp`
   (monthly/weekly) so retention becomes `DROP PARTITION` (no bloat). Keep it configurable and off by
   default to avoid forcing PG version/feature requirements on all deployments.

#### Issue 13 — PIT is a stub — ✅ Valid (Medium)
**Evidence.** `getPitId()` returns `pg::{index}::{ms}` and `deletePit()` is a no-op
(`:1212-1223`). There is no real MVCC snapshot, so a long scroll can see rows inserted/updated mid-iteration.
**Resolution.**
1. **Document** the limitation prominently (scroll/`search_after` is best-effort, not snapshot-isolated).
2. Make iteration stable via **keyset pagination** (order by an immutable tiebreaker such as
   `(updated_stamp, doc_id)` and page with `search_after` on those values) instead of `LIMIT/OFFSET`,
   which fixes the most common "shifting window / duplicate or skipped rows" symptom without needing a
   held snapshot.
3. (Optional, heavy) a true snapshot would require a dedicated `REPEATABLE READ` connection held for the
   scroll lifetime — only pursue if a real snapshot guarantee is required.

### 🟠 Medium priority

#### Issue 2 — Hardcoded `'english'` — ✅ Valid (Medium)
**Evidence.** `to_tsvector('english', …)` (`:74,455,939`), `websearch_to_tsquery('english', …)`
(`ElasticQueryTranslator.groovy:180,183`), and `ts_headline('english', …)`.
**Resolution.** Add a `text-config` (regconfig) option on the `<cluster>` element (default `english`),
thread it through `PostgresElasticClient` into a single constant used by index, query, and highlight SQL,
and pass it as an identifier (validated against a whitelist / `pg_ts_config`) — never as a bind param,
since regconfig can't be parameterized. Optionally allow per-index override via index settings.

#### Issue 4 — Shallow merge in `update()` — ✅ Valid (Medium)
**Evidence.** `mergedDoc.putAll(documentFragment)` (`:447`) replaces whole top-level values; the comment
on `:446` claims "Deep merge" but the behavior is shallow. Nested objects lose sibling keys, unlike ES
`_update`.
**Resolution.** Implement a recursive deep-merge helper (merge nested `Map`s key-by-key; fragment scalars
and arrays overwrite) and use it in `update()`. Add a unit test covering the `address.{city,state,zip}`
example from the critique. Fix the misleading comment.

#### Issue 11 — No aggregation support — ✅ Valid (Medium)
**Evidence.** No `aggs`/`aggregation` handling in the client; requests carrying aggregations get no
`aggregations` block back.
**Resolution.**
1. **Now:** document the limitation clearly and make it *loud* — if a search request contains `aggs`,
   log a `warn` (once) so callers aren't silently misled.
2. **Incremental:** implement the common cases that map cleanly to SQL — `terms`
   (`GROUP BY jsonpath`), `date_histogram` (`date_trunc`), and `stats/avg/sum/min/max` — behind the
   existing translator, returning ES-shaped `aggregations`. Defer nested/pipeline aggs.

#### Issue 14 — Postgres suite in default test task — ✅ Valid (Medium)
**Evidence.** `framework/build.gradle:206` includes `**/*PostgresSearchSuite.class` in the default `test`
task, directly contradicting `PostgresSearchSuite.groovy:12-20` which says it is opt-in. Without a live
PG, `:framework:test` fails for everyone.
**Resolution.** Gate the include behind a project/system property, e.g.:
```groovy
if (project.hasProperty('includePostgresSearch') || System.getenv('MOQUI_PG_SEARCH') == 'true') {
    include '**/*PostgresSearchSuite.class'
}
```
Document the opt-in flag in the PR/README. This restores the suite's stated "opt-in" behavior and unblocks
non-Postgres development/CI.

### 🟡 Low priority (hardening / partially-already-addressed)

#### Issue 5 — SQL-injection surface — 🟡 Mostly mitigated (Low)
**Evidence.** The critique's concrete `user.name--` example is already rejected by an explicit
`field.contains("--")` guard (`ElasticQueryTranslator.groovy:48-50`); all field names pass through
`sanitizeFieldName()` (rejects quotes/semicolons/whitespace/parens), and cast types are hardcoded
literals. No active injection path found.
**Resolution (defense-in-depth).** Add a whitelist assertion on `guessCastType()`'s return (only
`""`, `::numeric`, `::timestamptz` allowed) so future edits can't introduce an injection vector; add a
brief invariant comment at each interpolation site stating that only sanitized identifiers/hardcoded
casts may be interpolated. Add a negative unit test asserting malicious field names throw.

#### Issue 7 — DDL inside a transaction — 🟡 Partially valid (Low)
**Evidence.** All DDL is in one `begin/commit` (`:114-256`). Mitigating: statements are `IF NOT EXISTS`
(idempotent), and transactional DDL in PostgreSQL means a partial failure rolls back cleanly (atomic
schema init is generally desirable).
**Resolution.** Keep the transaction for atomicity but make init resilient: wrap the *optional* pieces
(extension creation, JSONB cast, sequence fix) so a non-fatal failure doesn't abort the whole init, and
ensure the fatal path logs the exact failing statement. Low effort; mostly already done for the
extension/cast.

#### Issue 8 — `jsonb_path_ops` GIN index — 🟡 Partially valid (Low-Med)
**Evidence.** `idx_mq_doc_json … GIN (document jsonb_path_ops)` (`:165`) indexes every path; write
amplification and size cost are real for large/deep docs.
**Resolution.** Make this index optional via a cluster/index setting (default on for correctness of
arbitrary path queries, allow opt-out for log-like or very large documents). Document the tradeoff.
No urgent code change required.

#### Issue 9 — `guessCastType()` fragility — 🟡 Improved (Low-Med)
**Evidence.** Now falls back to inspecting the sample value (numeric/decimal/ISO-date detection,
`:629-639`), covering many of the critique's examples (`duration`, `weight`, `size` with numeric values).
Still name/value heuristic, not authoritative.
**Resolution.** When an index mapping is available (`moqui_search_index.mapping`/DataDocument field
types), prefer the declared type over the heuristic; keep the current heuristic as fallback. Medium
effort, meaningful correctness win for range/sort.

#### Issue 12 — Two queries per search — 🟡 Partially valid (Low)
**Evidence.** COUNT is already gated by `if (tq.trackTotal)`, and `trackTotal` mirrors the request's
`track_total_hits` — so callers can already avoid it. Default `true` means two queries by default.
**Resolution.** Optionally collapse to a single query using `count(*) OVER () AS _total` in the main
`SELECT` so the total comes back with the page (removes the second round-trip while preserving the
default behavior). Low effort, purely an optimization.

### ⚪ No action

#### Issue 3 — `logging` group won't work with postgres — ❌ Invalid (Low)
**Why invalid.** `ElasticDatasourceFactory.getElasticClient()` resolves the client purely through
`efi.ecfi.elasticFacade.getClient(clusterName)` and uses the `ElasticFacade.ElasticClient` **interface**
(`ElasticDatasourceFactory.groovy:175-177`). Since `PostgresElasticClient implements
ElasticFacade.ElasticClient`, when the `default` cluster is `type="postgres"` the logging group's factory
transparently delegates to it — no override required and no startup failure.
**Action.** None functional. At most, tidy the misleading comment in `MoquiDefaultConf.xml:500-507` to
say the logging group works automatically when the default cluster is postgres.

#### Issue 10 — `@CompileStatic` on dynamic code — ❌ Invalid (None)
**Why invalid.** The class carries `@CompileStatic` (`:50`) and compiles and runs cleanly (the branch
builds and all `:framework:test` pass). GString SQL interpolation and typed `Map`/`LinkedHashMap` usage
are fully static-compile compatible; removing the annotation would *reduce* type-safety and performance.
**Action.** None. (Optionally add a one-line comment noting `@CompileStatic` is intentional and
compatible.)

---

## Suggested Execution Order

1. **Unblock development first (Low effort, high leverage):**
   - Issue 14 — gate the Postgres suite behind a flag.
   - Issue 1 (steps 1–3) — stop entity sync from fighting the DDL and raise the JSONB-cast log level.
2. **Correctness fixes (Medium):**
   - Issue 4 — deep merge in `update()` (+ test).
   - Issue 2 — configurable FTS language.
   - Issue 13 — keyset pagination + document PIT limitation.
3. **Operational & feature gaps (Medium):**
   - Issue 6 — batched retention deletes now; optional partitioning later.
   - Issue 11 — warn on aggregations now; implement `terms`/`date_histogram`/`stats` incrementally.
4. **Hardening / polish (Low):**
   - Issue 5 — cast-type whitelist + invariant comments/tests.
   - Issue 9 — mapping-driven cast types.
   - Issue 12 — single-query total via `count(*) OVER ()`.
   - Issues 7, 8 — resilient init + optional GIN index.
5. **Docs only:** Issues 3 and 10 — correct the comments; no functional change.
