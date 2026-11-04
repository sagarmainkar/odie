import { describe, expect, it } from "vitest";
import { jobLine, type JobRow } from "./jobs";

const job = (over: Partial<JobRow>): JobRow => ({ id: "job-1", kind: "task", title: "T", status: "running", runs: 1, outcome: null, error: null,
  every_minutes: 0, next_run_at: null, report: "", started_at: null, ended_at: null, ...over });

describe("a job's state in words", () => {
  it("reads each state", () => {
    expect(jobLine(job({}))).toBe("working");
    expect(jobLine(job({ every_minutes: 5, runs: 3 }))).toBe("checking (run 3)");
    expect(jobLine(job({ status: "waiting", every_minutes: 60, next_run_at: "2026-11-04T10:00:00+00:00" }))).toBe("every 60 min · next 10:00");
    expect(jobLine(job({ status: "done", outcome: "ready" }))).toBe("done");
    expect(jobLine(job({ status: "done", outcome: "ready", every_minutes: 5, runs: 4 }))).toBe("finished after 4 reports");
    expect(jobLine(job({ status: "done", outcome: "blocked" }))).toBe("stuck");
    expect(jobLine(job({ status: "failed", error: "no progress for 10 minutes" }))).toBe("didn't finish · no progress for 10 minutes");
    expect(jobLine(job({ status: "stopped" }))).toBe("stopped");
  });
});
