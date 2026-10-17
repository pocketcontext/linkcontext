# LinkContext Schema & Domain Rules

## Collections Overview

All writable business collections include server-managed `created_by`, `updated_by`, `revision` ($\ge 1$), `created`, and `updated`. Never supply these fields in `create` or `update` payloads.

### 1. `companies` (LinkedIn Organization / Company Pages)
- **Natural Key**: `universal_name` (unique, lowercase slug from `/company/<universal_name>`)
- **Deterministic ID**: `deterministic_id("companies", universal_name)`
- **Columns**:
  - `name` (required), `universal_name` (required, auto-derived from `linkedin_url` or `name` if omitted), `company_urn`, `linkedin_url`
  - `tagline`, `about`, `website`, `industry`, `company_size`, `headquarters`, `founded_year`
  - `follower_count`, `employee_count_on_linkedin`
  - `completeness`: `stub` | `card` | `full`
  - `crm_organization_id`: optional cached DealContext `organizations.id`
  - `first_seen_at`, `last_seen_at`, `last_scraped_at`, `last_sync_run` ($\to$ `sync_runs`)

### 2. `profiles` (LinkedIn Member Profiles)
- **Natural Key**: `public_id` (unique, lowercase slug from `/in/<public_id>`)
- **Deterministic ID**: `deterministic_id("profiles", public_id)`
- **Columns**:
  - `full_name` (required), `first_name`, `last_name`, `pronouns`
  - `public_id` (required, auto-derived from `linkedin_url` or `full_name` if omitted), `member_urn`, `linkedin_url`
  - `headline`, `about`, `location`, `industry`
  - `current_company` ($\to$ `companies`), `current_title`
  - `connection_degree`: `self` | `first` | `second` | `third` | `out_of_network` | `unknown`
  - `connected_at`, `follower_count`, `connection_count_label`
  - `email`, `phone`, `website`
  - `education_json` (JSON array), `skills_json` (JSON array)
  - `completeness`: `stub` | `card` | `full`
  - `crm_person_id`: optional cached DealContext `people.id`
  - `first_seen_at`, `last_seen_at`, `last_scraped_at`, `last_sync_run` ($\to$ `sync_runs`)

### 3. `experiences` (Profile Career History)
- **Natural Key**: `experience_key` (unique, `<profile>:<company_slug>:<title_slug>:<start_date>`)
- **Columns**:
  - `profile` ($\to$ `profiles`, required), `company` ($\to$ `companies`), `company_name` (required), `title` (required)
  - `employment_type`, `location`, `is_current` (bool), `start_date`, `end_date`, `description`
- **Invariant**: If `is_current = true`, `end_date` must be empty.

### 4. `connections` (1st-Degree Network Metadata)
- **Natural Key**: `profile` ($\to$ `profiles`, unique)
- **Columns**:
  - `profile` (required), `connected_at`, `relationship_status` (`connected` | `following` | `removed`), `notes`, `last_sync_run` ($\to$ `sync_runs`)

### 5. `invitations` (Incoming & Outgoing Connection Requests)
- **Natural Key**: `invitation_key` (unique, `<direction>:<profile>` or LinkedIn invitation URN)
- **Columns**:
  - `profile` ($\to$ `profiles`, required), `direction` (`incoming` | `outgoing`, required)
  - `status` (`pending` | `accepted` | `ignored` | `withdrawn`), `message`, `sent_at`, `resolved_at`, `last_sync_run`
- **Invariant**: `profile` and `direction` are immutable once created. Transitioning `status` to `accepted`, `ignored`, or `withdrawn` auto-populates `resolved_at`.

### 6. `posts` (Timeline / Feed Items & Activity Posts)
- **Natural Key**: `post_urn` (unique, e.g., `urn:li:activity:7251234567890123456`)
- **Deterministic ID**: `deterministic_id("posts", post_urn)`
- **Columns**:
  - `post_urn` (required), `permalink`, `author_type` (`profile` | `company`)
  - `author_profile` ($\to$ `profiles`), `author_company` ($\to$ `companies`)
  - `feed_reason`: `organic` | `connection_liked` | `connection_commented` | `repost` | `suggested` | `promoted` | `profile_activity`
  - `social_actor` ($\to$ `profiles` — the connection whose reaction/comment placed the post in the timeline)
  - `body`, `media_type` (`none` | `image` | `video` | `document` | `article` | `poll` | `event` | `repost`)
  - `shared_url`, `shared_title`, `reposted_post` ($\to$ `posts`)
  - `reaction_count`, `comment_count`, `repost_count`
  - `published_at` (required), `timestamp_precision` (`exact_urn` | `exact_dom` | `relative_approx`)
  - `first_seen_at`, `last_seen_at`, `last_sync_run`
- **Invariant**: Must specify **exactly one** of `author_profile` or `author_company`.

### 7. `post_interactions` (Comments, Replies & Notable Reactions)
- **Natural Key**: `interaction_key` (unique)
- **Columns**:
  - `post` ($\to$ `posts`, required), `actor` ($\to$ `profiles`, required)
  - `kind` (`comment` | `reply` | `reaction` | `repost`, required)
  - `reaction_type` (`like` | `celebrate` | `support` | `love` | `insightful` | `funny` | `none`)
  - `parent_comment_key`, `body`, `occurred_at`, `last_sync_run`
- **Invariants**: `comment` and `reply` require non-empty `body`. `reaction` requires `reaction_type != 'none'`.

### 8. `notifications` (LinkedIn Notifications Feed)
- **Natural Key**: `notification_key` (unique)
- **Columns**:
  - `kind`: `post_reaction` | `post_comment` | `comment_reply` | `mention` | `repost` | `profile_view` | `connection_accepted` | `invitation_received` | `message_received` | `job_change` | `work_anniversary` | `birthday` | `newsletter` | `other`
  - `actor_profile` ($\to$ `profiles`), `actor_company` ($\to$ `companies`), `target_post` ($\to$ `posts`)
  - `headline` (required), `snippet`, `target_url`
  - `is_read_on_linkedin` (bool), `triage_status` (`unreviewed` | `actioned` | `ignored`)
  - `occurred_at` (required), `timestamp_precision`, `last_sync_run`

### 9. `threads`, `thread_participants` & `messages` (Messaging Conversations)
- **`threads`**:
  - `thread_urn` (unique, required), `title` (required), `primary_profile` ($\to$ `profiles`)
  - `is_group`, `is_inmail`, `is_sponsored`, `unread_count`, `last_activity_at`, `last_message_preview`, `crm_deal_id`, `last_sync_run`
- **`thread_participants`**:
  - `thread` ($\to$ `threads`, required), `profile` ($\to$ `profiles`, required), `role` (`member` | `initiator` | `recipient` | `owner`)
  - Unique on `(thread, profile)`
- **`messages`**:
  - `message_key` (unique, required), `thread` ($\to$ `threads`, required), `sender` ($\to$ `profiles`)
  - `direction` (`incoming` | `outgoing`, required), `body` (required), `attachments_json`, `sent_at` (required), `crm_message_id`, `last_sync_run`
  - **Invariant**: `incoming` messages require a `sender` profile.

### 10. `bookmarks` (Saved Collections & Lists)
- **Unique Index**: `(target_collection, target_record_id, list_name)`
- **Columns**:
  - `list_name` (required), `target_collection` (`profiles` | `companies` | `posts` | `threads` | `messages` | `notifications`, required), `target_record_id` (required), `title` (required), `notes`, `status` (`active` | `archived`)
- **Invariant**: `target_record_id` must exist in `target_collection`.

### 11. `sync_runs` (Extraction Run Ledger & Watermarks)
- **Columns**:
  - `surface` (`feed` | `notifications` | `network` | `invitations` | `messages` | `profile_detail` | `company_detail`, required)
  - `status` (`running` | `completed` | `failed` | `partial`, required)
  - `lookback_since`, `max_items`, `started_at`, `completed_at`, `oldest_observed_at`, `newest_observed_at`, `stats_json`, `notes`
- **Invariant**: Completed or failed runs cannot transition back to `running`, and `surface` cannot change.

### 12. Read-Only System Projections
- `user_directory`: `id`, `name`, `created`, `updated`
- `audit_log`: `id`, `collection_name`, `record`, `action`, `actor`, `summary`, `changes`, `created`, `updated`
