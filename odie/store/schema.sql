CREATE TABLE IF NOT EXISTS approvals(
  id INTEGER PRIMARY KEY, session_id TEXT NOT NULL, invocation_id TEXT NOT NULL, request_id TEXT NOT NULL,
  tool TEXT NOT NULL, args_json TEXT NOT NULL, summary TEXT NOT NULL, detail_json TEXT, provenance_json TEXT,
  status TEXT NOT NULL CHECK(status IN ('pending','approved','rejected','expired')) DEFAULT 'pending',
  created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')), decided_at TEXT, result_text TEXT, call_id TEXT);
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
-- the morning hello: one card a day (the day starts at 05:00), its summary for the day's chats, and what it was
-- written from (odie.morning.round)
CREATE TABLE IF NOT EXISTS mornings(day TEXT PRIMARY KEY, card_json TEXT NOT NULL, summary TEXT NOT NULL,
  made_at TEXT NOT NULL, inputs_json TEXT);
CREATE TABLE IF NOT EXISTS push_subscriptions(id INTEGER PRIMARY KEY, endpoint TEXT NOT NULL UNIQUE, p256dh TEXT NOT NULL,
  auth TEXT NOT NULL, created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')), last_ok_at TEXT);
CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY, value_json TEXT NOT NULL);
-- chat threads the user pinned or renamed (odie.threads); the conversations themselves live in the session store
CREATE TABLE IF NOT EXISTS threads(session_id TEXT PRIMARY KEY, title TEXT, pinned_at TEXT);
-- other ways for the assistant to be (odie.personalities): a name and a picture each; its SOUL and its memories
-- are files. A thread's and a task's `personality` column (added in Store.init_schema) says whose it is; NULL = Odie
CREATE TABLE IF NOT EXISTS personalities(id TEXT PRIMARY KEY, name TEXT NOT NULL, avatar TEXT, created_at TEXT NOT NULL);
-- which connected apps (MCP servers) each one may use (odie.plugins.access): a row only where a switch was set;
-- no row = on. personality '' = everyday Odie
CREATE TABLE IF NOT EXISTS app_access(server TEXT NOT NULL, personality TEXT NOT NULL, allowed INTEGER NOT NULL,
  PRIMARY KEY(server, personality));

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

-- open loops (proactive design §5): one row per real-world thing Odie follows until it closes, whatever source it came
-- from (odie.loops.ledger). personality NULL = everyday Odie's, as tasks. loop_events is each loop's evidence, append-only.
create table if not exists loops (
  id integer primary key autoincrement,
  personality text,
  title text not null,
  kind text not null default '',
  owner text not null default 'odie' check (owner in ('odie','you','them')),
  state text not null default 'new' check (state in ('new','working','ready','waiting','closed','dropped')),
  next_step text not null default '',
  playbook text not null default '',
  priority text not null default 'normal' check (priority in ('high','normal','low')),
  due_at text,
  next_check_at text,
  hidden_until text,
  refs_json text not null default '[]',
  has_news integer not null default 0,
  result text not null default '',
  brief text not null default '',
  link text not null default '',
  nudges integer not null default 0,
  attempts integer not null default 0,
  shown_at text,
  tapped text,
  closed_by text,
  closed_why text,
  created_at text not null,
  updated_at text not null,
  closed_at text
);
create table if not exists loop_events (
  id integer primary key autoincrement,
  loop_id integer not null,
  at text not null,
  source text not null,
  ref text not null default '',
  fact text not null
);
create index if not exists loop_events_loop on loop_events(loop_id);

-- Workers (odie.workers, Workers design 18 Nov 2026): one row per background job, and one per tool call it made.
-- kind: task (a Worker the user started from chat) or pr_test (code runs a pull request's tests for a loop).
-- personality NULL = everyday Odie's. needed_json: what the Worker was refused (would need a tap); allowed_json: what
-- the user's tap in the app allowed for the job's next run only. taint: the outside text the chat had read when it
-- started the job ("mail", "web pages"): such a Worker gets no web and no apps. version: rows this code wrote are 2;
-- an older install's rows (the bots experiment's jobs table, upgraded by Store.init_schema) stay 0 and are never shown,
-- told, recovered or retried.
create table if not exists jobs (
  id text primary key,
  kind text not null,
  title text not null,
  brief text not null,
  personality text,
  started_by text not null default 'you' check (started_by in ('you','odie')),
  loop_id integer,
  status text not null check (status in ('queued','running','done','failed','stopped')),
  session_id text,
  folder text not null,
  budget_seconds integer not null,
  runs integer not null default 0,
  outcome text,
  report text,
  error text,
  needed_json text not null default '[]',
  allowed_json text not null default '[]',
  cleared integer not null default 0,
  taint text not null default '',
  version integer not null default 0,
  created_at text not null,
  started_at text,
  ended_at text
);
create index if not exists jobs_status on jobs(status);
create table if not exists job_actions (
  id integer primary key autoincrement,
  job_id text not null,
  ts text not null,
  tool text not null,
  args_json text,
  result_chars integer,
  refused text,
  error text
);
create index if not exists job_actions_job on job_actions(job_id, id);
