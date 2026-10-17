migrate((app) => {
  app.findCollectionByNameOrId("users");
  const auth = "@request.auth.id != '' && @request.auth.collectionName = 'users' && @request.auth.disabled = false";
  const text = (name, required = false, max = 500) => ({ name, type: "text", required, max });
  const num = (name, min = 0, onlyInt = true, required = false) => ({ name, type: "number", min, onlyInt, required });
  const bool = (name) => ({ name, type: "bool" });
  const date = (name, required = false) => ({ name, type: "date", required });
  const url = (name) => ({ name, type: "url" });
  const email = (name) => ({ name, type: "email" });
  const json = (name) => ({ name, type: "json", maxSize: 262144 });
  const sel = (name, values, required = false) => ({ name, type: "select", values, maxSelect: 1, required });
  const rel = (name, collection, required = false) => ({
    name,
    type: "relation",
    collectionId: app.findCollectionByNameOrId(collection).id,
    maxSelect: 1,
    required,
    cascadeDelete: false,
  });

  function save(name, fields, indexes = [], readOnly = false) {
    const collection = new Collection({
      type: "base",
      name,
      listRule: auth,
      viewRule: auth,
      createRule: readOnly ? null : auth,
      updateRule: readOnly ? null : auth,
      deleteRule: null,
      fields: fields.concat(
        readOnly ? [] : [
          rel("created_by", "users"),
          rel("updated_by", "users"),
          { name: "revision", type: "number", min: 1, onlyInt: true, required: true },
        ],
        [
          { name: "created", type: "autodate", onCreate: true, onUpdate: false },
          { name: "updated", type: "autodate", onCreate: true, onUpdate: true },
        ],
      ),
      indexes,
    });
    app.save(collection);
    return collection;
  }

  save("user_directory", [text("name", true, 200)], [], true);

  save("sync_runs", [
    sel("surface", ["feed", "notifications", "network", "invitations", "messages", "profile_detail", "company_detail"], true),
    sel("status", ["running", "completed", "failed", "partial"], true),
    date("lookback_since"),
    num("max_items", 1, true),
    date("started_at"),
    date("completed_at"),
    date("oldest_observed_at"),
    date("newest_observed_at"),
    json("stats_json"),
    text("notes", false, 10000),
  ], [
    "CREATE INDEX idx_sync_runs_surface ON sync_runs (surface, status)",
  ]);

  save("companies", [
    text("name", true, 300),
    text("universal_name", true, 200),
    text("company_urn", false, 200),
    url("linkedin_url"),
    text("tagline", false, 1000),
    text("about", false, 20000),
    url("website"),
    text("industry", false, 200),
    text("company_size", false, 100),
    text("headquarters", false, 300),
    num("founded_year", 0, true),
    num("follower_count", 0, true),
    num("employee_count_on_linkedin", 0, true),
    sel("completeness", ["stub", "card", "full"], true),
    text("crm_organization_id", false, 64),
    date("first_seen_at"),
    date("last_seen_at"),
    date("last_scraped_at"),
    rel("last_sync_run", "sync_runs"),
  ], [
    "CREATE UNIQUE INDEX idx_companies_universal_name ON companies (universal_name)",
    "CREATE INDEX idx_companies_urn ON companies (company_urn)",
    "CREATE INDEX idx_companies_crm ON companies (crm_organization_id)",
  ]);

  save("profiles", [
    text("full_name", true, 300),
    text("first_name", false, 150),
    text("last_name", false, 150),
    text("pronouns", false, 60),
    text("public_id", true, 200),
    text("member_urn", false, 200),
    url("linkedin_url"),
    text("headline", false, 1000),
    text("about", false, 20000),
    text("location", false, 300),
    text("industry", false, 200),
    rel("current_company", "companies"),
    text("current_title", false, 300),
    sel("connection_degree", ["self", "first", "second", "third", "out_of_network", "unknown"], true),
    date("connected_at"),
    num("follower_count", 0, true),
    text("connection_count_label", false, 60),
    email("email"),
    text("phone", false, 100),
    url("website"),
    json("education_json"),
    json("skills_json"),
    sel("completeness", ["stub", "card", "full"], true),
    text("crm_person_id", false, 64),
    date("first_seen_at"),
    date("last_seen_at"),
    date("last_scraped_at"),
    rel("last_sync_run", "sync_runs"),
  ], [
    "CREATE UNIQUE INDEX idx_profiles_public_id ON profiles (public_id)",
    "CREATE INDEX idx_profiles_member_urn ON profiles (member_urn)",
    "CREATE INDEX idx_profiles_company ON profiles (current_company)",
    "CREATE INDEX idx_profiles_crm ON profiles (crm_person_id)",
  ]);

  save("experiences", [
    text("experience_key", true, 300),
    rel("profile", "profiles", true),
    rel("company", "companies"),
    text("company_name", true, 300),
    text("title", true, 300),
    text("employment_type", false, 100),
    text("location", false, 300),
    bool("is_current"),
    text("start_date", false, 40),
    text("end_date", false, 40),
    text("description", false, 10000),
  ], [
    "CREATE UNIQUE INDEX idx_experiences_key ON experiences (experience_key)",
    "CREATE INDEX idx_experiences_profile ON experiences (profile)",
    "CREATE INDEX idx_experiences_company ON experiences (company)",
  ]);

  save("connections", [
    rel("profile", "profiles", true),
    date("connected_at"),
    sel("relationship_status", ["connected", "following", "removed"], true),
    text("notes", false, 10000),
    rel("last_sync_run", "sync_runs"),
  ], [
    "CREATE UNIQUE INDEX idx_connections_profile ON connections (profile)",
  ]);

  save("invitations", [
    text("invitation_key", true, 300),
    rel("profile", "profiles", true),
    sel("direction", ["incoming", "outgoing"], true),
    sel("status", ["pending", "accepted", "ignored", "withdrawn"], true),
    text("message", false, 2000),
    date("sent_at"),
    date("resolved_at"),
    rel("last_sync_run", "sync_runs"),
  ], [
    "CREATE UNIQUE INDEX idx_invitations_key ON invitations (invitation_key)",
    "CREATE INDEX idx_invitations_profile ON invitations (profile)",
  ]);

  const posts = save("posts", [
    text("post_urn", true, 300),
    url("permalink"),
    sel("author_type", ["profile", "company"], true),
    rel("author_profile", "profiles"),
    rel("author_company", "companies"),
    sel("feed_reason", ["organic", "connection_liked", "connection_commented", "repost", "suggested", "promoted", "profile_activity"], true),
    rel("social_actor", "profiles"),
    text("body", false, 50000),
    sel("media_type", ["none", "image", "video", "document", "article", "poll", "event", "repost"], true),
    url("shared_url"),
    text("shared_title", false, 500),
    num("reaction_count", 0, true),
    num("comment_count", 0, true),
    num("repost_count", 0, true),
    date("published_at", true),
    sel("timestamp_precision", ["exact_urn", "exact_dom", "relative_approx"], true),
    date("first_seen_at"),
    date("last_seen_at"),
    rel("last_sync_run", "sync_runs"),
  ], [
    "CREATE UNIQUE INDEX idx_posts_urn ON posts (post_urn)",
    "CREATE INDEX idx_posts_author_profile ON posts (author_profile)",
    "CREATE INDEX idx_posts_author_company ON posts (author_company)",
  ]);
  posts.fields.add(new RelationField({
    name: "reposted_post",
    collectionId: posts.id,
    maxSelect: 1,
    required: false,
    cascadeDelete: false,
  }));
  app.save(posts);

  save("post_interactions", [
    text("interaction_key", true, 300),
    rel("post", "posts", true),
    rel("actor", "profiles", true),
    sel("kind", ["comment", "reply", "reaction", "repost"], true),
    sel("reaction_type", ["like", "celebrate", "support", "love", "insightful", "funny", "none"], true),
    text("parent_comment_key", false, 300),
    text("body", false, 20000),
    date("occurred_at"),
    rel("last_sync_run", "sync_runs"),
  ], [
    "CREATE UNIQUE INDEX idx_post_interactions_key ON post_interactions (interaction_key)",
    "CREATE INDEX idx_post_interactions_post ON post_interactions (post)",
    "CREATE INDEX idx_post_interactions_actor ON post_interactions (actor)",
  ]);

  save("notifications", [
    text("notification_key", true, 300),
    sel("kind", ["post_reaction", "post_comment", "comment_reply", "mention", "repost", "profile_view", "connection_accepted", "invitation_received", "message_received", "job_change", "work_anniversary", "birthday", "newsletter", "other"], true),
    rel("actor_profile", "profiles"),
    rel("actor_company", "companies"),
    rel("target_post", "posts"),
    text("headline", true, 2000),
    text("snippet", false, 5000),
    url("target_url"),
    bool("is_read_on_linkedin"),
    sel("triage_status", ["unreviewed", "actioned", "ignored"], true),
    date("occurred_at", true),
    sel("timestamp_precision", ["exact_urn", "exact_dom", "relative_approx"], true),
    rel("last_sync_run", "sync_runs"),
  ], [
    "CREATE UNIQUE INDEX idx_notifications_key ON notifications (notification_key)",
    "CREATE INDEX idx_notifications_actor ON notifications (actor_profile)",
  ]);

  save("threads", [
    text("thread_urn", true, 300),
    text("title", true, 300),
    rel("primary_profile", "profiles"),
    bool("is_group"),
    bool("is_inmail"),
    bool("is_sponsored"),
    num("unread_count", 0, true),
    date("last_activity_at"),
    text("last_message_preview", false, 2000),
    text("crm_deal_id", false, 64),
    rel("last_sync_run", "sync_runs"),
  ], [
    "CREATE UNIQUE INDEX idx_threads_urn ON threads (thread_urn)",
    "CREATE INDEX idx_threads_primary_profile ON threads (primary_profile)",
  ]);

  save("thread_participants", [
    rel("thread", "threads", true),
    rel("profile", "profiles", true),
    sel("role", ["member", "initiator", "recipient", "owner"], true),
  ], [
    "CREATE UNIQUE INDEX idx_thread_participants_unique ON thread_participants (thread, profile)",
  ]);

  save("messages", [
    text("message_key", true, 300),
    rel("thread", "threads", true),
    rel("sender", "profiles"),
    sel("direction", ["incoming", "outgoing"], true),
    text("body", true, 50000),
    json("attachments_json"),
    date("sent_at", true),
    text("crm_message_id", false, 64),
    rel("last_sync_run", "sync_runs"),
  ], [
    "CREATE UNIQUE INDEX idx_messages_key ON messages (message_key)",
    "CREATE INDEX idx_messages_thread ON messages (thread)",
    "CREATE INDEX idx_messages_sender ON messages (sender)",
  ]);

  save("bookmarks", [
    text("list_name", true, 120),
    sel("target_collection", ["profiles", "companies", "posts", "threads", "messages", "notifications"], true),
    text("target_record_id", true, 64),
    text("title", true, 300),
    text("notes", false, 10000),
    sel("status", ["active", "archived"], true),
  ], [
    "CREATE UNIQUE INDEX idx_bookmarks_unique ON bookmarks (target_collection, target_record_id, list_name)",
  ]);

  save("audit_log", [
    text("collection_name", true, 80),
    text("record", true, 64),
    sel("action", ["create", "update"], true),
    rel("actor", "users"),
    text("summary", true, 500),
    json("changes"),
  ], ["CREATE INDEX idx_audit_record ON audit_log (collection_name, record)"], true);

  const settings = app.settings();
  settings.batch.enabled = true;
  settings.batch.maxRequests = 20;
  settings.batch.timeout = 5;
  app.save(settings);
}, () => {
  throw new Error("Restore a verified backup to roll back the initial schema.");
});
