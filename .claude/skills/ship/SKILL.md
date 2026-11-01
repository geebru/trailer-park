---
name: ship
description: Push the reviewed branch and open a Gitea pull request against tp-ui. Only run after the owner has approved the work.
disable-model-invocation: true
---

The owner has approved the current branch. Publish it and open the PR, following the **Ship phase** in AGENTS.md. Do not merge anything.

1. **Check the branch.** It must not be `tp-ui` or `main`, the working tree must be clean, and `git log --oneline origin/tp-ui..HEAD` must show commits. If not, stop and say why. Work out the issue number from the branch name (`<type>/<N>-<slug>`).
2. **Push.** `git push -u origin <branch>`. Never push anywhere else, never force.
3. **Write the PR.**
   - Title: a valid Conventional Commit header. With one commit, use its subject; with several, write one header that covers them. It becomes the squash commit, so keep it under 72 characters.
   - Body in a temp file, following `.gitea/PULL_REQUEST_TEMPLATE.md`: Description (what and why), Testing (what was run and seen, with the before/after evidence from the review), and a final `Resolves #<N>` line.
   - Label: copy the issue's label.
4. **Open it.** `python scripts/gitea.py pr --head <branch> --title "<title>" --body-file <file> --label <label>`. If `GITEA_TOKEN` is missing, stop after the push and give the owner the title and body to paste into Gitea instead.
5. **Report** the PR link and remind the owner to squash-merge it in Gitea. Stop there; do not close the issue or delete branches.
