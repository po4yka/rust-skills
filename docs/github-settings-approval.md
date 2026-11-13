# GitHub settings: separate approval

Status: proposed, not applied. Snapshot: 2026-11-13.

This proposal covers audit findings 03 and 19. A pull request changes repository
files only. Apply these settings only after the owner approves this proposal.

## Observed state and proposed changes

| Setting | Observed state | Proposed state |
| --- | --- | --- |
| Required checks on `main` | None | Require `Validate catalog` and `Compile-check examples`; require the branch to be up to date |
| Required pull request review | None | Require one approval and Code Owners review; dismiss stale approvals |
| Administrator bypass | Enabled | Enforce the same branch requirements for administrators |
| Signed commits on `main` | Not required | Require signed commits |
| Force-push and deletion of `main` | Disabled | Keep both disabled |
| Release tag ruleset | No ruleset | Add an active tag ruleset for `v*` that blocks updates and deletion, with no bypass |
| Private vulnerability reporting | Disabled | Enable it |

The tag rule permits creation of new tags. It blocks changes to existing release
tags. This proposal does not publish a tag, change repository permissions, add a
collaborator, or merge a pull request.

## Review prerequisite

The current CODEOWNERS file names only the repository owner. A pull request
author cannot approve their own pull request. Required Code Owners review with
no administrator bypass would block owner-authored pull requests until another
eligible Code Owner can review them.

Before enabling that requirement, the owner must select another eligible reviewer
and separately authorize any access or CODEOWNERS change. No reviewer or access
change is selected by this proposal. The CI, signing, tag, and private-reporting
settings can be approved separately from the review requirement.

## Read-only verification

Run after approved settings are applied. Inspect the returned values; a successful
HTTP response alone does not prove that the requirements are enabled.

```bash
gh api repos/po4yka/rust-skills/branches/main/protection
gh api repos/po4yka/rust-skills/branches/main/protection/required_signatures
gh api repos/po4yka/rust-skills/rulesets
gh api repos/po4yka/rust-skills/private-vulnerability-reporting
```

Read the new tag ruleset by its returned ID. Confirm its `v*` condition, active
enforcement, update/deletion rules, and empty bypass list. Confirm that the private
report form is available without submitting a test report. Update the dated
settings notes in README.md, AGENTS.md, SECURITY.md, and docs/releasing.md only
after verification.

## Sources

- [Protected branch settings](https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-protected-branches/about-protected-branches)
- [Required reviews and author approval limits](https://docs.github.com/en/pull-requests/how-tos/review-pull-requests/approving-a-pull-request-with-required-reviews)
- [Private vulnerability reporting](https://docs.github.com/en/code-security/how-tos/report-and-fix-vulnerabilities/configure-vulnerability-reporting/configure-for-a-repository)

The snapshot comes from the branch protection, ruleset, and private-reporting
REST endpoints above. No repository-settings write request was made during the
audit or its fixes.
