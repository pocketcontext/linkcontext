# Antigravity Browser Extraction & Idempotent Ingestion Guide

Use this workflow when Antigravity drives the user's browser on LinkedIn and ingests records into `LinkContext`.

## 1. End-to-End Sync Run Lifecycle

Always wrap an extraction session in a `sync_run` so watermarks, cutoffs, and stats are recorded:

```sh
# 1. Start a sync run for a surface with a lookback horizon (e.g. 7d, 24h, 2026-10-10, or last-sync)
RUN_JSON=$("/path/to/skills/linkcontext/linkcontext" sync-start feed --since 7d --max-items 50)
SYNC_ID=$(printf '%s' "$RUN_JSON" | python3 -c 'import json,sys; print(json.load(sys.stdin)["sync_run"]["id"])')
CUTOFF=$(printf '%s' "$RUN_JSON" | python3 -c 'import json,sys; print(json.load(sys.stdin)["lookback_since"])')
```

`sync-start` returns:
- `sync_run.id`: Pass this to `--sync-run "$SYNC_ID"` on every `upsert` call.
- `lookback_since`: The UTC cutoff timestamp (`YYYY-MM-DD HH:MM:SS.mmmZ`).
- `last_completed_sync`: The previous completed `sync_runs` row for that surface (if any).

When extraction finishes, close the run:

```sh
"/path/to/skills/linkcontext/linkcontext" sync-finish "$SYNC_ID" \
  --status completed \
  --stats '{"scanned": 25, "created": 8, "updated": 3, "unchanged": 14}'
```

---

## 2. Dependency Order for Upserting Extracted Entities

Because records reference `companies`, `profiles`, `posts`, and `threads` by their 15-character IDs, always upsert parent entities first (or use deterministic IDs):

1. **`companies`** (extracted from profile cards, experience entries, or company posts)
2. **`profiles`** (post authors, commenters, notification actors, message participants, connections)
3. **`experiences`**, **`connections`**, **`invitations`** (referencing `profiles.id` and `companies.id`)
4. **`posts`** (referencing `author_profile` or `author_company` and optional `social_actor`)
5. **`post_interactions`** and **`notifications`** (referencing `posts.id` and `profiles.id`)
6. **`threads`**, then **`thread_participants`**, then **`messages`**

Because `linkcontext` uses **deterministic 15-character IDs**, you can either read the `ids` array returned by `linkcontext upsert` OR precompute any record's ID directly:
- Company `acme-corp` $\to$ `linkcontext deterministic-id companies acme-corp`
- Profile `jane-doe` $\to$ `linkcontext deterministic-id profiles jane-doe`
- Post `urn:li:activity:7251234567890123456` $\to$ `linkcontext deterministic-id posts urn:li:activity:7251234567890123456`
- Thread `urn:li:messagingThread:2-abc` $\to$ `linkcontext deterministic-id threads urn:li:messagingThread:2-abc`

---

## 3. Surface-Specific Stopping & Extraction Rules

### A. Suggested Timeline / Feed (`surface = "feed"`)
- **Ordering Warning**: The LinkedIn home feed is algorithmic, not strictly chronological.
- **Exact Timestamp Extraction**: Extract the `data-urn` or permalink URN (`urn:li:activity:<19-digit-id>` or `urn:li:ugcPost:<19-digit-id>`). When passed to `linkcontext upsert posts`, the CLI automatically decodes the 64-bit Snowflake ID (`id >> 22` ms since Unix epoch) into an exact UTC `published_at` with `timestamp_precision = "exact_urn"`.
- **Stopping Rule**: Scroll until `max_items` (e.g., 50 posts) have been inspected or 10 consecutive `post_urn`s are already stored and unchanged. Pass `--since "$CUTOFF"` to `linkcontext upsert posts` so posts older than the cutoff are automatically skipped (`skipped_before_cutoff`).

### B. Notifications (`surface = "notifications"`)
- **Ordering**: Reverse-chronological.
- **Stopping Rule**: Stop scrolling as soon as notification timestamps fall before `lookback_since` or after encountering 5 consecutive already-ingested `notification_key`s.
- **Upsert Example**:
  ```sh
  "/path/to/skills/linkcontext/linkcontext" upsert notifications --sync-run "$SYNC_ID" --since "$CUTOFF" - <<'EOF'
  [
    {
      "notification_key": "urn:li:notification:9001",
      "kind": "post_comment",
      "actor_profile": "<15-char-profile-id>",
      "target_post": "<15-char-post-id>",
      "headline": "Jane Doe commented on your post",
      "snippet": "Great writeup on agentic workflows!",
      "target_url": "https://www.linkedin.com/feed/update/urn:li:activity:7251234567890123456/",
      "is_read_on_linkedin": false,
      "occurred_at": "2026-10-17 09:15:00.000Z"
    }
  ]
  EOF
  ```

### C. Messaging Threads & Messages (`surface = "messages"`)
- **Ordering**: Thread list is ordered by `last_activity_at` descending.
- **Stopping Rule**: Stop scrolling the left-hand thread list once `last_activity_at < lookback_since`. Open only threads with activity $\ge$ `lookback_since` and extract messages with `sent_at >= lookback_since`.
- **Important**: Every `incoming` message must set `sender` to the sender's 15-character `profiles.id`.

### D. Network Connections & Invitations (`surface = "network"` / `"invitations"`)
- **Connections**: Upsert each person into `profiles` (`connection_degree: "first"`, `completeness: "card"`), then upsert into `connections` (`profile: "<id>"`, `relationship_status: "connected"`).
- **Invitations**: Upsert into `invitations` with `direction` (`incoming` or `outgoing`) and `status` (`pending`, `accepted`, `ignored`, `withdrawn`).

### E. Full Profile & Company Detail Pages (`surface = "profile_detail"` / `"company_detail"`)
- Set `"completeness": "full"` and `"last_scraped_at"` when extracting a dedicated `/in/<public_id>` or `/company/<universal_name>` page.
- Subsequent shallow feed/notification extractions (`"completeness": "card"` or `"stub"`) will **never** overwrite the rich fields (`about`, `education_json`, `skills_json`, `email`) of a `"full"` profile.
