function bad(message) { throw new BadRequestError(message); }
function isoNow() { return new Date().toISOString().replace("T", " "); }

function slugify(value) {
  const base = String(value || "")
    .trim()
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "")
    .slice(0, 80);
  return base || "item";
}

function suffixId(record) {
  return String(record.id || Math.random().toString(36).slice(2, 10)).toLowerCase();
}

function extractSlugFromUrl(rawUrl, prefix) {
  const text = String(rawUrl || "").trim();
  if (!text) return "";
  const regex = new RegExp(`/${prefix}/([^/?#]+)`, "i");
  const match = text.match(regex);
  return match && match[1] ? decodeURIComponent(match[1]).trim().toLowerCase() : "";
}

function prepare(app, r) {
  const table = r.collection().name;
  const isCreate = r.isNew();
  const orig = isCreate ? null : r.original();
  const now = isoNow();

  const immutable = ["created_by", "created"];
  if (!isCreate && orig) {
    for (const field of immutable) {
      if (JSON.stringify(r.get(field)) !== JSON.stringify(orig.get(field))) {
        bad(field + " is immutable");
      }
    }
  }

  if (table === "sync_runs") {
    if (!r.getString("status")) r.set("status", "running");
    if (isCreate && !r.getString("started_at")) r.set("started_at", now);
    const status = r.getString("status");
    if (!isCreate && orig) {
      const prevStatus = orig.getString("status");
      if ((prevStatus === "completed" || prevStatus === "failed") && status === "running") {
        bad("Completed or failed sync runs cannot return to running.");
      }
      if (orig.getString("surface") !== r.getString("surface")) {
        bad("Sync run surface cannot change.");
      }
    }
    if ((status === "completed" || status === "failed" || status === "partial") && !r.getString("completed_at")) {
      r.set("completed_at", now);
    }
  }

  if (table === "companies") {
    const name = r.getString("name").trim();
    if (!name) bad("Company name is required.");
    let universal = r.getString("universal_name").trim().toLowerCase();
    if (!universal) {
      universal = extractSlugFromUrl(r.getString("linkedin_url"), "company");
    }
    if (!universal) {
      universal = `${slugify(name)}-${suffixId(r)}`;
    }
    r.set("universal_name", universal);
    if (!r.getString("linkedin_url")) {
      r.set("linkedin_url", `https://www.linkedin.com/company/${encodeURIComponent(universal)}`);
    }
    if (!r.getString("completeness")) r.set("completeness", "stub");
    if (isCreate && !r.getString("first_seen_at")) r.set("first_seen_at", now);
    if (!r.getString("last_seen_at")) r.set("last_seen_at", now);
  }

  if (table === "profiles") {
    const fullName = r.getString("full_name").trim();
    if (!fullName) bad("Profile full_name is required.");
    let publicId = r.getString("public_id").trim().toLowerCase();
    if (!publicId) {
      publicId = extractSlugFromUrl(r.getString("linkedin_url"), "in");
    }
    if (!publicId) {
      publicId = `${slugify(fullName)}-${suffixId(r)}`;
    }
    r.set("public_id", publicId);
    if (!r.getString("linkedin_url")) {
      r.set("linkedin_url", `https://www.linkedin.com/in/${encodeURIComponent(publicId)}`);
    }
    if (!r.getString("connection_degree")) r.set("connection_degree", "unknown");
    if (!r.getString("completeness")) r.set("completeness", "stub");
    if (r.getString("connection_degree") === "first" && isCreate && !r.getString("connected_at")) {
      r.set("connected_at", now);
    }
    if (isCreate && !r.getString("first_seen_at")) r.set("first_seen_at", now);
    if (!r.getString("last_seen_at")) r.set("last_seen_at", now);
  }

  if (table === "experiences") {
    const profile = r.getString("profile");
    const companyName = r.getString("company_name").trim();
    const title = r.getString("title").trim();
    if (!profile || !companyName || !title) {
      bad("Experience requires profile, company_name, and title.");
    }
    if (r.getBool("is_current") && r.getString("end_date").trim()) {
      bad("Current experience cannot have an end_date.");
    }
    if (!r.getString("experience_key").trim()) {
      const start = r.getString("start_date").trim() || "unknown";
      r.set("experience_key", `${profile}:${slugify(companyName)}:${slugify(title)}:${start}`);
    }
  }

  if (table === "connections") {
    if (!r.getString("profile")) bad("Connection requires a profile.");
    if (!r.getString("relationship_status")) r.set("relationship_status", "connected");
    if (isCreate && r.getString("relationship_status") === "connected" && !r.getString("connected_at")) {
      r.set("connected_at", now);
    }
  }

  if (table === "invitations") {
    const profile = r.getString("profile");
    const direction = r.getString("direction");
    if (!profile || !direction) bad("Invitation requires profile and direction.");
    if (!r.getString("status")) r.set("status", "pending");
    if (!r.getString("invitation_key").trim()) {
      r.set("invitation_key", `${direction}:${profile}`);
    }
    if (!isCreate && orig) {
      if (orig.getString("profile") !== profile || orig.getString("direction") !== direction) {
        bad("Invitation profile and direction cannot change.");
      }
    }
    if (isCreate && !r.getString("sent_at")) r.set("sent_at", now);
    const status = r.getString("status");
    if ((status === "accepted" || status === "ignored" || status === "withdrawn") && !r.getString("resolved_at")) {
      r.set("resolved_at", now);
    }
  }

  if (table === "posts") {
    const postUrn = r.getString("post_urn").trim();
    if (!postUrn) bad("Post requires post_urn.");
    const authorProfile = r.getString("author_profile");
    const authorCompany = r.getString("author_company");
    if (Boolean(authorProfile) === Boolean(authorCompany)) {
      bad("Post must specify exactly one of author_profile or author_company.");
    }
    const inferredType = authorCompany ? "company" : "profile";
    if (!r.getString("author_type")) {
      r.set("author_type", inferredType);
    } else if (r.getString("author_type") !== inferredType) {
      bad("Post author_type must match author_profile or author_company.");
    }
    if (!r.getString("permalink")) {
      r.set("permalink", `https://www.linkedin.com/feed/update/${encodeURIComponent(postUrn)}/`);
    }
    if (!r.getString("feed_reason")) r.set("feed_reason", "organic");
    if (!r.getString("media_type")) r.set("media_type", "none");
    if (!r.getString("published_at")) r.set("published_at", now);
    if (!r.getString("timestamp_precision")) r.set("timestamp_precision", "exact_urn");
    if (isCreate && !r.getString("first_seen_at")) r.set("first_seen_at", now);
    if (!r.getString("last_seen_at")) r.set("last_seen_at", now);
  }

  if (table === "post_interactions") {
    const post = r.getString("post");
    const actor = r.getString("actor");
    const kind = r.getString("kind");
    if (!post || !actor || !kind) bad("Post interaction requires post, actor, and kind.");
    if (!r.getString("reaction_type")) {
      r.set("reaction_type", kind === "reaction" ? "like" : "none");
    }
    if ((kind === "comment" || kind === "reply") && !r.getString("body").trim()) {
      bad("Comments and replies require body text.");
    }
    if (kind === "reaction" && r.getString("reaction_type") === "none") {
      bad("Reaction interactions require a reaction_type other than none.");
    }
    if (!r.getString("occurred_at")) r.set("occurred_at", now);
    if (!r.getString("interaction_key").trim()) {
      r.set("interaction_key", `${kind}:${post}:${actor}:${r.getString("occurred_at")}`);
    }
  }

  if (table === "notifications") {
    const kind = r.getString("kind");
    const headline = r.getString("headline").trim();
    if (!kind || !headline) bad("Notification requires kind and headline.");
    if (!r.getString("triage_status")) r.set("triage_status", "unreviewed");
    if (!r.getString("occurred_at")) r.set("occurred_at", now);
    if (!r.getString("timestamp_precision")) r.set("timestamp_precision", "exact_dom");
    if (!r.getString("notification_key").trim()) {
      const actor = r.getString("actor_profile") || r.getString("actor_company") || "system";
      r.set("notification_key", `${kind}:${actor}:${r.getString("occurred_at")}`);
    }
  }

  if (table === "threads") {
    if (!r.getString("thread_urn").trim() || !r.getString("title").trim()) {
      bad("Thread requires thread_urn and title.");
    }
    if (isCreate && !r.getString("last_activity_at")) r.set("last_activity_at", now);
  }

  if (table === "thread_participants") {
    if (!r.getString("thread") || !r.getString("profile")) {
      bad("Thread participant requires thread and profile.");
    }
    if (!r.getString("role")) r.set("role", "member");
  }

  if (table === "messages") {
    const thread = r.getString("thread");
    const direction = r.getString("direction");
    const msgBody = r.getString("body").trim();
    if (!thread || !direction || !msgBody) {
      bad("Message requires thread, direction, and body.");
    }
    if (direction === "incoming" && !r.getString("sender")) {
      bad("Incoming messages require a sender profile.");
    }
    if (!r.getString("sent_at")) r.set("sent_at", now);
    if (!r.getString("message_key").trim()) {
      r.set("message_key", `${thread}:${direction}:${r.getString("sent_at")}:${suffixId(r)}`);
    }
  }

  if (table === "bookmarks") {
    const listName = r.getString("list_name").trim();
    const targetCollection = r.getString("target_collection");
    const targetRecordId = r.getString("target_record_id").trim();
    const title = r.getString("title").trim();
    if (!listName || !targetCollection || !targetRecordId || !title) {
      bad("Bookmark requires list_name, target_collection, target_record_id, and title.");
    }
    if (!r.getString("status")) r.set("status", "active");
    try {
      app.findRecordById(targetCollection, targetRecordId);
    } catch (_) {
      bad("Bookmark target record does not exist.");
    }
  }
}

function write(e) {
  const originalApp = e.app, r = e.record, name = r.collection().name, fresh = r.isNew(), body = e.requestInfo().body;
  originalApp.runInTransaction((app) => {
    e.app = app;
    try {
      if (!fresh) {
        const current = app.findRecordById(name, r.id);
        if (typeof body.expected_revision !== "number" || !Number.isInteger(body.expected_revision)) {
          bad("expected_revision is required as an integer");
        }
        if (current.getInt("revision") !== body.expected_revision || current.getInt("revision") !== r.original().getInt("revision")) {
          throw new ApiError(409, "Revision conflict; read the record again before retrying.", {});
        }
      }
      const actor = e.auth && e.auth.collection().name === "users" ? e.auth.id : "";
      for (const field of ["revision", "created_by", "updated_by", "created", "updated"]) {
        if (Object.prototype.hasOwnProperty.call(body, field)) bad(field + " is server managed");
      }
      const before = fresh ? null : snapshot(r.original());
      r.set("revision", fresh ? 1 : r.original().getInt("revision") + 1);
      r.set("created_by", fresh ? actor : r.original().getString("created_by"));
      r.set("updated_by", actor);
      prepare(app, r);
      e.next();
      const after = snapshot(r);
      const changes = fresh ? {after} : {before: {}, after: {}};
      if (before) {
        for (const field in after) {
          if (JSON.stringify(before[field]) !== JSON.stringify(after[field])) {
            changes.before[field] = before[field];
            changes.after[field] = after[field];
          }
        }
      }
      const row = new Record(app.findCollectionByNameOrId("audit_log"));
      const label = r.getString("name") || r.getString("full_name") || r.getString("title") || r.getString("headline") || r.getString("post_urn") || r.id;
      row.set("action", fresh ? "create" : "update");
      row.set("collection_name", name);
      row.set("record", r.id);
      if (actor) row.set("actor", actor);
      row.set("summary", `${fresh ? "Created" : "Updated"} ${name} ${label}`.slice(0, 500));
      row.set("changes", changes);
      app.save(row);
    } finally {
      e.app = originalApp;
    }
  });
}

function snapshot(r) {
  const all = JSON.parse(JSON.stringify(r)), out = {};
  for (const f of r.collection().fields.fieldNames()) out[f] = all[f];
  return out;
}

module.exports = {prepare, write};
