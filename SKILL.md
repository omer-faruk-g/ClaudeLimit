---
name: claudelimit
description: "ClaudeLimit (MinToken+ClaudeLean+ClaudeCtx): small context, short output, one task per session with core-context note + clear, cache-safe habits, drain analysis, lean mode. Use on coding tasks, on its hook messages, or when the user asks about tokens, limits, usage, devam, kısa, temizle."
aliases: [mintoken, claudelean, claudectx, token-saver, token-tasarruf]
---

# ClaudeLimit

One skill for where the 5-hour and weekly limits go. It merges MinToken (references, drain catalog, log filter, status line), ClaudeLean (less in, less out) and ClaudeCtx (core context + clear). Their rules are kept below. Lines marked **[ClaudeLimit]** are new and were added by Claude from the 2026-11-08 root-cause sweep and the usage-limit articles the user pasted. Python stdlib only, no network. Paths are relative to `${CLAUDE_SKILL_DIR}`.

## 0. Where the limit goes (measured on this machine, 2026-10-25..11-08) [ClaudeLimit]
Cost units on Pro: input 1, cache write 2 (1h TTL), cache read 0.1, output 5. A 5-hour window is about 10M units.
- 4,023 requests cost 131.7M units: cache read 50%, cache write 26%, output 24% (thinking 12.7%).
- The startup floor (tools ~30K, system ~7K, skill listing ~7.5K) is re-read on every request: ~25% of all cost.
- 84% of requests carry one tool call. Prompts with ≥20 requests are 62% of cost. At 165K context, one extra round trip costs ~16K units.
- Full cache rewrites ~13%: mid-session switches (/model, error resumes) 3.9%, idle >1h 3.5%, compaction 3.1%, session starts 2.3%.
- Requests at 200K+ context are 36.8% of cost.
- Effort per request: max 33.8K units, xhigh 31.9K, high 26.2K.
- Not drains: subagents 3.3%, hooks <1%, file reads ~1%.
- A 5-minute TTL would cost +2.1% here (116 gaps >5 min), so keep the 1h default.
- Re-measure: `python scripts/drain.py YYYY-MM-DD` (cost split, causes, effort, bands, what-if) and `python scripts/drain_detail.py YYYY-MM-DD` (floor composition from the latest request shape, mid-session busts, tool calls per request).

## 1. Ground rules (MinToken)
- **Labels.** [D] verified in official docs · [G] observed in tool definitions/environment · [R] third-party report, unverified · [I] inference, unverified. Never present [R]/[I] as fact; say "unverified".
- **Verify before writing.** Before writing a settings key, env var, hook schema or slash command, re-read the docs page (index: `https://code.claude.com/docs/llms.txt`). Claude Code changes between releases; never write from memory.
- **No percentage claims.** Never promise "X% savings". Use `references/measurement.md` so the user gets their own "measured change: X → Y".
- **Consent.** Never change settings.json, hooks, permissions, `skillOverrides`, `autoCompactWindow` or any config without showing a diff and getting an explicit "yes/evet". Never install/remove other skills, plugins or tools. Managed/org policy: report only.
- **Make the invisible visible.** Most waste is where the user does not look: status line, `/usage`, `/context`, the drain catalog.
- Prefer hedged wording ("prefer / if possible / by default") over absolutes. Every suggestion states its cost (lost feature/accuracy).

## 2. Less in, less out (ClaudeLean)
Tool output stays in the context and is re-sent with every later request. Output tokens cost about five times as much as input tokens. Spend both on the result, not on bulk.

Input:
- Locate before reading: Grep with `-n` and a few context lines, or Glob. Then Read only the range you need (offset/limit).
- One bug is not twenty files. Start at the error (stack trace, failing test, file:line) and follow the call chain; widen only when the trail ends.
- Do not re-read a file that has not changed since you read it.
- Searches across many files or unfamiliar code: propose a subagent, so only its summary enters this context.
- Command output: quiet flags, `| tail -n 40`, failures-only test runs. Never `cat` a large file or a whole log.
- When the Read guard blocks a whole-file read, do what it says. Pass an explicit `limit` only when you really need the whole file.

Output:
- Lead with the result: the code change, the finding, the answer. Then at most 3 short lines: what changed, how it was verified, what is left.
- Explain why, compare alternatives or walk through how the code works only when the user asks (neden, açıkla, anlat, why, explain), and then answer just that.
- Self-correction stays internal. If you catch a mistake, fix it and report the final state; do not print the wrong version first or narrate "actually, wait".
- No recap of the plan, the question, or what you just did beyond one line.
- Change existing files with Edit, touching only the lines that change. Use Write for new files and real rewrites.
- In chat, show only the changed lines or a diff with about 3 lines of context. Never reprint unchanged imports, dependencies, type definitions, constants or classes.
- Do not add types, constants, defensive checks or boilerplate the task did not ask for.
- The user's explicit request wins: if they ask for a whole file or a detailed explanation, give it.

Fewer round trips **[ClaudeLimit]** (every request re-reads the whole context):
- Batch independent tool calls in one message: several Reads/Greps, or Edits to different files, together.
- Batch dependent shell steps into one command when a failure would not need a decision in between.
- After an Edit, do not Read the file back to check it; the tool reports failure.
- Do not split one answer across several tool calls that each print a little.
- Think as much as the task needs and stop; do not re-derive facts already established in the conversation.

## 3. One task per session: core context + clear (ClaudeCtx)
Every request re-sends the whole conversation, so cost grows with session length. `/clear` costs nothing; `/compact` is itself a large request. Keep each session to one task and carry state across `/clear` in a short core-context note.

Do this when a ClaudeCtx hook reported the soft limit and the current task is done, when it reported the hard limit and the current step is done, when a task is done and the user's next request is unrelated, or when the user asks for it (öz bağlam, temizle, handoff):
1. Never mid-edit. Leave the code consistent first.
2. Read the whole session, not only what compaction kept: `python "${CLAUDE_SKILL_DIR}/scripts/ctx/ctx_hook.py" digest --transcript "<transcript from the hook>"` prints every message the user typed. Without a hook message, leave out `--transcript`; the newest transcript is used. Take the user's rules from it verbatim.
3. Write the note to the handoff path the hook gave, or get it with `python "${CLAUDE_SKILL_DIR}/scripts/ctx/ctx_hook.py" path`. At most 40 lines, in this template:
   ```
   # Handoff YYYY-MM-DD HH:MM
   Goal: <one line>
   Status: <done, or what remains>
   Done: <changed files, one line each>
   User rules: <the user's constraints, verbatim>
   Decisions: <choices made and why, one line each>
   Open issues: <bugs, unverified assumptions>
   Next step: <the very next action; an unrelated request the user just made, verbatim>
   Key paths/commands: <build/test commands, files with line refs>
   ```
   No code dumps and no history narrative. Keep only what the next session cannot rediscover cheaply.
4. In your last message give the task's result, then one line: the context size, the note path, and that the session is being cleared.
5. Clear, as the very last action of the turn:
   - Claude desktop app: load `mcp__ccd_session_mgmt__clear_session` with ToolSearch if it is deferred, then call it with `session_id: "self"`. The app asks the user to approve. The clear happens when the turn ends, and nothing after the call carries over.
   - Without that tool (terminal, IDE), or when the hook said auto_clear is off: ask the user to run `/clear`.
   - If the user declines, continue here and do not offer again until the hook reports a higher level.

After the clear: the first session that starts after the note was written gets the note in full if it is under 30 minutes old: that is the core context. Trust it, follow its User rules, continue from Next step when the user continues, and re-read only the files that step touches. An older note is only pointed to: read it if the user continues that work ("devam", "continue"), otherwise ignore it. When the note's task is finished, overwrite the note with the new state or delete it.

While working: an unrelated question in a large session: suggest a new session instead of answering here.

## 4. Cache-safe habits [ClaudeLimit]
- **Model and effort:** pick them at session start. A `/model` switch mid-session rewrites the whole context to the cache (~1.9 × context in units; 40 switches in 30 days here). If a switch is needed, do it right after `/clear`. The cache guard hook warns when it happens. Effort: high for normal work, max only for hard problems (max cost 1.3× high per request here).
- **Cold chat (idle >1h):** the cache has expired, so the next message re-sends everything uncached. `/compact` on a cold chat pays that same full re-read and then a summary on top. Prefer a core-context note + `/clear` (section 3). The ClaudeCtx hook warns about idle gaps.
- **Do not resume old chats for their decisions:** write agreed decisions/specs to a project `.md` file (or the handoff note) and start a new session that reads it.
- **Errors and retries:** after a `<synthetic>`/API error resume, do not repeat the same large request; continue with the next small step.
- **TTL:** keep the subscription default 1h for the main conversation (5m measured +2.1% worse here). `subagentPromptCacheTtl` is optional: subagents are 3.3% of cost. Names and precedence: `references/cache-awareness.md`.
- **Check:** point the user to `/usage` (cache-miss line; W for the weekly view) and `/context`.

## 5. Startup floor and lean mode [ClaudeLimit]
- Keep always-loaded text small: CLAUDE.md under 200 lines, MEMORY.md trimmed (only its first 200 lines load), stale notes deleted, unused plugins uninstalled with `/plugin`. Skill descriptions stay short (the listing caps each at 1,536 chars). Check: `python scripts/limit.py audit` (CLAUDE.md/MEMORY.md sizes, plugins, skill listing cost with a suggested `skillOverrides` block).
- **Lean mode** (temporary, reversible) takes rarely used skills out of the listing and denies whole tools for a period of work:
  1. `python scripts/limit.py lean on --skills a,b --tools X,Y --dry-run` and show the diff.
  2. Only after the user's explicit yes, run it without `--dry-run`. It backs up settings.json and records exactly what it added in `~/.claude/claudelimit-lean.json`.
  3. `python scripts/limit.py lean off` removes exactly that; `lean status` shows it. Both take effect in a new session.
- **Conflict, flagged:** MinToken B2 says "Never deny a bare tool name". Lean mode is the one approved exception, because it is temporary and undone by `lean off`. Whether a denied tool also leaves the request's tool list is unverified [I]: check with `drain_detail.py` in the new session and report the measured floor X → Y. Plugin skills ignore `skillOverrides`.

## 6. Tools: installed → patch the gap · missing → do the job (MinToken A1–A6)
Run `python scripts/audit_tools.py` (read-only, 3 sections).

| Tool | Installed | Not installed |
|---|---|---|
| Headroom | HEADROOM_BEACON (telemetry default on [R]); OUTPUT_SHAPER default off [R]; model routing enterprise-only [R]; prefix not compressed → B4 | `filter_log.py` + D1 hook; keep only needed fields of 100+ line JSON/grep |
| Graphify | deny `Read(graphify-out/**)`; graph.json > 500 KB → `graphify query`, keep node name + path; `--code-only` | Grep → Read(offset/limit); narrow `find … \| head -20`; LSP plugin [D] |
| Ponytail | injected every turn + subagents [R]; `/ponytail lite` or `off` for trivial edits | YAGNI ladder: needed? exists? stdlib? installed dep? one line? → minimum code (security/validation/a11y exempt) |
| claude-mem | observer = model calls on your plan [R]; check CLAUDE_MEM_ONLINE_OPTIN; measure SessionStart injection | 1–2 line dated notes in CLAUDE.md, < 200 lines [D]; loads at start / after /clear, /compact [D] |
| ECC | ≥15 agents/rules/commands → descriptions every turn; unscoped rules load every session [D]; MCP schemas deferred now [D]; source repo mismatch [G] | compact → B4, memory → A4, routing → `references/model-routing.md`, MCP → B7 |
| SkillSpector | `skillspector scan <dir> --no-llm` before installs | read README/files: network, hooks, file access, deps, obfuscation |

## 7. Working rules (MinToken B1–B15)
- **B1** Internal notes/plans/comments/CLAUDE.md notes in English; reply in the user's language, short. ASCII identifiers.
- **B2** Only scoped deny rules (`Read(build/**)`) via `scripts/suggest_deny_rules.py`. Never deny a bare tool name (exception: lean mode, section 5). `.claudeignore` has no effect [D].
- **B3** Never read 200+ raw lines of build/log output: `cmd 2>&1 | python scripts/filter_log.py` (or D1 hook). Raw: `MINTOKEN_RAW=1`.
- **B4** Suggest, in one sentence (you cannot run slash commands): topic changed → `/clear` (rename first); 15+ turns or bloated → `/compact <keep what>` at a natural break (on a cold chat prefer section 3); wrong path → `/rewind` [D]. Do not repeat a suggestion.
- **B5** 20 tool calls without a user message → stop, 3-line summary, ask. Same error twice → stop, root cause, change method. Same file 3rd read → stop. Deterministic version: D2 hook.
- **B6** Failed Edit → widen old_string once; second failure → root cause in 3 lines, change method or ask. Vague task → one clarifying question before touching code; big task → plan mode.
- **B7** MCP schemas are deferred by default [D]; only names + server instructions sit in context. Real numbers: `/context`, `/mcp`. CLIs (gh, aws) are cheaper than MCP [D].
- **B8** Subagents start cold (own CLAUDE.md/MCP/skills, no parent cache) [D]. Not for short work; narrow task, summary only, `model: haiku` for simple jobs, prompt ≤ 10 lines. Do give them heavy-output work (tests, logs).
- **B9** Prefer Edit over Write; show only changed parts; 1–2 sentence wrap-up.
- **B10/B15** Cache breakers and TTL buckets → `references/cache-awareness.md`. Pick model/effort at session start.
- **B11** Task lists only for 3+ steps; take only what you need from WebFetch/WebSearch.
- **B12** "Why did my limit run out?" → `/usage` flags + attribution first, then `scripts/drain.py`, then drains. `/usage` excludes claude.ai and other devices [D]: ask.
- **B13** No "long-context price tier" claim. `CONTEXT_SIZE_WARN` (config.md) is a hygiene threshold.
- **B14** The tokenizer cannot be changed; reduce the worst content (B1, filter_log.py). `--estimate-tokens` = chars/4, rough.

Hidden drain catalog (178 items, Turkish, labelled): C1–C50 `references/hidden-drains.md` · C51–C114 `references/hidden-drains-2.md` · C115–C178 `references/hidden-drains-3.md`. `python scripts/audit_tools.py --drains` (C1–50) · `--drains2` (C51–114) · `--drains all` (C1–114) · `--drains3` (C115–178) · `--drain N` (1–178). Read only the item you need; do not load whole catalogs into context.

## 8. Hooks (warn-only, no model calls)
| Hook | Script | What it does |
|---|---|---|
| UserPromptSubmit | `scripts/cache_guard.py` **[ClaudeLimit]** | `/model` or `/effort` since the last request at ≥30K context → one-line warning with the rewrite cost |
| UserPromptSubmit / SessionStart | `scripts/ctx/ctx_hook.py prompt` / `start` | context soft/hard limit, idle cache miss, handoff note pointer/autoload |
| PreToolUse | `scripts/lean/lean_hook.py` | Read guard (whole-file read of 400+ line text files without `limit`), Write note (Write that repeats most of a file) |
| UserPromptSubmit | `scripts/lean/lean_hook.py` | reply note after 250+ words of prose or 80+ lines of code in chat |
| PreToolUse(Bash) | `scripts/hooks/pretool_bash_filter.py` | D1: pipes gradle/mvn/npm test/pytest/go test output through filter_log.py; returns `ask`, never `allow` (Bash only, not PowerShell) |
| SessionStart(resume/fork) | `scripts/hooks/resume_cost_guard.py` | G2 cold-cache warning, ≤300 chars |
| statusLine | `scripts/statusline_mintoken.py` | D3: `ctx 38% · cache 91% · warm 1h (42m left) · miss 2 (cause)` |
| optional | `scripts/hooks/session_counter.py` | D2 runaway brake (tool count, re-reads, repeated errors) |

`scripts/install_hooks.py` is MinToken's installer and still matches its old entries by the "mintoken" mark; ClaudeLimit's hooks are set by a shown diff instead.

## 9. Scripts and measuring
| Script | Purpose |
|---|---|
| `scripts/drain.py SINCE` / `scripts/drain_detail.py SINCE` **[ClaudeLimit]** | root-cause drain analysis (section 0) |
| `scripts/limit.py audit` / `lean on/off/status` **[ClaudeLimit]** | startup-floor audit, reversible lean mode (section 5) |
| `scripts/ctx/ctx_report.py --since YYYY-MM-DD [--clear-at 120000]` | context per request, sessions, idle cache misses, what-if |
| `scripts/ctx/skill_audit.py` | listing cost and usage per skill, suggested `skillOverrides` block |
| `scripts/lean/lean_report.py --since YYYY-MM-DD` | tool output per tool, biggest/repeated reads, output per request, prose per reply, mostly-unchanged rewrites |
| `scripts/measure_sessions.py --since DATE` | context per request (median/p90, share >200K), per-session totals, what D1 would remove (filters by file mtime) |
| `scripts/filter_log.py` | filter build/log/stack traces; UUID/HASH/HEX/B64 shortening with mapping file; `--estimate-tokens` (rough) |
| `scripts/suggest_deny_rules.py` | propose scoped `Read(...)` deny rules; diff; writes only with `--apply` + explicit yes |
| `scripts/audit_tools.py` / `scripts/audit_config.py` | 6-tool audit + drain catalog / read-only settings, env, hooks, skills, CLAUDE.md audit; `--profile safe/medium/aggressive` (suggestions only) |

Typical flow for "tokens/limit going fast": B12 → `scripts/drain.py` (check effort per window first) → `scripts/limit.py audit` → suggest one change → after it, measure again with `--since <change date>` and report measured X → Y.

Platform-level items ClaudeLimit cannot change: TTL values, plan pool shared with claude.ai/other devices, limit weighting, tokenizer, classifier/background requests, managed policy. It handles them by monitoring (status line, `/usage` guide in `references/context-audit-checklist.md`), warning (hooks, audits) and setting suggestions (`references/settings-cheatsheet.md`, profiles). Thresholds: `references/config.md`. Tool sizes: `references/tool-overhead.md`.
