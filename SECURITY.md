# Security policy

## Supported versions

Only the latest release gets security fixes. Check the [releases page](https://github.com/geebru/trailer-park/releases) and update before reporting.

## Reporting a vulnerability

Please do not open a public issue for a vulnerability: that discloses it before it can be fixed.

Report it privately instead: open the repository's **Security** tab and choose **Report a vulnerability**, or go straight to <https://github.com/geebru/trailer-park/security/advisories/new>.

Include the version, what you did, what happened, and what an attacker could gain. Leave real API keys, webhook URLs and media paths out of the report.

## What to expect

Trailer Park is a hobby project with one maintainer. You will get an acknowledgement within a week. A fix or a clear answer follows as soon as the maintainer can manage it, and the report stays private until a fixed release is out. If you want credit in the release notes, say so.

## Scope

In scope: anything that lets someone read or write files outside the configured media folders, disclose the stored keys or webhook URL, run commands, or use the app to reach hosts it should not.

Out of scope:

- **No login.** Trailer Park has no authentication yet, so anyone who can reach its port can use it. That is known and documented (see the [README](README.md#security)); a login is tracked in [#15](https://github.com/geebru/trailer-park/issues/15). Reports that only say "there is no authentication" are not new.
- Anything that needs access to the `/config` directory or the host first, or an attacker already on the trusted network the README tells you to use.
- Flaws in yt-dlp, ffmpeg, Alpine or other bundled software on their own. Report those upstream. Tell the maintainer if the way Trailer Park uses them makes the flaw reachable.
