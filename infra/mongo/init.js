// HomeAI Cloud — MongoDB bootstrap (local dev).
// Owner: Renuka (P0-5). Source of truth: docs/02_CONTRACTS.md section 5.2.
//
// Runs once on first container start via /docker-entrypoint-initdb.d/.
// The mongo:7 image runs *.js files with the admin user from
// MONGO_INITDB_ROOT_USERNAME/PASSWORD already authenticated.
//
// Collections and their owners (contracts 5.2):
//   media_events      c1_app inserts; c3_app updates processing fields; c3/c4 read
//   ai_detections     c3_app readWrite; c2_reader + c4 read
//   activity_patterns c3_app readWrite; c4 reads
//   dashboard_stats_daily  c4_app readWrite
//
// Built-in roles are database-scoped: each owner gets readWrite on `homeai`, and
// isolation between owners is enforced in application code (each service only
// writes its own collections). C2's reader gets a custom role limited to `find`
// on ai_detections.

const dbName = "homeai";
const pwd = "devpass"; // dev only; AWS reads real secrets from Secrets Manager

const appDb = db.getSiblingDB(dbName);

function ensureUser(username, roles) {
  const existing = appDb.getUser(username);
  if (existing) {
    print(`[mongo-init] user ${username} already exists; updating roles`);
    appDb.updateUser(username, { roles: roles });
  } else {
    print(`[mongo-init] creating user ${username}`);
    appDb.createUser({ user: username, pwd: pwd, roles: roles });
  }
}

// Owners: read/write on the homeai database.
ensureUser("c1_app", [{ role: "readWrite", db: dbName }]);
ensureUser("c3_app", [{ role: "readWrite", db: dbName }]);
ensureUser("c4_app", [{ role: "readWrite", db: dbName }]);

// Reader: C2 may only read ai_detections (contracts 5.2), so it gets a custom
// role with `find` on that one collection instead of the database-wide `read`.
// (Health checks use `ping`, which needs no privilege.)
const detectionsReader = "aiDetectionsRead";
const detectionsPrivileges = [
  { resource: { db: dbName, collection: "ai_detections" }, actions: ["find"] },
];
if (appDb.getRole(detectionsReader)) {
  appDb.updateRole(detectionsReader, { privileges: detectionsPrivileges, roles: [] });
} else {
  appDb.createRole({ role: detectionsReader, privileges: detectionsPrivileges, roles: [] });
}
ensureUser("c2_reader", [{ role: detectionsReader, db: dbName }]);

// Touch the core collections so they exist immediately (indexes are created by
// the owning services' startup code — C1 for media_events, C3 for detections).
appDb.createCollection("media_events");
appDb.createCollection("ai_detections");
appDb.createCollection("activity_patterns");
appDb.createCollection("worker_heartbeats");
appDb.createCollection("dashboard_stats_daily");

print("[mongo-init] done: users and collections ready on 'homeai'");
