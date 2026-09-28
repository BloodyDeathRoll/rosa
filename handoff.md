# Session Handoff — 2026-09-28 (Claude GitHub review)

## Goal
Make the Claude GitHub agent (review on every PR + `@claude` mentions) actually run on
`BloodyDeathRoll/rosa`, including Dependabot PRs, then review, audit and merge the two
open Dependabot PRs.

## Current State
- Claude review works on human PRs (PR #27, run 36454823772) and Dependabot PRs
  (#26 run 36472049932, #25 run 36472087198); each posts a summary comment.
- `@claude` mention workflow (`.github/workflows/claude.yml`) unchanged and NOT tested
  since the app install.
- Dependabot PRs #26 (maplibre-gl 6.10.0, vite 8.3.0, wrangler 4.136.1, workers-types)
  and #25 (ruff 0.16.8) were reviewed ("No issues found"), hand-audited, and merged
  (squash) at 19:29 UTC [22:29 local] on the operator's explicit request. Their remote
  branches were deleted. `origin/main` = 4b54eeb.
- Web was NOT redeployed after #26's maplibre/vite bump - rosa.surf still runs the old
  build. Checks (web build + tests) passed on the PR.
- Leftover: remote + local branch `setup-claude-git-workflow` (closed PR #27) still
  exists; this worktree sits on it. Unrelated local branch `ci/claude-review-dependabot`
  untouched.

## Active Files
- `.github/workflows/claude-code-review.yml` - the PR review; now has
  `CLAUDE_CODE_DISABLE_BACKGROUND_TASKS=1` and a Dependabot-only direct prompt.

## Changes Made This Session
1. Confirmed the `claude` GitHub App was not reaching rosa (401 "not installed") even
   though the operator had installed it for all repos; the operator then added rosa
   specifically - fixed.
2. Dependabot runs read a separate Dependabot copy of `CLAUDE_CODE_OAUTH_TOKEN`; it was
   invalid ("401 Invalid bearer token"). Generated a fresh `claude setup-token` token
   in-session (operator only pasted the browser code), tested it locally with
   `claude -p`, piped it into `gh secret set --app dependabot`.
3. 74fd364: background tasks off - the code-review plugin backgrounds its sub-agents
   and the headless run exited before they reported, passing green with no review.
4. 7c72408: the code-review plugin skips "automated" PRs by design (confirmed in the
   full log: `trivial_or_automated: true, should_stop: true`), so
   `user.login == 'dependabot[bot]'` gets a direct prompt (diff + changelogs + grep
   usage, inline comments, one summary comment); human PRs still use the plugin.
5. `show_full_output: true` was added twice for debugging and removed both times.

## Failed Attempts
- Asking the operator to run `claude setup-token` + `gh secret set` by hand: two
  pastes saved a corrupted token (401). Don't hand this back; do it in-session.
- Extracting the token with `tr -d '\r\n'` joined it with the next line ("Store this
  token...") -> invalid. The token ends at a CR; split on `\r` first.
- A green `claude-review` check is not proof of a review: check `num_turns` (real
  reviews ran 5+ with a summary comment; empty ones 2-3).
- `pkill -f` with a pattern that matches the calling shell kills the Bash call itself
  (exit 144).

## Next Step
1. Deploy web so the merged maplibre/vite bump reaches rosa.surf (project "rosa", see
   memory `vercel-web-project-link`); smoke the map + spot page.
2. Ask before deleting `setup-claude-git-workflow` (remote + local).
3. Optionally test `@claude` with a comment on the next PR.
