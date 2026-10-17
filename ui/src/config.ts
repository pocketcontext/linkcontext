export interface Entity {
  table: string;
  label: string;
  menu?: boolean;
  title: string[];
  subtitle?: string[];
  search: string[];
  filters?: Record<string, string[]>;
  hidden?: string[];
  markdown?: string[];
  money?: Record<string, string>;
  relations?: Record<string, string>;
  relationLabels?: Record<string, string>;
  reverseLabels?: Record<string, string>;
}
export const app: {
  name: string;
  authCollection: string;
  google?: boolean;
  entities: Entity[];
} =
  {
    name: "LinkContext",
    authCollection: "users",
    entities: [
      {
        table: "profiles",
        label: "Profiles",
        title: ["full_name", "public_id"],
        subtitle: ["connection_degree", "current_title", "completeness"],
        search: [
          "full_name",
          "public_id",
          "headline",
          "about",
          "location",
          "industry",
          "current_title",
          "email",
          "crm_person_id",
        ],
        filters: {
          connection_degree: [
            "self",
            "first",
            "second",
            "third",
            "out_of_network",
            "unknown",
          ],
          completeness: ["stub", "card", "full"],
        },
        markdown: ["about"],
        relations: {
          current_company: "companies",
          last_sync_run: "sync_runs",
          created_by: "user_directory",
          updated_by: "user_directory",
        },
        reverseLabels: {
          "experiences.profile": "Work history",
          "connections.profile": "1st-degree connection",
          "invitations.profile": "Invitations",
          "posts.author_profile": "Authored posts",
          "posts.social_actor": "Timeline social activity",
          "post_interactions.actor": "Comments & reactions",
          "notifications.actor_profile": "Notifications from profile",
          "threads.primary_profile": "1:1 Threads",
          "thread_participants.profile": "Thread memberships",
          "messages.sender": "Sent messages",
        },
      },
      {
        table: "companies",
        label: "Companies",
        title: ["name", "universal_name"],
        subtitle: ["industry", "company_size", "completeness"],
        search: [
          "name",
          "universal_name",
          "tagline",
          "about",
          "website",
          "industry",
          "headquarters",
          "crm_organization_id",
        ],
        filters: {
          completeness: ["stub", "card", "full"],
        },
        markdown: ["about"],
        relations: {
          last_sync_run: "sync_runs",
          created_by: "user_directory",
          updated_by: "user_directory",
        },
        reverseLabels: {
          "profiles.current_company": "Current profiles",
          "experiences.company": "Experience history",
          "posts.author_company": "Company posts",
          "notifications.actor_company": "Company notifications",
        },
      },
      {
        table: "posts",
        label: "Timeline Posts",
        title: ["post_urn"],
        subtitle: ["author_type", "feed_reason", "media_type", "published_at"],
        search: [
          "post_urn",
          "body",
          "shared_title",
          "shared_url",
          "permalink",
        ],
        filters: {
          author_type: ["profile", "company"],
          feed_reason: [
            "organic",
            "connection_liked",
            "connection_commented",
            "repost",
            "suggested",
            "promoted",
            "profile_activity",
          ],
          media_type: [
            "none",
            "image",
            "video",
            "document",
            "article",
            "poll",
            "event",
            "repost",
          ],
        },
        markdown: ["body"],
        relations: {
          author_profile: "profiles",
          author_company: "companies",
          social_actor: "profiles",
          reposted_post: "posts",
          last_sync_run: "sync_runs",
          created_by: "user_directory",
          updated_by: "user_directory",
        },
        reverseLabels: {
          "post_interactions.post": "Interactions (comments & reactions)",
          "notifications.target_post": "Notifications",
          "posts.reposted_post": "Reposts",
        },
      },
      {
        table: "post_interactions",
        label: "Post Interactions",
        title: ["kind", "interaction_key"],
        subtitle: ["kind", "reaction_type", "occurred_at"],
        search: ["interaction_key", "body", "parent_comment_key"],
        filters: {
          kind: ["comment", "reply", "reaction", "repost"],
          reaction_type: [
            "like",
            "celebrate",
            "support",
            "love",
            "insightful",
            "funny",
            "none",
          ],
        },
        markdown: ["body"],
        relations: {
          post: "posts",
          actor: "profiles",
          last_sync_run: "sync_runs",
          created_by: "user_directory",
          updated_by: "user_directory",
        },
      },
      {
        table: "notifications",
        label: "Notifications",
        title: ["headline"],
        subtitle: ["kind", "triage_status", "occurred_at"],
        search: ["headline", "snippet", "notification_key", "target_url"],
        filters: {
          triage_status: ["unreviewed", "actioned", "ignored"],
          kind: [
            "post_reaction",
            "post_comment",
            "comment_reply",
            "mention",
            "repost",
            "profile_view",
            "connection_accepted",
            "invitation_received",
            "message_received",
            "job_change",
            "work_anniversary",
            "birthday",
            "newsletter",
            "other",
          ],
        },
        markdown: ["snippet"],
        relations: {
          actor_profile: "profiles",
          actor_company: "companies",
          target_post: "posts",
          last_sync_run: "sync_runs",
          created_by: "user_directory",
          updated_by: "user_directory",
        },
      },
      {
        table: "threads",
        label: "Messaging Threads",
        title: ["title", "thread_urn"],
        subtitle: ["last_activity_at", "unread_count"],
        search: ["title", "thread_urn", "last_message_preview", "crm_deal_id"],
        relations: {
          primary_profile: "profiles",
          last_sync_run: "sync_runs",
          created_by: "user_directory",
          updated_by: "user_directory",
        },
        reverseLabels: {
          "thread_participants.thread": "Participants",
          "messages.thread": "Messages",
        },
      },
      {
        table: "messages",
        label: "Messages",
        title: ["direction", "sent_at"],
        subtitle: ["direction", "sent_at"],
        search: ["body", "message_key", "crm_message_id"],
        filters: {
          direction: ["incoming", "outgoing"],
        },
        markdown: ["body"],
        relations: {
          thread: "threads",
          sender: "profiles",
          last_sync_run: "sync_runs",
          created_by: "user_directory",
          updated_by: "user_directory",
        },
      },
      {
        table: "invitations",
        label: "Invitations",
        title: ["direction", "invitation_key"],
        subtitle: ["direction", "status", "sent_at"],
        search: ["invitation_key", "message"],
        filters: {
          direction: ["incoming", "outgoing"],
          status: ["pending", "accepted", "ignored", "withdrawn"],
        },
        markdown: ["message"],
        relations: {
          profile: "profiles",
          last_sync_run: "sync_runs",
          created_by: "user_directory",
          updated_by: "user_directory",
        },
      },
      {
        table: "connections",
        label: "Connections",
        title: ["relationship_status", "connected_at"],
        subtitle: ["relationship_status", "connected_at"],
        search: ["notes"],
        filters: {
          relationship_status: ["connected", "following", "removed"],
        },
        markdown: ["notes"],
        relations: {
          profile: "profiles",
          last_sync_run: "sync_runs",
          created_by: "user_directory",
          updated_by: "user_directory",
        },
      },
      {
        table: "experiences",
        label: "Experiences",
        title: ["title", "company_name"],
        subtitle: ["company_name", "start_date", "end_date"],
        search: ["title", "company_name", "location", "description", "experience_key"],
        markdown: ["description"],
        relations: {
          profile: "profiles",
          company: "companies",
          created_by: "user_directory",
          updated_by: "user_directory",
        },
      },
      {
        table: "bookmarks",
        label: "Bookmarks",
        title: ["title", "list_name"],
        subtitle: ["list_name", "target_collection", "status"],
        search: ["title", "list_name", "target_record_id", "notes"],
        filters: {
          target_collection: [
            "profiles",
            "companies",
            "posts",
            "threads",
            "messages",
            "notifications",
          ],
          status: ["active", "archived"],
        },
        markdown: ["notes"],
        relations: {
          created_by: "user_directory",
          updated_by: "user_directory",
        },
      },
      {
        table: "sync_runs",
        label: "Sync Runs",
        title: ["surface", "started_at"],
        subtitle: ["surface", "status", "lookback_since"],
        search: ["surface", "status", "notes"],
        filters: {
          surface: [
            "feed",
            "notifications",
            "network",
            "invitations",
            "messages",
            "profile_detail",
            "company_detail",
          ],
          status: ["running", "completed", "failed", "partial"],
        },
        markdown: ["notes"],
        relations: {
          created_by: "user_directory",
          updated_by: "user_directory",
        },
      },
      {
        table: "thread_participants",
        label: "Thread Participants",
        menu: false,
        title: ["role"],
        subtitle: ["role"],
        search: ["role"],
        relations: {
          thread: "threads",
          profile: "profiles",
          created_by: "user_directory",
          updated_by: "user_directory",
        },
      },
      {
        table: "user_directory",
        label: "Users",
        menu: false,
        title: ["name"],
        search: ["name"],
      },
    ],
  };
