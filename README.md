# LinkContext

LinkedIn context store operated through a coding agent, built on [PocketContext](https://github.com/pocketcontext/pocketcontext). LinkContext stores normalized LinkedIn profiles, companies, career history, network connections, invitations, timeline posts, interactions, notifications, messaging threads, messages, and bookmarks, with an authenticated read-only browser reader at `/`.

## Application

Ingest, deduplicate, browse, and cross-reference LinkedIn activity alongside CRM data (`DealContext`). Writes enforce optimistic concurrency (`expected_revision`), attribution (`created_by`, `updated_by`), transactional audit history (`audit_log`), and non-destructive lifecycle status updates (`DELETE` is blocked). See [the data model](docs/data-model.md).

One deployment serves one team's shared LinkedIn context workspace. In local-first mode on `http://127.0.0.1:8095` (`http://localhost:8095`), an ordinary `users` account can be bootstrapped via `LINKCONTEXT_LOCAL_USER_EMAIL` and `LINKCONTEXT_LOCAL_USER_PASSWORD`. When deployed publicly at `https://link.pocketcontext.com`, verified Google Workspace identities receive a `users` account on first login. PocketBase's default `users` collection serves both humans and agents; direct public REST signup remains blocked.

## Build and run (localhost-first on port 8095)

Build the server revision recorded in `POCKETCONTEXT_VERSION`, using the Go version in its `go.mod`, CGO and a C compiler.

```sh
# From a PocketContext checkout at the pinned revision:
make build

# Build the reader UI assets once:
cd ui && pnpm install --frozen-lockfile && pnpm build && cd ..

# Start LinkContext locally on http://127.0.0.1:8095:
export LINKCONTEXT_LOCAL_USER_EMAIL=agent@localhost.localdomain
export LINKCONTEXT_LOCAL_USER_PASSWORD='YourLocalAgentPassword123!'
/path/to/pocketcontext serve --dir ./pb_data --http 127.0.0.1:8095
```

Startup applies migrations and serves the authenticated reader UI at `http://localhost:8095/`. Keep `pb_data` outside Git.

## Agent client & ingestion commands

Install or copy `skills/linkcontext` to `~/.agents/skills/linkcontext` (and symlink `~/.claude/skills/linkcontext`). The portable client (`linkcontext`) supports authenticated SQL reads, REST writes, deterministic ID generation, lookback windowing (`--since`), and idempotent upserts:

```sh
export LINKCONTEXT_URL=http://127.0.0.1:8095
export LINKCONTEXT_USER_EMAIL=agent@localhost.localdomain
export LINKCONTEXT_USER_PASSWORD='YourLocalAgentPassword123!'

"/absolute/path/to/skills/linkcontext/linkcontext" login
"/absolute/path/to/skills/linkcontext/linkcontext" whoami
"/absolute/path/to/skills/linkcontext/linkcontext" check

# Idempotent upsert with deterministic 15-char ID and non-destructive merge:
"/absolute/path/to/skills/linkcontext/linkcontext" upsert profiles '{"public_identifier":"alice-smith","full_name":"Alice Smith","headline":"CTO at Example"}'

#Bounded sync run lifecycle with --since lookback cutoff:
"/absolute/path/to/skills/linkcontext/linkcontext" sync-start --scope feed --since 7d
"/absolute/path/to/skills/linkcontext/linkcontext" upsert posts --since 7d '{"urn":"urn:li:activity:7400000000000000000","text_content":"Launching v2"}'
"/absolute/path/to/skills/linkcontext/linkcontext" sync-finish <sync_run_id> --status completed --seen 10 --upserted 4 --skipped 6
```

Never use superuser credentials in the agent client. Updates include `expected_revision`; stale writes return HTTP 409. Related writes can use transactional `/api/batch` requests.

## Browser reader and permanent links

The authenticated reader at `/` provides a collection chooser across all 14 browsable collections (`profiles`, `companies`, `experiences`, `connections`, `invitations`, `posts`, `post_interactions`, `notifications`, `threads`, `thread_participants`, `messages`, `bookmarks`, `sync_runs`, `audit_log`), server-side text search, paginated records, collection-specific filters, and outgoing/reverse relationship links.

Use `/#/<collection>/<record-id>` for a permanent record link:
- Localhost: `http://localhost:8095/#/profiles/<record-id>`
- Future public deployment: `https://link.pocketcontext.com/#/profiles/<record-id>`

Because record IDs (`lc` + 13 base32 chars) are deterministic hashes of canonical LinkedIn natural keys, re-extracting data preserves the exact same record ID and URL. If LinkContext is later migrated from `http://localhost:8095` to `https://link.pocketcontext.com`, only the origin prefix changes while every `/#/<collection>/<record-id>` path remains identical.

```sh
cd ui
pnpm install --frozen-lockfile
pnpm typecheck
pnpm test
pnpm build
pnpm exec playwright install chromium
pnpm e2e
cd ..
python3 tests/reader.py --binary /absolute/path/to/pinned/pocketcontext --browser
```

## Validate

All tests use synthetic records and isolated temporary databases:

```sh
python3 tests/integration.py --binary /absolute/path/to/pocketcontext
python3 tests/tracing.py --binary /absolute/path/to/pinned/pocketcontext
python3 tests/auth.py --binary /absolute/path/to/pocketcontext
python3 tests/oauth_integration.py --binary /absolute/path/to/pocketcontext
python3 tests/skill.py --binary /absolute/path/to/pocketcontext
python3 tests/deploy.py --binary /absolute/path/to/pocketcontext
python3 tests/maintenance.py --binary /absolute/path/to/pocketcontext
python3 tests/object_storage.py --binary /absolute/path/to/pocketcontext
python3 tests/reader.py --binary /absolute/path/to/pocketcontext --browser
python3 tests/oauth.py
python3 tests/packaging.py
python3 tests/entrypoint.py
python3 tests/maintenance_entrypoint.py
python3 tests/deploy_workflow.py
```

When an intentional schema change occurs, run `tests/skill.py --binary ... --write-schema` and review the snapshot and skill references.

## Documentation

- [Data model](docs/data-model.md)
- [Deployment](docs/deployment.md)
- [Container runtime](docs/container-runtime.md)
- [CI and deployment](docs/ci-and-deployment.md)
- [Implementation status](docs/implementation.md)
