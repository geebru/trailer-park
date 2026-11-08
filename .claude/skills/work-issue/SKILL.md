---
name: work-issue
description: Take a GitHub issue from read to an open pull request. Reproduces, fixes, verifies, commits, pushes the branch and opens the PR against main, then stops for the owner to review and merge.
argument-hint: <issue number, with or without #>
---

Work the GitHub issue given as `$ARGUMENTS` following AGENTS.md (read it first if it is not in context). Carry it through to an open PR without waiting for approval; the PR is the review step. Ask only where AGENTS.md "Workflow" says to stop. Never merge.

**Issue number.** The argument may arrive as `31` or `#31`. Take the digits only and call them N. Use plain N in every command and branch name, and write `#N` only inside commit messages. Never put a bare `#` in a shell command: it starts a comment and drops the rest of the line.

1. **Read it.** `gh issue view N --comments`. The type is the prefix of the title (`fix`, `feat`, `docs`, `chore`, ...); the `question` label means the answer is the deliverable. Note any comments that change the scope. If the body is only an image, download it with `curl` into the scratchpad and look at it. If the direction is unclear or a "stop and ask" case from AGENTS.md "Workflow" applies, ask the owner before building; otherwise go.
2. **Isolate.** Work in a git worktree, not the main checkout. Reuse the current worktree if the session already runs in one; otherwise use EnterWorktree. Then `git fetch origin` and make sure the branch `<type>/N-<short-slug>` is based on `origin/main` (rename the branch and `git rebase origin/main`; both are fine while nothing is committed). `<type>` is the title's type.
3. **Do the work** for the type as AGENTS.md describes. For UI issues, start the dev stack from this worktree (AGENTS.md "Checking changes") and use the browser pane: capture the problem before changing anything, and capture the result after, at 1280 px and 390 px. For `question`, draft the answer in chat instead (no branch, no PR) and stop.
4. **Verify.** Run the checks in AGENTS.md "Checking changes" that fit the change, including axe on each page you touched at 1280 px and 390 px. Then the docs check: go through "Keep docs in step" and update whatever the change makes wrong, in the same commit. Run `python dev/stack.py down`, and reset `dev/media` if you changed it.
5. **Commit** with Conventional Commits and `Resolves #N` (or `Refs #N` for a related extra). One logical commit per working change: several small commits beat one big one, and each leaves the app working. Write the message to a file in the scratchpad and run `git add <paths>` and `git commit -F <file>` as separate plain commands; the worktree guard refuses commands that mix git with inline text.
6. **Open the PR.** Follow `/ship`: push the branch and open the PR against `main`. Build the PR's Description and Testing from the work: problem and root cause in plain terms, before/after evidence (screenshots, request/response, or repro steps and result), checks run and their results, docs updated or why none, risks, and anything you could not verify.
7. **Report** in chat: the PR link, a short summary, the risks and anything unverified, and the branch and worktree path. Say the owner can run `/preview` for a live copy; then stop. The owner reviews and squash-merges.
