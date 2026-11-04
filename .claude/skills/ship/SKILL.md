---
name: ship
description: Push the reviewed branch and open a GitHub pull request against main. Only run after the owner has approved the work.
disable-model-invocation: true
---

The owner has approved the current branch. Publish it and open the PR, following AGENTS.md. Do not merge anything.

1. **Check the branch.** It must not be `main`, the working tree must be clean, and `git log --oneline origin/main..HEAD` must show commits. If not, stop and say why. Work out the issue number from the branch name (`<type>/<N>-<slug>`).
2. **Push.** `git push -u origin <branch>`. Never push anywhere else, never force.
3. **Write the PR.**
   - Title: a valid Conventional Commit header. With one commit, use its subject; with several, write one header that covers them. It becomes the squash commit, so keep it under 72 characters. The "Title format" check fails the PR otherwise.
   - Body in a temp file, following `.github/PULL_REQUEST_TEMPLATE.md`: Description (what and why), Testing (what was run and seen, with the before/after evidence from the review), Docs (what was updated, or why none), and a final `Resolves #<N>` line.
   - No label to set: the "Title format" workflow labels the PR from the title's type.
4. **Open it.** `gh pr create --base main --head <branch> --title "<title>" --body-file <file>`. If `gh` is not logged in (`gh auth status`), stop after the push and give the owner the title and body to paste into GitHub instead. Never ask for or handle a token.
5. **Report** the PR link and remind the owner to squash-merge it on GitHub. Stop there; do not close the issue or delete branches.
