---
name: merge-dependabot-prs
description: Merge saleVault's Dependabot pull requests one at a time, each rebased onto the current main and green in CI, as single-line squash commits. Use when the user asks to merge, apply or clean up dependency updates.
---

# Merge Dependabot pull requests

Merging changes the public repository: do it only when the user asks. Dependabot PRs all touch the lock files, so they are merged strictly one after another.

## 1. Look at what is open

```bash
gh pr list -R levch6/saleVault --author app/dependabot --json number,title,mergeStateStatus
```

For a major update, read the changelog and check whether the code needs changes; tell the user before merging it.

## 2. For each PR, in order

1. Make sure it is based on the current `main`:
   ```bash
   head=$(gh pr view N --json headRefOid --jq .headRefOid)
   gh api repos/levch6/saleVault/compare/main...$head --jq .behind_by
   ```
   If it is behind, comment `@dependabot rebase` on the PR and wait for the new head.
2. Wait until the `lint, test and build` check is `COMPLETED:SUCCESS` on that head:
   ```bash
   gh pr view N --json statusCheckRollup --jq '[.statusCheckRollup[] | "\(.status):\(.conclusion)"] | join(",")'
   ```
   If it fails, read the log (`gh run view <id> --log-failed`), fix the code on `main` if needed, and rebase again.
3. Squash-merge with a one-line subject of at most 100 characters and an empty body (Dependabot titles can be longer; shorten them):
   ```bash
   gh pr merge N --squash --subject "build(deps): bump <package> from <a> to <b> in /<dir>" --body ""
   ```

## 3. Afterwards

```bash
git pull --ff-only
(cd backend && uv sync --locked) && (cd frontend && pnpm install --frozen-lockfile)
just check
```

Report the merged versions and anything that needed a code change.
