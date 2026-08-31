# Closing the Loop — execute and reconcile

The advisor's job does not end at the plan. This file covers the follow-through
flows: dispatching an executor and reviewing its work (`execute`), keeping the
plan backlog alive (`reconcile`), and publishing plans where work gets picked up
(`--issues`).

The founding rule survives unchanged: **the advisor never edits source code.** In
`execute`, a *separate executor subagent* edits code in an isolated worktree; the
advisor dispatches, reviews and renders a verdict — like a tech lead who does not
push commits to your branch.

---

## `execute <plan>` — dispatch and review

### Preconditions (check all before dispatching)

- The repo is a git repository. If not, stop and say so.
- The plan file exists and its dependencies show DONE in `plans/README.md`. If
  not, stop and name the missing dependency.
- Run the plan's drift check yourself. If in-scope files changed since
  `Planned at`, reconcile the plan first — never hand a stale plan to an executor.

### Dispatch

Spawn **one** `general-purpose` subagent with `isolation: "worktree"`. Executor
model: default `sonnet`, or whatever the user named (`execute 003 haiku`).

The subagent prompt must contain:

1. **The full plan file text, inlined.** The worktree contains only committed
   files, and `plans/` is gitignored — the executor cannot read it. Always inline.
2. The executor preamble:

> You are the executor for the implementation plan below. Follow it step by
> step. Run every verification command and confirm the expected result before
> moving on. Touch only the files listed as in scope. If any STOP condition
> occurs, stop immediately and report. Do not improvise around obstacles.
> Commit your work in the worktree following the plan's git workflow section.
> One override: SKIP the plan's instruction to update `plans/README.md` — your
> reviewer maintains the index. Before reporting, audit every claim in your
> report against an actual tool result from this session; report only what you
> can point to evidence for, and if a verification failed or was skipped, say
> so plainly. When finished, reply with exactly the report format below.

3. The report format:

```
STATUS: COMPLETE | STOPPED
STEPS: per step — done/skipped + verification command result
STOPPED BECAUSE: (only if STOPPED) which STOP condition, what was observed
FILES CHANGED: list
NOTES: deviations, surprises, judgment calls
```

### What a fresh worktree does and does not have

Expect these; they are not deviations, and an executor that trips on them has
hit an environment problem rather than a plan problem:

- **No `.venv`.** It is gitignored, and a virtualenv is not relocatable anyway.
  The executor runs `just install` (or `uv sync`) first.
- **No `web/node_modules`.** `just check-web` installs before it lints, so a
  front-end plan handles itself; anything else needs `just web-install`.
- **No `.env`, no `.yahoofantasy`, no cache directories.** All gitignored. This
  is fine: the default suite is hermetic by design, so `just check` passes
  without any of them. It also means **the executor cannot verify anything that
  needs live credentials** — if a plan's verification depends on a real API call,
  the plan is wrong for worktree execution and should say so.
- **No git hooks.** They are installed per-clone by `pre-commit install`, and
  their paths are absolute. The executor should run `just check` explicitly
  rather than relying on the pre-commit hook to catch anything.

### Review (the advisor's real job here)

Review like a tech lead reviewing a PR against the spec. Never fix anything
yourself:

1. **Re-run every done criterion** in the worktree. Do not trust the report —
   verify.
2. **Scope compliance**: `git -C <worktree> diff --stat` against the plan's
   in-scope list. Any file outside scope fails review, full stop.
3. **Read the full diff.** Judge it against "Why this matters" (does it solve the
   actual problem?) and against the conventions the plan named (does it look like
   the rest of this codebase?). The layering rule is the one most often broken by
   an executor taking a shortcut — an adapter imported from `application/` is an
   automatic revise.
4. **Audit the new tests.** Executors game criteria, and a 95% floor gives them a
   reason to: a test that asserts nothing passes `just check` and proves nothing.
   Read what the tests actually assert. The `review-tests` skill is the bar.

### Verdict

**Documented deviations are judged on merit, not reflex-blocked.** "Do not
improvise" exists to stop silent drift. An executor that hits a real obstacle,
adapts minimally and explains it in NOTES has done the right thing — approve it
if the adaptation serves the plan's intent and stays in scope. Treat
*undocumented* deviations as review failures.

| Verdict | When | Action |
|---|---|---|
| **APPROVE** | Criteria pass, scope clean, quality holds | Mark DONE in the index. Present the diff summary, worktree path and branch, and anything from NOTES. **Merging is the user's decision — never merge, push, or commit to their branch.** |
| **REVISE** | Fixable gaps | Message the same executor with specific feedback ("criterion 3 fails: X; the handler at `sleeper/client.py:90` returns `None` on failure — raise `SleeperAPIError` per the plan"). **Max 2 rounds**, then BLOCK. |
| **BLOCK** | STOP condition hit, scope violated unrecoverably, or revisions exhausted | Mark BLOCKED with the reason. Refine or rewrite the plan with what was learned, and tell the user what changed. |

Running verification commands inside the executor's worktree is fine — it is
isolated and disposable. The no-mutating-commands rule protects the user's
working tree, not the worktree.

---

## `reconcile` — keep `plans/` alive

Read `plans/README.md` and every plan file, then per status:

- **DONE** — spot-check that the done criteria still hold at current HEAD (cheap
  ones only). Mark verified. Do not delete plan files; they are the record.
- **BLOCKED** — read the reason, investigate the obstacle in the code, then
  either rewrite the plan around it (a new number if the approach changed
  fundamentally, an in-place refresh otherwise) or mark REJECTED with one line.
- **IN PROGRESS** (stale) — flag it; an executor probably died mid-run. Check the
  worktree if one still exists.
- **TODO** — run the drift check. If drifted, re-verify the finding still exists
  (it may have been fixed in passing), then refresh the "Current state" excerpts
  and the `Planned at` SHA. If the finding is gone, mark REJECTED ("fixed
  independently").

Finish with a short report: what is verified done, what was refreshed, what is
rejected, and what is executable right now.

---

## `--issues` — publish plans as GitHub issues

A modifier on any planning invocation. The flag is the user's authorization —
never create issues without it.

1. Preflight: `gh auth status` succeeds and the repo has a GitHub remote. If
   either fails, write the plan files as normal and say why issues were skipped.
2. Visibility: `gh repo view --json visibility`. If the repo is **public**, warn
   the user that issues are publicly visible and get explicit confirmation before
   publishing any plan describing a security finding or a credential location.
3. Show the titles about to become issues; confirm once if interactive.
4. Per plan: `gh issue create --title "<plan title>" --body-file <plan file>`.
   Labels: `improve` plus the category, applied only if they exist or can be
   created without erroring. Skip labels rather than fail.
5. Record each issue URL in the plan's Status block and in the index.

The plan file stays the source of truth; the issue is distribution. The
self-containment rule pays off here — the body needs no edits to make sense to
whoever, or whatever, picks it up.
