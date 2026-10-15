CREATE TABLE IF NOT EXISTS approvals(
  id INTEGER PRIMARY KEY, session_id TEXT NOT NULL, invocation_id TEXT NOT NULL, request_id TEXT NOT NULL,
  tool TEXT NOT NULL, args_json TEXT NOT NULL, summary TEXT NOT NULL, detail_json TEXT, provenance_json TEXT,
  status TEXT NOT NULL CHECK(status IN ('pending','approved','rejected','expired')) DEFAULT 'pending',
  created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')), decided_at TEXT, result_text TEXT);
CREATE TABLE IF NOT EXISTS tasks(
  id INTEGER PRIMARY KEY, title TEXT NOT NULL,
  kind TEXT NOT NULL CHECK(kind IN ('waiting','followup','reminder','todo')),
  status TEXT NOT NULL CHECK(status IN ('open','waiting','done','dropped')) DEFAULT 'open',
  due_at TEXT, next_check_at TEXT, source_kind TEXT, source_ref TEXT,
  origin TEXT NOT NULL CHECK(origin IN ('user','agent','system')) DEFAULT 'user', notes TEXT,
  created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
  updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')), completed_at TEXT);
CREATE TABLE IF NOT EXISTS audit_log(
  id INTEGER PRIMARY KEY, ts TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
  session_id TEXT, invocation_id TEXT, actor TEXT NOT NULL CHECK(actor IN ('agent','user','job')),
  event TEXT NOT NULL, tool TEXT, args_json TEXT, result_summary TEXT, approval_id INTEGER);
CREATE TABLE IF NOT EXISTS briefs(id INTEGER PRIMARY KEY, date TEXT NOT NULL, text TEXT NOT NULL, items_json TEXT,
  created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')));
CREATE TABLE IF NOT EXISTS push_subscriptions(id INTEGER PRIMARY KEY, endpoint TEXT NOT NULL UNIQUE, p256dh TEXT NOT NULL,
  auth TEXT NOT NULL, created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')), last_ok_at TEXT);
CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY, value_json TEXT NOT NULL);
-- chat threads the user pinned or renamed (odie.threads); the conversations themselves live in the session store
CREATE TABLE IF NOT EXISTS threads(session_id TEXT PRIMARY KEY, title TEXT, pinned_at TEXT);

create table if not exists trackers (
  id integer primary key autoincrement,
  title text not null,
  check_text text not null,
  schedule_json text not null,
  notify text not null default 'change' check (notify in ('change','always','condition')),
  condition text not null default '',
  until_at text not null,
  status text not null default 'active' check (status in ('active','paused','done','stopped','failed')),
  last_state text,
  last_summary text,
  last_blocks_json text,
  last_checked_at text,
  next_check_at text not null,
  fails integer not null default 0,
  created_at text not null
);

-- paired devices (odie.devices): only hashes of keys, codes and the setup token are kept
create table if not exists devices (
  id integer primary key autoincrement,
  name text not null,
  key_hash text not null unique,
  created_at real not null,
  last_seen_at real not null
);
create table if not exists pair_codes (
  code_hash text primary key,
  kind text not null check (kind in ('code','setup')),
  expires_at real
);

-- what the user did to a block in a chat reply (a checklist's ticks), so it survives a reload and shows on every device.
-- message_key: the ADK event id of the reply; block_path: "<fence>/<place in the fence>", e.g. "0/1.children.0"
create table if not exists block_state (
  session_id text not null,
  message_key text not null,
  block_path text not null,
  value_json text not null,
  updated_at text not null,
  primary key (session_id, message_key, block_path)
);
