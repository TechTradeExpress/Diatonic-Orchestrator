# Workflow MVP.1: agent task, authorization and recovery contract

Status: documentation-only contract for Issue #48. No runner code, Codex launch,
GitHub mutation, Work trigger, unattended execution or live-run authorization is
provided here. Future implementation and live use require separately scoped human
authorization and the fake-tool evidence below. “Must” defines that future runner's
acceptance contract, not an implemented security control.

Read [AGENTS.md](../../AGENTS.md), the [contributing workflow](../contributing-workflow.md),
the normative [Resource Model](../resource-model/v0alpha1.md), the
[M3.2 entry gate](../reviews/m3-synthetic-implementation-entry-gate.md), and
[ADR-0018](../decisions/0018-provider-configuration-secret-boundary.md),
[ADR-0019](../decisions/0019-m3-operation-context.md),
[ADR-0020](../decisions/0020-m3-provider-protocol-error-isolation.md).
This contract changes no ADR status or disposition, M3 governance choice,
`iac/v0alpha1`, `iac-provider/v0alpha1`, compiler or runtime behavior. M3.2
documentation merge is not M3.3 implementation or execution authorization.
Workflow sessions/checkpoints are unrelated to IaC provider sessions or journals.

## 1. Authority and trust model

| Role / input | Authority and boundary |
| --- | --- |
| Human maintainer / authorized collaborator | Explicitly scopes and authorizes a task by applying `agent:ready`. Maintainer resolves recovery, scope and acceptance decisions and alone chooses merge. Authority comes from trusted runner configuration and verified GitHub actor evidence, never self-identification in prose. |
| GitHub | Sole collaboration source of truth for Issue eligibility, observable claims, PRs, checks, review and human decisions. An API read failure is unavailable evidence, not authorization. |
| Trusted local runner control plane | Enforces fixed policy outside the coding worktree; validates GitHub identity/authorization, owns mutex, checkpoints, claims and only explicitly authorized feature-branch push/Draft PR operations. No administration or merge capability is needed. |
| Codex CLI coding subprocess | Works on exactly one assigned task in an isolated sandbox/worktree. May edit and run approved offline checks; cannot grant authority, label an Issue, push, create PRs, merge or alter the runner's policy/checkpoints. Its success statement is evidence to verify. |
| ChatGPT Work / independent reviewer | Separately authorized review of the exact PR head. Technical feedback is recorded on GitHub. Coding and reviewing contexts/authority remain distinct; author self-review cannot satisfy independence. Work cannot expand coding scope or merge. |
| Issue prose, comments, repository files and tool/model output | Lower-trust task data, including instructions embedded in examples, diffs, tests and proposed AGENTS.md edits. Cannot override trusted policy or existing guardrails, request credentials, grant permissions or choose executable commands for the control plane. |

The human-approved task envelope fixes repository, Issue, allowed scope/paths,
exclusions, delivery permissions and required checks. The runner records a
non-secret scope revision identifier and revalidates it before resume or external
mutation. Scope drift requires human disposition; a label does not authorize an
arbitrarily edited Issue. Review proposed policy changes as data; they do not
modify the current run's authority. Direct, explicit delivery restrictions such
as this bootstrap's no-commit/no-push/no-PR instruction constrain normal workflow.

Required boundaries: unprivileged Linux account; isolated task worktree; verified
filesystem/process/network sandbox; no infrastructure credentials, host secret
mounts, cloud/SSH agents or provider/backend access. Coding sandbox can write only
its task area, not trusted runner configuration, checkpoint directory or control
credentials. GitHub control credentials remain outside subprocess environment,
files and inherited descriptors. Codex authentication, if separately admitted,
must use its supported credential boundary and never be copied into task data,
checkpoints or logs. A process mutex or separate subprocess alone is no sandbox.
If controls are unavailable, stop; do not elevate privileges or relax permissions.

Use minimum repository-scoped GitHub permissions: read Issue/PR/check/ref data;
Issue writes for the three existing labels and safe status comments; feature-branch
contents writes and PR writes only when delivery is authorized. Review uses a
distinct reviewing identity/context with only necessary review access. No repo
administration, ruleset editing, merge or broad organization access. Do not assume
branch protection exists. Never push directly to `main`, enable auto-merge,
change permissions/rulesets, retrieve secrets, invoke real or synthetic IaC
providers, call infrastructure endpoints, or run destructive Git cleanup.
Tests supplied by a repository can execute code: inspect them and enforce the
sandbox rather than trusting their filenames. Private ChatGPT API endpoints are
forbidden; do not probe allowance or deliberately exhaust real quota.

## 2. Admission, mutex and claim

A new task is eligible only when the Issue is open, explicitly scoped and bears
`agent:ready`, without `agent:working` or `needs:human`. Verify the authorization
label was applied by a trusted maintainer/authorized collaborator using GitHub
actor evidence and trusted allowlist/policy. Missing or ambiguous evidence stops
admission. The runner/coding agent cannot self-apply `agent:ready`. No additional
label taxonomy or label creation is part of MVP.

One runner may own one active Issue, including paused and PR-review-waiting work.
Use one fixed host-local exclusive nonblocking `flock` in a private trusted
directory shared by all invocations of this runner. Acquire it before reading or
mutating recovery state or claiming work; lock failure exits without side effects.
Never unlink/recreate the lock to bypass contention. Prevent a child surviving
runner death from freeing effective exclusion: a trusted supervisor must keep the
lock for the full owned coding-process lifetime. No second child may start until
the previous process is proven stopped. Unsupported supervision fails closed.

Under the mutex, re-read eligibility, durably record claim intent, apply
`agent:working`, then re-read and reconcile the claim before launching. Preserve
`agent:ready` while claimed so resume can revalidate it. Labels are not conditional
compare-and-swap: `agent:working` is an observable claim, **not an atomic
distributed lock**. Multiple hosts/runners, shared-filesystem lock assumptions and
distributed contention are out of scope and must not be enabled.

An existing `agent:working` permits only recovery of the verified saved task;
it never admits a fresh task. Unknown/stale claims require human reconciliation,
not automatic removal. Retain the claim across pause/restart/PR_READY. On a known
blocking condition publish a safe GitHub reason and `needs:human`; if GitHub is
unavailable, stop locally and reconcile the pending update before further work.
Local checkpoints are session recovery metadata, never a second status board.

## 3. Versioned atomic checkpoint

Schema version 1 is an exact non-secret record. Reject unknown versions, missing
required fields, invalid types, unsafe paths and inconsistent identities. Nullable
fields below are explicit JSON null when not known; all others are required.

| Field | Contract |
| --- | --- |
| `schema_version`, `generation` | Integer 1; monotonically increasing nonnegative checkpoint generation. |
| `repository` | Expected GitHub host, immutable repository ID, canonical owner/name and verified local Git common-directory identity; detect remote substitution/rename and require reconciliation. |
| `issue_number`, `scope_revision` | Positive Issue number and trusted approved task-envelope revision; no Issue body snapshot. |
| `base_sha`, `branch`, `worktree` | Full immutable starting `main` SHA, exact dedicated branch and canonical absolute isolated worktree path. Never silently rebase/change base on resume. |
| `codex_thread_id` | Validated opaque ID observed from the pinned CLI adapter's `thread.started`, otherwise null. Not permission or a credential. |
| `process_identity` | Null before launch/after confirmed stop; otherwise supervisor-owned launch ID, host boot ID, PID and process start identity. PID alone is insufficient against reuse. |
| `state`, `pause_reason` | One state from section 4 and null or a bounded runner-owned reason enum from section 5. No free-form model/error text. |
| `next_permitted_retry` | Explicit UTC timestamp or null for no automatic retry. Deadline grants no authority; resume still checks all gates. |
| `attempts` | Persisted nonnegative `total_launches`, `quota_retries`, `transient_retries`; bounded as below. No reset on restart or event replay. |
| `pr_number` | Positive known PR number or null; GitHub remains authoritative. |
| `last_safe_checkpoint` | Generation, UTC time, fixed phase enum, observed full branch head SHA and operation status (`none`, `prepared`, `confirmed`) with a bounded operation kind (`claim`, `launch`, `push`, `create_pr`, `publish_review`, `release_claim`). |

Keep checkpoints outside the repository in a trusted owner-only 0700 directory,
with private regular 0600 files. Reject symlinks, unexpected ownership and unsafe
permissions; do not follow paths provided by Issue text. Under `flock`, serialize
the validated record to an exclusively created 0600 temporary file in the same
directory, write completely, fsync the file, atomically replace the destination,
then fsync the containing directory. Acknowledge persistence only after all steps
succeed. Failure stops new side effects. A crash exposes either old or new whole
record; orphan temporary files are not authoritative and are not auto-promoted.
Corruption, competing generations or uncertain durability requires human recovery.

No tokens, credential material, raw JSONL/model output, prompts, Issue prose,
environment dumps, diffs or exception text belong in checkpoints. Limit records
to 16 KiB; safe identifiers/paths must themselves contain no secrets. Operational
logs use bounded allowlisted codes/counters only; never archive raw stdout/stderr.
Raw CLI events are transient, tainted input, not safe diagnostics.

Persist intent **before** each claim, launch, push, PR creation or review update,
and persist confirmation only after independently observing its result. Save the
thread ID as soon as validated; save each terminal state before announcing it.
Filesystem replacement cannot atomically commit a GitHub action or process launch.
A prepared operation after crash means “outcome unknown”: inspect supervisor and
GitHub refs/PRs/comments before any replay. If identity/result cannot be proven,
stop for a human. Never infer exactly-once behavior from a checkpoint.

## 4. States and allowed transitions

`READY` means admitted candidate, no coding process yet. `RUNNING` means one
owned task attempt, including verification/delivery after the child exits.
`PAUSED_QUOTA` and `PAUSED_TRANSIENT` mean no live coding process and a bounded
retry schedule. `NEEDS_HUMAN` prohibits automatic progress. `PR_READY` means one
verified Draft PR with coding/check evidence; review may still be pending.
`COMPLETED` means verified human merge/closure disposition, never agent merge.

Every transition requires the mutex, an atomic checkpoint and GitHub
reconciliation. All unlisted transitions are forbidden. A self-transition may
only update evidence without repeating side effects. “Resume gates” means all
invariants in section 6, not merely elapsed time.

| From | Event and guard | To / required action |
| --- | --- | --- |
| No saved task | Eligible authorized Issue; no existing unknown claim/process | READY; save identities and claim intent. |
| READY | Claim verified, no existing Draft PR, safe clean initial worktree, launch allowed | RUNNING; checkpoint launch intent/counters before starting one child. |
| READY | Exactly one existing Draft PR matches approved Issue, branch, base and verified saved recovery identity | PR_READY; adopt its number after checking actual head/check evidence; no new branch/PR. No saved identity or mismatched evidence goes to NEEDS_HUMAN. |
| RUNNING | Verified task completion, required checks pass, authorized delivery confirmed, exactly one matching Draft PR | PR_READY; persist number/head and publish review pending for that head. A turn completion alone is insufficient. |
| RUNNING | Explicit reliable usage-limit evidence, child stopped, identity known, retry budget available | PAUSED_QUOTA; persist safe reason and permitted retry time. |
| RUNNING | Recognized recoverable network/service failure, child stopped, no ambiguous side effect, session known, budget available | PAUSED_TRANSIENT; persist backoff. |
| READY / RUNNING / either PAUSED / PR_READY | Authentication/authorization failure or revocation, Git conflict, failed tests, task failure, manual intervention, unsafe scope/identity, exhausted budget | NEEDS_HUMAN; halt further work, retain changes/claim and publish safe reason with `needs:human`. Stop owned child before retry eligibility. |
| RUNNING on restart | Crash/interruption, absent terminal evidence, possibly live child, unknown thread, prepared external operation | NEEDS_HUMAN; reconcile exact process/session and external effects; never auto-relaunch. |
| Either PAUSED | Time reached, budget available, resume gates pass, exact saved thread resumable | RUNNING; checkpoint counter and launch intent; resume same session once. |
| Either PAUSED | Restart before retry time, known stopped process, resume gates pass | Same PAUSED; preserve timestamp/counters, no launch or hot polling. |
| NEEDS_HUMAN | Explicit maintainer recovery record; gates pass; exact session known and stopped | RUNNING for authorized same-session continuation, or PR_READY if existing Draft PR and evidence suffice. No automatic transition; clear `needs:human` only after verified human disposition. |
| NEEDS_HUMAN | Human reconciles an unlaunched task (no possible previous coding process/session), gates pass | READY; never use this path to replace an unknown launched session. |
| PR_READY | Work unavailable or review incomplete for current head | PR_READY; publish pending on GitHub, rescan later; no coding launch. |
| PR_READY | New head observed | PR_READY; invalidate old review coverage and check evidence; request fresh review of exact new SHA. Unexplained external edits require NEEDS_HUMAN. |
| PR_READY | Review requests changes; maintainer explicitly authorizes same-task revision, resume gates pass | RUNNING; resume known session; old review cannot cover the next head. |
| PR_READY | GitHub proves human merge of reviewed head with required checks/signoff | COMPLETED; reconcile human disposition, release observable claim; never merge automatically. |
| Any nonterminal | Human explicitly cancels/closes task without merge and confirms no live process/ambiguous operation | COMPLETED; record cancellation disposition, retain worktree/changes, release claim. Closure alone while running first stops work for human reconciliation. |
| COMPLETED | Restart | COMPLETED; verify terminal disposition; do not reopen, retry or start another task in this invocation. |

If no PR delivery is authorized, do not manufacture PR_READY: finish local edits,
report evidence and wait for human disposition in NEEDS_HUMAN (`local_delivery`).
COMPLETED never implies that code was merged. Release `agent:working` only after
terminal disposition is confirmed; ambiguous release is reconciled on restart.

## 5. JSONL and retry classification

Future implementation must pin and fixture-test its supported Codex CLI version
and event adapter. This document does not assert current CLI flags or stable
error codes. Process JSONL incrementally with explicit limits: 64 KiB per line,
16 MiB total per attempt, 64 levels maximum nesting; reject malformed UTF-8,
duplicate keys, invalid shape, truncation and excess before unbounded allocation.
Unknown informational events may be discarded only if the pinned adapter marks
them non-control; unknown terminal/error semantics stop for human inspection.
Never execute or persist event text. Classify from validated structured evidence,
not substring searches over assistant messages, Issue text or stderr.

| Evidence | Meaning / safe reason and action |
| --- | --- |
| `thread.started` | Save one observed thread ID atomically. Conflicting IDs, mismatched resumed ID or no durable ID after possible launch: `session_unknown`, NEEDS_HUMAN. |
| `turn.completed` | Candidate completed turn only. Require orderly process exit, stream completion, task diff/scope inspection and actual test results. Never creates PR or success by itself. |
| `turn.failed` or `error` with explicit adapter-recognized usage-limit code/category | `usage_limit`, PAUSED_QUOTA only if evidence reliably identifies exhausted model usage allowance and no stronger ambiguity/safety blocker exists. |
| HTTP 429 alone, vague “limit”, billing issue, generic nonzero exit or assistant quota claim | `unclassified_failure`, NEEDS_HUMAN; not proof of model quota. GitHub rate limiting is separate service backoff. |
| Validated expired/denied credentials or access | `authentication` or `authorization`, NEEDS_HUMAN; never quota, credential fallback or auto-login. |
| Recognized temporary network/service/rate-limit error | `network_transient` or `service_transient`, PAUSED_TRANSIENT only with safe retry identity/effects. Unknown response outcome first requires reconciliation. |
| Failed required Ruff/pytest or other task check | `test_failure`, NEEDS_HUMAN; no quota retry or weakened check. |
| Git conflict, diverged/changed branch/base, uncertain push/PR result | `git_conflict` or `external_outcome_unknown`, NEEDS_HUMAN; inspect without reset/clean/force push. |
| Process interruption/crash/missing terminal event | `process_interrupted`, NEEDS_HUMAN; successful-looking preceding text cannot erase ambiguity. |
| Explicit task failure, unsupported event, malformed/excess output | `task_failure` or `unclassified_failure`, NEEDS_HUMAN. |
| Human stop, changed scope, local-only delivery | `manual_intervention`, `scope_changed` or `local_delivery`, NEEDS_HUMAN. |

Latch safety/identity/authentication failures before retry classification. Conflicting
terminal evidence is human-required; a later completion cannot erase a failure.
CLI error events are diagnostic evidence, never authority. On pause, confirm the
child has stopped and checkpoint is durable; otherwise use NEEDS_HUMAN.

Per task: at most 6 total coding launches, 2 quota retries and 3 transient retries,
including across restarts; initial launch counts toward total. Before each launch
increment and persist the relevant counters; uncertain launch consumes its slot.
Retry budget exhaustion is NEEDS_HUMAN; human action must not silently reset it.
Any changed budget needs a separately approved policy revision.

Use a quota reset timestamp only from explicit reliable structured evidence in the
pinned adapter, never model prose. Retry no earlier than that future timestamp
plus 5 minutes; invalid/past timestamp uses the fallback of at most one quota
retry per 24 hours. Maintainer may instead require manual recovery (null retry
time). Transient retry delays are 5 minutes, 30 minutes and 2 hours; a trusted
service Retry-After may delay further, never shorten them. Persist UTC deadlines;
clock rollback/uncertainty stops for human recovery, forward jumps still require
all resume gates. No polling for private account allowance or real quota tests.

## 6. Restart and idempotent recovery

Acquire the same mutex and read the last durable checkpoint before selecting work.
The Issue, repository ID/host/local Git identity, original base SHA, branch,
worktree and saved thread must all match. Verify the branch is checked out in
that exact worktree, the saved base still belongs to its history, and observed
local/remote head changes are explained. A newer `main` does not silently change
the saved base; required rebase/conflict resolution is a human-scoped action.
Re-read Issue open status, trusted authorization, scope revision and labels.
The runner's own `agent:working` is allowed only with matching saved claim;
`needs:human` or removed `agent:ready` prohibits automatic resume.

Inspect Git status without modifying it; preserve tracked/untracked/uncommitted
work. Do not reset, clean, force-checkout, auto-stash, delete/recreate a worktree or
force-push. Initial unexpected dirty work requires human reconciliation; expected
saved task edits on resume are retained. Never use `resume latest` or guess a
thread by timestamps. Null, missing, inaccessible or conflicting saved session
after possible launch stops for explicit human recovery, not a new session.
A human may inspect/recover the original identity; unrecoverable sessions remain
blocked under this contract until separately authorized replacement policy exists.

Check supervisor identity (boot ID, PID/start identity, launch ID), not PID alone.
If the old child is known live, do not spawn a second or attach blindly. If it is
unknown, do not kill an arbitrary PID; require human reconciliation. A recovered
RUNNING checkpoint always requires human disposition even if no child is now
visible, because a terminal event or side effect could have been lost.

Search GitHub for the exact repository/Issue/head branch/base, including closed
and merged PRs, and compare observed remote ref SHA. Exactly one matching Draft
PR is reused; adopt its number if the crash lost that field only after identity
verification. Multiple PRs, unrelated existing branches, non-Draft state or
unexpected heads stop for a human. Never create a duplicate or rewrite history.
Before retrying a prepared push, compare the intended saved full SHA to remote;
before PR creation, search again. If a response was lost and the operation's
outcome cannot be proven, stop rather than retry. Review comments likewise carry
the head SHA and are reconciled before republishing. These checks provide bounded
idempotent reconciliation, not an atomic GitHub transaction or exactly-once claim.

## 7. Independent review and human acceptance

Review unit is `(repository ID, PR number, exact full head SHA)`. Record reviewer
identity, findings, check evidence and reviewed SHA on GitHub. Re-read head before
publishing; if it changed, mark findings historical and review the new head.
Never describe an abbreviated SHA, branch name or previous green CI as current
head coverage. The coding agent cannot certify its own independent review.

If Work is unavailable or lacks access, publish a bounded pending-review comment
for that SHA on GitHub and rescan at most once per hour during later manual
invocations. Do not invent approval, configure triggers or add labels. If the
pending update fails, keep it unreconciled and retry only after inspecting GitHub.
PR_READY remains claimed while waiting; no second task starts.

`COMMENT` is technical feedback, not GitHub `APPROVE`, human acceptance or merge
authority. Formal approval requires an eligible independent reviewer/account and
applicable repository policy. No nominal second identity to simulate independence.
The maintainer separately records acceptance, exact head SHA, scope, conditions
and date under the applicable governance procedure. A new head invalidates prior
coverage/signoff and requires fresh review and disposition. Immediately before
human merge, verify head still equals reviewed/accepted SHA, conditions hold and
required checks passed for that head. No agent merges or enables auto-merge.
This workflow does not select or waive M3.2's pending governance decisions.

## 8. Linux operator runbook (future manual use)

No runner executable or command syntax is delivered. Do not launch Codex or
construct a runner from this runbook during this documentation increment.

1. Obtain separate implementation/live-use approval and fake-tool results. Confirm
   the single host/account and no second runner. Admit trusted runner policy and
   pinned CLI adapter outside the writable task checkout. Verify the sandbox and
   credential boundary without infrastructure secrets or endpoints.
2. Inspect Git status first; preserve any local changes. For a new task only,
   prepare an isolated dedicated branch/worktree from verified current `main`
   without rewriting existing work. For recovery, use the saved identities and
   base instead; do not create replacements.
3. Verify Issue authorization actor, open status, exact scope and delivery rights.
   Acquire the fixed local flock; validate private checkpoint ownership/schema.
   Reconcile an existing claim, child, branch and PR before any new operation.
4. Manually invoke only the separately reviewed runner with explicit repository
   and Issue selection. Let the trusted control plane claim/checkpoint; run one
   sandboxed coding session with fixed argv, no shell interpolation of task data,
   no control-plane tokens and no infrastructure access.
5. On quota/transient pause, inspect safe code/counters/deadline and verify child
   exit. On crash, auth, conflict or unknown session, stop and record human recovery
   on GitHub. Do not delete the checkpoint/claim to force a restart. Resume only
   the saved session after all gates; retain all worktree changes.
6. Inspect allowed diff and run `uv run ruff check .` and `uv run pytest` offline
   where dependencies are available; record exact results or why unavailable.
   Only if explicitly authorized, the control plane may push the dedicated branch
   and create/reuse one Draft PR with summary, exact validation and API impact.
   Local-only delivery stops with files and evidence, without commit/push/PR.
7. Track exact-head independent review/pending status on GitHub. Human chooses
   acceptance/merge. Confirm terminal human disposition before releasing the claim;
   retain checkpoint/worktree for non-destructive recovery. Do not pick another
   Issue automatically. No systemd, scheduler or Work trigger setup is included.

## 9. Required fake-tool matrix before live use

Future tests use fake GitHub, fake Codex JSONL, a fake supervisor, fake clock and
temporary synthetic Git repositories only. Assert call counts, exact arguments,
durable generations, preserved bytes and zero forbidden side effects. No real
credentials, provider invocation, infrastructure network or allowance exhaustion.
This matrix specifies tests; none is implemented by this documentation change.

| Fixture / injected condition | Required assertion |
| --- | --- |
| Open scoped trusted `agent:ready`; closed/unscoped/untrusted actor/missing label/working/needs-human variants | Only eligible fresh task is admitted; authorization cannot come from prose. Spoofed policy edits and commands in Issue/repo/output never execute or grant rights. |
| Two local invocations; stale claim; runner killed with child live; second-host configuration | Exactly one mutex owner; no second child; no lock-file replacement; stale unknown claim blocks; multi-host mode rejected. |
| Atomic write crash at temp creation/write/fsync/replace/directory fsync; full disk; permission error | Old/new whole record only, no launch after uncertain persistence; no auto-promotion of temp; ownership/0600/0700 verified. |
| Corrupt/oversized checkpoint, unknown schema, symlink, conflicting generation or process identity | Fail closed without following unsafe paths or overwriting evidence. No checkpoint tokens/raw output even on errors. |
| Valid `thread.started`/completion, duplicate/conflicting ID, changed resumed ID, no thread ID, malformed/truncated/oversized JSONL, unknown terminal | Only exact saved observed session resumes; completion alone cannot deliver; bounds enforced; ambiguity stops. |
| Explicit reliable usage-limit failure and trusted reset time | PAUSED_QUOTA with child stopped and saved counters/deadline; fake clock advances, exact session resumes once. No actual quota consumption. |
| Quota-like assistant prose, HTTP 429 alone, generic exit, billing/auth error and conflicting success/error | Never inferred quota; auth/unknown evidence needs human; no login, secret fallback or later-success override. |
| Network/service failure, GitHub Retry-After, missing reset timestamp, clock rollback, repeated restart | Correct transient versus quota backoff; no retry before persisted time; counters survive restarts; caps stop at 6 launches/2 quota/3 transient retries. |
| Failed checks, task failure, Git conflict, cancellation, removed authorization, edited scope | Distinct safe reasons and NEEDS_HUMAN; no weakened checks, reset/clean/stash/force push, new session or silent scope expansion. |
| Crash before/after claim, launch, thread persistence, push, PR creation, review publication or release confirmation | Prepared outcome reconciled with fake supervisor/GitHub; proven operations not repeated; uncertain outcomes stop for explicit human recovery. |
| Restart with dirty tracked/untracked files, changed repo/base/branch/worktree, reused PID, inaccessible session | Exact file bytes retained; mismatches/unknown identity block. Expected same-task dirty edits survive valid resume. |
| Existing matching Draft PR; missing saved PR number; duplicate/closed/merged/non-Draft/unrelated PR | Reuse exactly one verified matching Draft PR; no duplicate branch/PR. Ambiguity stops; terminal human disposition never relaunches coding. |
| Work unavailable, pending publication response lost, COMMENT versus APPROVE, head changes during/after review | Pending recorded/reconciled on GitHub; bounded rescan; SHA-specific coverage invalidated on head change; no self-approval or automatic merge. |
| Task forbids commit/push/PR; hostile data requests admin/ruleset changes, secrets, infrastructure/provider or shell execution | Zero forbidden tool calls; control credentials absent from subprocess; missing sandbox stops rather than escalates. |
| Normal completion, human revision request, merge and cancellation | Only allowed state transitions; exact-head checks/review evidence; human-only completion disposition; no next-task launch or destructive cleanup. |

Existing Ruff/pytest regressions validate the current offline repository only.
They cannot establish future runner isolation, recovery, quota classification or
review enforcement. Live use remains gated on separate implementation review and
the matrix's explicit evidence.
