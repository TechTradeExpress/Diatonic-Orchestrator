## Summary

<!-- What changed and why? -->

## Scope

<!-- What is included and excluded? Which assigned task or milestone increment does this implement? -->

## Checks

- [ ] `uv run ruff check .`
- [ ] `uv run pytest`
- [ ] Tests added/updated for changed behavior, or not applicable (explain)

<!-- Mention any checks not run and why. -->

## Resource Model and architecture

- [ ] Preserves `iac/v0alpha1` and `iac-provider/v0alpha1` API namespaces
- [ ] Keeps out-of-scope milestones out of this PR
- [ ] Any semantic changes to the public contract are explained and tested

## Related issue

<!-- Use Refs #N for an explicitly assigned Issue. Avoid autoclosing keywords.
The Issue is closed at independent technical acceptance, before human merge.
If no Issue was explicitly assigned, state that here. -->

## Delivery and independent review

<!-- Follow ../docs/contributing-workflow.md. Codex delivers a Draft PR and does
not fill in its own independent acceptance or mark the PR ready to merge. -->

- Full head commit SHA:
- Changed files and outstanding limitations:
- Independent ChatGPT review: PENDING

<!-- Reviewer: record CHANGES_REQUESTED / ACCEPTED / BLOCKED in the PR conversation
with the exact full reviewed head SHA and check evidence. Every new commit
invalidates prior technical acceptance. Acceptance is distinct from GitHub APPROVE.
After acceptance, verify current head/checks/criteria, publish ACCEPTED and
READY TO MERGE with the full SHA, comment on and close the Issue as accepted
awaiting human merge, then mark the Draft PR Ready for review. Leave the PR open.
READY TO MERGE is a workflow decision, not a merge or proof branch rules pass.
Only the human maintainer merges. Reconcile Issue/PR state if acceptance lapses;
reopen the Issue when necessary. Never report an unmerged PR as merged. -->
