# Cross-Referencing LinkContext with DealContext (CRM) & WikiContext

Use this guide when answering questions that span LinkedIn (`linkcontext`), the CRM (`dealcontext`), and the knowledge base (`wikicontext`).

## 1. Identity Resolution Between `LinkContext` and `DealContext`

`LinkContext` stores canonical LinkedIn slugs and optional soft-reference cache columns pointing to `DealContext` record IDs:

| LinkContext Table & Column | DealContext Table & Column | Matching Key |
| :--- | :--- | :--- |
| `profiles.crm_person_id` | `people.id` | Normalize `dealcontext.people.linkedin_url` $\to$ `/in/<public_id>` == `linkcontext.profiles.public_id`, or match `LOWER(email)` |
| `companies.crm_organization_id` | `organizations.id` | Normalize `website` host or `LOWER(name)` |
| `threads.crm_deal_id` | `deals.id` | Primary participant's open deal in `DealContext` |
| `messages.crm_message_id` | `messages.id` | Synced LinkedIn correspondence (`channel = 'linkedin'`) |

### Reconciling Identities (Python One-Liner Pattern)
When asked to cross-reference LinkedIn activity with CRM deals or contacts:
1. Query `linkcontext` for profiles/companies/messages/notifications:
   ```sh
   "/path/to/skills/linkcontext/linkcontext" query "SELECT id, full_name, public_id, linkedin_url, headline, current_title, crm_person_id FROM profiles"
   ```
2. Query `dealcontext` for people, organizations, and open deals:
   ```sh
   "/path/to/skills/dealcontext/dealcontext" query "SELECT id, name, email, organization, linkedin_url FROM people WHERE archived = 0"
   ```
3. When a match is found on `/in/<public_id>` or `email` and `crm_person_id` is empty in `LinkContext`, cache it via `linkcontext upsert profiles`:
   ```sh
   "/path/to/skills/linkcontext/linkcontext" upsert profiles '[{"public_id":"jane-doe","full_name":"Jane Doe","crm_person_id":"<dealcontext-person-id>"}]'
   ```

---

## 2. Common Cross-System Analytical Queries

### A. Active CRM Deals with Recent LinkedIn Touchpoints
Find people on open CRM deals who sent LinkedIn messages, accepted invitations, or interacted with posts recently:

```sql
-- Run against LinkContext:
SELECT
  p.id AS profile_id,
  p.full_name,
  p.public_id,
  p.crm_person_id,
  m.id AS message_id,
  m.direction,
  m.sent_at,
  m.body,
  m.crm_message_id
FROM messages m
JOIN threads t ON t.id = m.thread
JOIN profiles p ON p.id = COALESCE(m.sender, t.primary_profile)
WHERE p.crm_person_id != ''
ORDER BY m.sent_at DESC
LIMIT 50;
```

### B. Warm Intro & Career Overlap Discovery
Find 1st-degree connections who currently or previously worked at a target CRM account:

```sql
-- Run against LinkContext:
SELECT
  p.id AS profile_id,
  p.full_name,
  p.public_id,
  p.headline,
  e.company_name,
  e.title,
  e.is_current,
  e.start_date,
  e.end_date
FROM experiences e
JOIN profiles p ON p.id = e.profile
WHERE p.connection_degree = 'first'
  AND LOWER(e.company_name) LIKE '%acme%'
ORDER BY e.is_current DESC, e.start_date DESC;
```

### C. High-Signal Engagement on Timeline Posts
Identify non-first-degree prospects or CRM contacts who commented on or reacted to relevant posts:

```sql
-- Run against LinkContext:
SELECT
  pi.kind,
  pi.reaction_type,
  pi.body AS comment_body,
  pi.occurred_at,
  p.id AS actor_id,
  p.full_name,
  p.headline,
  p.connection_degree,
  p.crm_person_id,
  post.id AS post_id,
  post.post_urn
FROM post_interactions pi
JOIN profiles p ON p.id = pi.actor
JOIN posts post ON post.id = pi.post
ORDER BY pi.occurred_at DESC
LIMIT 50;
```

---

## 3. Embedding Permanent Links in DealContext & WikiContext

Every `LinkContext` record has a permanent reader URL:
- Localhost (Phase 1): `http://localhost:8095/#/<collection>/<15-char-id>`
- Future Cloud (Phase 2): `https://link.pocketcontext.com/#/<collection>/<15-char-id>`

When logging a LinkedIn message into `DealContext` (`messages` or `notes`) or citing LinkedIn market intelligence in `WikiContext`, always include the `LinkContext` permalink (`/#/<collection>/<id>`) alongside the external LinkedIn URL so humans can inspect the full captured context in the `LinkContext` Reader UI.
