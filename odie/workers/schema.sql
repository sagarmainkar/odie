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
