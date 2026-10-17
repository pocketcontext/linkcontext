/// <reference path="../pb_data/types.d.ts" />
const RULES = [
  {label: "*:auth", audience: "", duration: 60, maxRequests: 10},
  {label: "/api/batch", audience: "", duration: 10, maxRequests: 10},
  {label: "/api/context/", audience: "", duration: 10, maxRequests: 60},
  {label: "/api/", audience: "", duration: 10, maxRequests: 300},
];

function env(name) {
  return String($os.getenv(name) || "").trim();
}

function up(e) {
  try {
    const row = new DynamicModel({n: 0});
    e.app.db().newQuery("SELECT count(*) AS n FROM _collections").one(row);
  } catch (error) {
    throw new ApiError(503, "The database is not available.", {});
  }
  return e.string(200, "OK");
}

function settings(app) {
  require(`${__hooks}/storage.js`).configure(app, false);
  const group = (name, detail, change) => {
    const current = app.settings(), changed = [];
    const set = (section, key, value) => {
      if (JSON.stringify(current[section][key]) === JSON.stringify(value)) return;
      current[section][key] = value;
      changed.push(section + "." + key);
    };
    try {
      change(set, current);
      if (changed.length === 0) return;
      app.save(current);
      console.log("deploy: applied " + name + " from the environment (" + detail + "); changed: " + changed.join(", "));
    } catch (error) {
      console.log("deploy: could not apply " + name + " from the environment; stored settings kept: " + error);
      app.reloadSettings();
    }
  };

  const url = env("BASE_URL"), sender = env("MAILER_FROM_ADDRESS");
  if (url) {
    group("application URL", "BASE_URL " + url, (set) => set("meta", "appURL", url.replace(/\/+$/, "")));
  }
  if (sender) {
    const named = /^\s*"?([^"<]*?)"?\s*<([^<>\s]+)>\s*$/.exec(sender);
    group("sender", "MAILER_FROM_ADDRESS set", (set) => {
      set("meta", "senderAddress", named ? named[2] : sender.trim());
      if (named && named[1]) set("meta", "senderName", named[1]);
    });
  }

  const host = env("SMTP_ADDRESS");
  if (host) {
    const port = env("SMTP_PORT") ? parseInt(env("SMTP_PORT"), 10) : 587;
    const username = env("SMTP_USERNAME"), password = env("SMTP_PASSWORD");
    const detail = "host " + host + ", port " + port + ", username " + (username ? "set" : "empty") + ", password " + (password ? "set" : "empty");
    group("SMTP settings", detail, (set) => {
      if (!(port > 0 && port < 65536)) throw new Error("SMTP_PORT is not a port number");
      set("smtp", "enabled", true);
      set("smtp", "host", host);
      set("smtp", "port", port);
      set("smtp", "username", username);
      set("smtp", "password", password);
      set("smtp", "tls", port === 465);
    });
  }

  const header = env("LINKCONTEXT_TRUSTED_PROXY_HEADER");
  if (header) {
    group("trusted proxy header", header, (set) => {
      set("trustedProxy", "headers", [header]);
      set("trustedProxy", "useLeftmostIP", false);
    });
  }

  const limits = env("LINKCONTEXT_RATE_LIMITS");
  if (limits === "true") {
    group("rate limits", "enabled, " + RULES.length + " rules", (set) => {
      set("rateLimits", "rules", RULES);
      set("rateLimits", "enabled", true);
    });
  } else if (limits === "false") {
    group("rate limits", "disabled", (set) => set("rateLimits", "enabled", false));
  } else if (limits) {
    console.log("deploy: LINKCONTEXT_RATE_LIMITS must be true or false; rate limit settings left alone");
  }
}

function googleOAuth(app) {
  const clientId = String($os.getenv("LINKCONTEXT_GOOGLE_CLIENT_ID") || "");
  const clientSecret = String($os.getenv("LINKCONTEXT_GOOGLE_CLIENT_SECRET") || "");
  if (!clientId && !clientSecret) return;
  if (!clientId.trim() || !clientSecret.trim()) {
    throw new Error("LINKCONTEXT_GOOGLE_CLIENT_ID and LINKCONTEXT_GOOGLE_CLIENT_SECRET must be set together");
  }
  if (/\s/.test(clientId) || /\s/.test(clientSecret)) {
    throw new Error("LinkContext Google OAuth credentials must not contain whitespace");
  }
  try {
    const users = app.findCollectionByNameOrId("users");
    const providers = JSON.parse(JSON.stringify(users.oauth2.providers || []));
    let google = providers.find(provider => provider.name === "google");
    if (google && users.oauth2.enabled && google.clientId === clientId && google.clientSecret === clientSecret) return;
    if (!google) {
      google = {name: "google"};
      providers.push(google);
    }
    google.clientId = clientId;
    google.clientSecret = clientSecret;
    users.oauth2.providers = providers;
    users.oauth2.enabled = true;
    app.save(users);
    console.log("deploy: applied Google OAuth from the environment");
  } catch (_) {
    throw new Error("Could not apply LinkContext Google OAuth configuration; server startup stopped");
  }
}

function localBootstrap(app) {
  const email = env("LINKCONTEXT_LOCAL_USER_EMAIL").toLowerCase();
  const password = String($os.getenv("LINKCONTEXT_LOCAL_USER_PASSWORD") || "");
  if (!email && !password) return;
  if (!email || !password.trim()) {
    throw new Error("LINKCONTEXT_LOCAL_USER_EMAIL and LINKCONTEXT_LOCAL_USER_PASSWORD must be set together");
  }
  const name = env("LINKCONTEXT_LOCAL_USER_NAME") || "Local Agent";
  let user = null;
  try {
    user = app.findAuthRecordByEmail("users", email);
  } catch (_) {}
  if (!user) {
    const users = app.findCollectionByNameOrId("users");
    user = new Record(users);
    user.setEmail(email);
  }
  user.set("name", name);
  user.set("disabled", false);
  user.setVerified(true);
  user.setPassword(password);
  app.save(user);
}

module.exports = {up, settings, googleOAuth, localBootstrap, RULES};
