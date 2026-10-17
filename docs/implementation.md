# Implementation status

The initial LinkContext application implements the 15 SQL-exported LinkedIn collections (`user_directory`, `sync_runs`, `companies`, `profiles`, `experiences`, `connections`, `invitations`, `posts`, `post_interactions`, `notifications`, `threads`, `thread_participants`, `messages`, `bookmarks`, `audit_log`), operator provisioning, localhost user bootstrap (`LINKCONTEXT_LOCAL_USER_EMAIL` / `LINKCONTEXT_LOCAL_USER_PASSWORD`), verified Google Workspace JIT, SQL allowlists, attribution, audit history, revision-checked writes, deterministic 15-char IDs, idempotent non-destructive `upsert`, `--since` lookback filtering, and the authenticated browser reader at `/`.

See [the data model](data-model.md) for exact collection schemas, natural keys, and deduplication semantics.
