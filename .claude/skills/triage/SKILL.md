---
name: triage
description: Sort the open Gitea issues into agent-ready, needs-info and needs-design, and propose labels and questions for the owner to approve. Changes nothing until the owner agrees.
argument-hint: <optional issue numbers, default all open issues>
disable-model-invocation: true
---

Triage the open Gitea issues so the owner can see which ones `/work-issue` can take without a conversation first. If `$ARGUMENTS` lists issue numbers (digits only, `#` optional), triage only those. Otherwise triage every open issue that has no status label yet.

Status labels (set alongside the type label, never instead of it): `agent-ready`, `needs-info`, `needs-design`.

1. **Read.** `python scripts/gitea.py issues` for the list, then `python scripts/gitea.py issue N` for each one, comments included. If the body is only an image, download it with `curl` into the scratchpad and look at it. Skip issues that already have a status label unless the owner named them, or a new comment answers the open question.
2. **Classify** each issue by what an agent would need to start:
   - `agent-ready`: a `bug`, `chore` or `documentation` issue with a reproduction or a concrete target, and a "done when" you could check. Small, self-contained enhancements qualify only when the acceptance criteria are already written and nothing below applies.
   - `needs-design`: it changes the API contract, anything under "Behavior to keep" in AGENTS.md, adds a page or setting, swaps a framework, or has more than one reasonable answer. Also `question` issues that ask for a decision rather than a fact.
   - `needs-info`: anything else that is unclear: no repro steps, no expected result, a screenshot with no explanation, scope that cannot be sized.
   - `question` issues that ask for a fact (compare with the original, check how something behaves) are agent work too: mark them `agent-ready` and say the output is a drafted answer, not code.
3. **Look before judging.** For a bug, check the code or the running dev stack enough to know the report is real and where it lives. Do not guess; a vague report stays `needs-info`.
4. **Propose.** Show one table: issue, title, type label, proposed status label, one-line reason. For each `needs-info` issue draft the two or three specific questions you would post as a comment. For each `agent-ready` issue add the likely files and a rough size (small, medium, large). Then stop and ask which to apply.
5. **Apply only what the owner approves.** `python scripts/gitea.py label N --add <status>` (and `--remove` for a stale status label), and `python scripts/gitea.py comment N "<text>"` for approved questions. Never close issues, edit their titles or bodies, or change the type label.
6. **Report** what was labelled and commented, and name the `agent-ready` issues that are safe to run in parallel (they touch different files).
