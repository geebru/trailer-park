---
name: triage
description: Read the open GitHub issues and report which ones /work-issue can take, which need a decision from the owner, and which need more information. Changes nothing until the owner agrees.
argument-hint: <optional issue numbers, default all open issues>
disable-model-invocation: true
---

Triage the open GitHub issues so the owner can see which ones `/work-issue` can take without a conversation first. If `$ARGUMENTS` lists issue numbers (digits only, `#` optional), triage only those. Otherwise triage every open issue. Nothing is recorded on the issues: the report is the output, and a later run reads the issues again.

1. **Read.** `gh issue list --state open --json number,title,labels` for the list, then `gh issue view N --comments` for each one. If the body is only an image, download it with `curl` into the scratchpad and look at it. Take new comments into account: an answered question can move an issue to ready.
2. **Classify** each issue by what an agent would need to start:
   - **Ready:** a `fix`, `chore`, `docs` or similar issue with a reproduction or a concrete target, and a "done when" you could check. Small, self-contained `feat` issues qualify only when the acceptance criteria are already written and nothing below applies.
   - **Needs a decision:** it changes the API contract, anything under "Behavior to keep" in AGENTS.md, adds a page or setting, swaps a framework, or has more than one reasonable answer. Also `question` issues that ask for a decision rather than a fact.
   - **Needs information:** anything else that is unclear: no repro steps, no expected result, a screenshot with no explanation, scope that cannot be sized.
   - `question` issues that ask for a fact (compare with the original, check how something behaves) are agent work too: mark them ready and say the output is a drafted answer, not code.
3. **Look before judging.** For a bug, check the code or the running dev stack enough to know the report is real and where it lives. Do not guess; a vague report needs information.
4. **Report.** One table: issue, title, class, one-line reason. Check each title against the `type(scope): subject` form and propose a corrected title where it is off. For each issue that needs information, draft the two or three specific questions you would post as a comment. For each ready issue add the likely files and a rough size (small, medium, large). Then stop and ask which comments and title fixes to apply.
5. **Apply only what the owner approves:** `gh issue comment N --body "<text>"` for approved questions and `gh issue edit N --title "<title>"` for approved title fixes. Never close issues, edit their bodies, or change labels by hand (the title decides the type label).
6. **Finish** by naming the ready issues that are safe to run in parallel (they touch different files).
