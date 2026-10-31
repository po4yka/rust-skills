## What changes

<!-- One skill per pull request where practical. Name the skill, or say "harness" for
     checks/, scripts/, evals/, .github/, or .claude-plugin/. -->

## Why

<!-- The defect, misroute, stale claim, or primary source that motivates the change. Link a
     misroute issue when there is one. -->

## Verification

<!-- The commands you ran and what they proved. -->

- [ ] `bash checks/check.sh` is green
- [ ] A changed description keeps every phrase in `tests/routing-cases.md` and claims no
      phrase in `evals/routing/negative-cases.md` (the validator checks both)
- [ ] A new or changed command, crate, or URL was checked against its primary source
- [ ] No body grew past its entry in `scripts/catalog-ceilings.toml`

## What a green run does not prove

<!-- For example: a prose claim, a flag on another platform, routing in a real client. -->
