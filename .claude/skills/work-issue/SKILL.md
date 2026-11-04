---
name: work-issue
description: Take a GitHub issue from read to a reviewed-ready fix on a local branch. Reproduces, fixes, verifies and commits, then stops for the owner's review without pushing.
argument-hint: <issue number, with or without #>
disable-model-invocation: true
---

Work the GitHub issue given as `$ARGUMENTS` following AGENTS.md (read it first if it is not in context). Do the work phase only. Never push and never open a PR here.

**Issue number.** The argument may arrive as `31` or `#31`. Take the digits only and call them N. Use plain N in every command and branch name, and write `#N` only inside commit messages. Never put a bare `#` in a shell command: it starts a comment and drops the rest of the line.

1. **Read it.** `gh issue view N --comments`. The type is the prefix of the title (`fix`, `feat`, `docs`, `chore`, ...); the `question` label means the answer is the deliverable. Note any comments that change the scope. If the body is only an image, download it with `curl` into the scratchpad and look at it. If the issue is vague, contradicts "Behavior to keep" in AGENTS.md, or needs a design call (API or settings shape, new page or setting), ask the owner before building.
2. **Isolate.** Work in a git worktree, not the main checkout. Reuse the current worktree if the session already runs in one; otherwise use EnterWorktree. Then `git fetch origin` and make sure the branch `<type>/N-<short-slug>` is based on `origin/main` (rename the branch and `git rebase origin/main`; both are fine while nothing is committed). `<type>` is the title's type.
3. **Do the work** for the type as AGENTS.md describes. For UI issues, start the dev stack from this worktree (AGENTS.md "Checking changes") and use the browser pane: capture the problem before changing anything, and capture the result after, at 1280 px and 390 px. For `question`, draft the answer instead and skip to step 6.
4. **Verify.** Run the checks in AGENTS.md "Checking changes" that fit the change, including axe on each page you touched at 1280 px and 390 px (stop the helper server on port 8090 afterwards). Then the docs check: go through "Keep docs in step" and update whatever the change makes wrong, in the same commit. Run `python dev/stack.py down`, and reset `dev/media` if you changed it.
5. **Commit** with Conventional Commits and `Resolves #N` (or `Refs #N` for a related extra). Several small logical commits are better than one big one. Write the message to a file in the scratchpad and run `git add <paths>` and `git commit -F <file>` as separate plain commands; the worktree guard refuses commands that mix git with inline text. If signing fails, stop and tell the owner.
6. **Hand over for review.** Do not push. Write the review package:
   - Problem and root cause, in plain terms
   - What changed: commit list (`git log --oneline origin/main..HEAD`) and files touched
   - Before/after evidence (screenshots, request/response, or repro steps and result)
   - Checks run and their results
   - Docs updated, or why none needed
   - Risks, and anything you could not verify
   - Branch name and worktree path

   Open the session's diff view for the owner. Finish by saying: review it (run `/preview` for a live copy to click through), then run `/ship` to push and open the PR, or tell me what to change.
