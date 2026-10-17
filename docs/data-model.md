# LinkedIn context data model

The initial schema is implemented in `pb_migrations/1790300100_linkcontext.js`. PocketBase supplies the default `users` auth collection; LinkContext configures it without creating another identity collection.

## Collections

| Collection | Natural Key (`upsert`) | Responsibility |
| --- | --- | --- |
| `users` | — | Humans and agents, provisioned by verified Workspace Google login or an operator; excluded from SQL |
| `user_directory` | — | SQL-readable identity IDs and display names |
| `sync_runs` | — | Extraction run tracking (`scope`, `lookback_since`, `status`, counters, `cursor_info`) |
| `companies` | `linkedin_url` or `universal_name` | LinkedIn company pages, industry, size, website, optional `crm_organization_id` |
| `profiles` | `public_identifier` or `linkedin_url` | LinkedIn member profiles, headline, location, connection degree (`1st`, `2nd`, `3rd`, `out_of_network`, `self`), optional `crm_person_id` |
| `experiences` | `(profile, company_name, title, start_date)` | Work history entries linking a `profile` to a `company` |
| `connections` | `profile` | First-degree network edges (`connected`, `removed`, `disconnected`) |
| `invitations` | `invitation_urn` or `(profile, direction)` | Sent and received connection invitations (`pending`, `accepted`, `ignored`, `withdrawn`) |
| `posts` | `urn` | Timeline/feed posts, author profile/company, engagement counts, feed reason, `published_at`, optional `crm_deal_id` |
| `post_interactions` | `interaction_key` | Reactions, comments, and reposts on a `post` |
| `notifications` | `notification_urn` | LinkedIn notifications (`type`, `read_state`, actor, target post/thread, `occurred_at`) |
| `threads` | `thread_urn` | Messaging conversations, subject, snippet, `unread_count`, `last_activity_at`, optional `crm_deal_id` |
| `thread_participants` | `(thread, profile)` | Participants in a messaging thread |
| `messages` | `message_urn` | Individual messages in a thread (`inbound`, `outbound`, `system`), `sent_at`, optional `crm_message_id` |
| `bookmarks` | `(target_collection, target_id, label)` | User/agent saved references with tags, priority, notes, and deep-link path |
| `audit_log` | — | Attributed create/update changes; ordinary users cannot modify it |

All writable domain records carry server-managed `created_by`, `updated_by`, `revision`, `created`, and `updated`. Every REST update requires `expected_revision`, an integer equal to the current revision. A stale update returns HTTP 409. Records cannot be deleted through REST; archive or update their status instead. Record updates and audit changes commit together, including inside batches.

## Deterministic IDs & idempotent upsert

Every LinkedIn entity has a deterministic 15-character PocketBase ID (`lc` + 13 lowercase base32 characters of `SHA-256(collection + ":" + canonical_natural_key)`). When `linkcontext upsert <collection> '<json>'` runs:
1. It normalizes LinkedIn URLs and computes the deterministic ID.
2. If `--since <duration|ISO-date>` is passed, it extracts the timestamp from LinkedIn Snowflake URNs (`(id >> 22)` ms since epoch) or timestamp fields (`published_at`, `occurred_at`, `sent_at`, `last_activity_at`) and skips records older than the cutoff.
3. It checks whether the record already exists. If absent, it creates the record with that deterministic ID. If present, it merges non-empty incoming fields into the existing record (never overwriting populated fields with `null`/`""`) and submits a revision-checked `PATCH` only if at least one field changed.

## Cross-referencing with DealContext (CRM)

LinkContext supports two complementary CRM cross-referencing mechanisms:
1. **Normalized URL / Name Matching**: Both `linkcontext` (`profiles.linkedin_url`, `companies.linkedin_url`) and `dealcontext` (`people.linkedin_url`, `organizations.linkedin_url`) store canonical LinkedIn URLs, allowing zero-configuration cross-context matching in Python.
2. **Cached Soft-Reference Columns**: `profiles.crm_person_id`, `companies.crm_organization_id`, `posts.crm_deal_id`, `threads.crm_deal_id`, and `messages.crm_message_id` cache verified `DealContext` record IDs so subsequent queries and UI views immediately show the linked CRM entity.

## Validation

`tests/integration.py` uses synthetic records in an isolated temporary database. It checks revisions, concurrent updates, transactional audit and batch rollback, uniqueness constraints, domain invariants, protected audit writes, and exclusion of auth records from SQL. `tests/skill.py` verifies `upsert` idempotency, non-destructive merging, `--since` lookback filtering, and `sync-start` / `sync-finish` tracking.
