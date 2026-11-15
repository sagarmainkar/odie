-- Workers (odie.workers): one row per job, and one per tool call a Worker made.
create table if not exists jobs (
  id text primary key,                       -- "job-3f9a2c"
  kind text not null,                        -- task (later: reporter, mail)
  title text not null,
  brief text not null,
  model text not null default '',            -- '' = the chat's model; else the model slot the kind named
  status text not null check (status in ('queued','running','waiting','done','failed','stopped')),  -- waiting: a reporter between runs
  session_id text,                           -- the chat the job came from, where its report is posted
  folder text not null,
  budget_seconds integer not null,
  every_minutes integer not null default 0,  -- a reporter runs again this often; 0 = once
  until_at text,                             -- a reporter's last run is before this (UTC)
  next_run_at text,                          -- when a waiting reporter runs next (UTC)
  notify text not null default 'always',     -- a reporter speaks: always | change (the state differs) | condition (met)
  condition text not null default '',        -- the condition, in words, for notify = condition
  last_state text,                           -- the reporter's last comparable state ("2-1 FT", "Out for delivery")
  runs integer not null default 0,           -- how many times a Worker was started on it
  outcome text,                              -- what the Worker said in report: ready, blocked, dropped
  report text,                               -- the Worker's report text
  error text,                                -- why it failed, one line
  created_at text not null,
  started_at text,
  ended_at text
);
create table if not exists job_actions (
  id integer primary key autoincrement,
  job_id text not null,
  ts text not null,
  tool text not null,
  args_json text,
  result_chars integer,                      -- how long the tool's answer was
  refused text,                              -- why the guard refused the call (then the tool never ran)
  error text                                 -- what the tool raised
);
create index if not exists job_actions_job on job_actions(job_id, id);
-- Bots (odie.workers.bots): named Worker templates. The chief makes the others; the user edits any of them in Settings.
create table if not exists bots (
  name text primary key,                     -- "chief", "researcher": lower case, what the chat and the chief call it
  role text not null,                        -- one line: what it is for ("finds and checks sources")
  prompt text not null,                      -- its own instructions, under the Worker rules
  model_json text,                           -- {"provider": "ollama", "model": "lfm3:latest"}; null = the chat's model
  powers_json text not null default '[]',    -- what it may use: web, files, shell, browser
  made_by text not null default 'user',      -- chief | user | odie (the chief itself)
  edited_by_user integer not null default 0, -- the user changed it in Settings: the chief may no longer change it
  created_at text not null,
  updated_at text not null
);
-- A question a running bot waits on: a tap for a browser step, or the user's sign-in in the live view.
create table if not exists job_asks (
  id text primary key,                       -- "ask-1a2b3c"
  job_id text not null,
  kind text not null,                        -- tap | sign_in
  text text not null,                        -- what the card says ("Click "Place order" on amazon.in")
  detail_json text,                          -- why, site, tab, screenshot
  status text not null default 'open',       -- open | yes | no | expired
  created_at text not null,
  answered_at text
);
-- Conversations with a bot (odie.workers.convs): each message the user sends is answered by one of the bot's jobs.
create table if not exists bot_convs (
  id text primary key,                       -- "conv-1a2b3c4d"
  bot text not null,
  title text not null,
  origin text not null default '',           -- chat: started by "@bot …" in Odie's own chat
  preview text not null default '',          -- the last message's first line
  unread integer not null default 0,         -- the bot said something the user hasn't opened
  created_at text not null,
  updated_at text not null
);
create index if not exists bot_convs_bot on bot_convs(bot, updated_at);
create table if not exists bot_msgs (
  id integer primary key autoincrement,
  conv_id text not null,
  role text not null,                        -- user | bot | ask (a question the bot waits on) | note
  text text not null,
  job_id text not null default '',
  media_json text,                           -- a reply's files; a question's {"ask": id, "kind", "why", "card"}
  ts text not null
);
create index if not exists bot_msgs_conv on bot_msgs(conv_id, id);
