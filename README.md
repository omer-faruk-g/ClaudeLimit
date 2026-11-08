# ClaudeLimit

A Claude Code skill against token and usage-limit drain. It merges MinToken, ClaudeLean and ClaudeCtx into one skill, so there is one listing entry and one set of hooks.

- **Less in, less out:** Grep before Read, range reads, capped output, Edit over Write, result-first replies, fewer round trips.
- **One task per session:** a core-context note + clear at task boundaries; the note reloads after `/clear`.
- **Cache-safe habits:** pick model/effort at session start; handoff + `/clear` instead of `/compact` on a cold chat; keep the 1h TTL.
- **Measure:** `scripts/drain.py SINCE` and `scripts/drain_detail.py SINCE` give a root-cause cost split from local transcripts (read-only).
- **Startup floor:** `scripts/limit.py audit`; temporary, reversible lean mode with `scripts/limit.py lean on|off|status` (diff first, backup, undo exactly).
- **Hooks (warn-only):** cache guard (`/model`/`/effort` mid-session), context meter, Read guard / Write note / reply note, build-log filter, resume warning, status line.

Python 3 stdlib only, no network. Tests: `python -m unittest discover -s tests`.

License: GPL-3.0-or-later.
