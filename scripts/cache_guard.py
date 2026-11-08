#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""ClaudeLimit cache guard (UserPromptSubmit hook, warn-only, stdlib only).

Warns the user when /model or /effort was run since the last request of a large session:
a model switch makes the next request rewrite the whole context to the prompt cache
(cache write weighs 2, cache read 0.1, so the extra cost is ~1.9 x context). The idle-gap
warning lives in ctx/ctx_hook.py and is not repeated here. Never blocks the prompt.

  stdin: the hook JSON ({"transcript_path": ...}); stdout: {"systemMessage": ...} or nothing
"""
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "ctx"))
from _common import context_of, load_config, long_path  # noqa: E402

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

MIN_CTX = 30000      # below this a rewrite is cheap; stay quiet
WINDOW = 10_000_000  # Pro 5-hour window in cost units (measured, see SKILL.md)
VERB = {"en": {True: "rewrites", False: "may rewrite"}, "tr": {True: "yeniden yazar", False: "yeniden yazabilir"}}
MSG = {
    "en": "ClaudeLimit: {cmd} after the last request: this message {v} ~{k}K tokens to the cache "
          "(~{p}% of a 5h window). Pick model/effort at session start, or switch right after /clear.",
    "tr": "ClaudeLimit: son istekten sonra {cmd}: bu mesaj ~{k}K tokeni önbelleğe {v} "
          "(5 saatlik pencerenin ~%{p}'i). Model/effort'u oturum başında seç ya da /clear'dan hemen sonra değiştir.",
}


def text_of(content):
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return " ".join(b.get("text", "") for b in content if isinstance(b, dict) and b.get("type") == "text")
    return ""


def switches_since_last_request(transcript_path, chunk=512 * 1024):
    """(commands, context): /model or /effort commands after the latest main request, and its context.

    Reads only the transcript tail; returns ([], None) when no request is found in it.
    """
    try:
        f = open(long_path(transcript_path), "rb")
    except (OSError, TypeError, ValueError):
        return [], None
    with f:
        f.seek(0, os.SEEK_END)
        size = f.tell()
        f.seek(max(0, size - chunk))
        lines = f.read().split(b"\n")
    if size > chunk:
        lines = lines[1:]
    cmds = []
    for raw in reversed(lines):
        try:
            d = json.loads(raw)
        except ValueError:
            continue
        if d.get("isSidechain"):
            continue
        if d.get("type") == "system" and d.get("subtype") == "compact_boundary":
            return [], None  # compaction rewrites anyway; nothing extra to warn about
        m = d.get("message") or {}
        if d.get("type") == "assistant" and m.get("usage"):
            return cmds, context_of(m["usage"]) + (m["usage"].get("output_tokens") or 0)
        if d.get("type") == "user":
            t = text_of(m.get("content"))
            for c in ("/model", "/effort"):
                if "<command-name>" + c + "</command-name>" in t and c not in cmds:
                    cmds.append(c)
    return [], None


def check(data, cfg):
    cmds, ctx = switches_since_last_request(data.get("transcript_path"))
    if not cmds or not ctx or ctx < MIN_CTX:
        return None
    p = round(100 * 1.9 * ctx / WINDOW, 1)
    lang = cfg.get("lang") if cfg.get("lang") in MSG else "en"
    v = VERB[lang]["/model" in cmds]  # an /effort-only switch is not confirmed to bust the cache [I]
    return MSG[lang].format(cmd=" + ".join(cmds), v=v, k=round(ctx / 1000), p=p)


def main():
    try:
        data = json.loads(sys.stdin.buffer.read().decode("utf-8", errors="replace") or "{}")
        msg = check(data, load_config())
        if msg:
            print(json.dumps({"systemMessage": msg}, ensure_ascii=False))
    except Exception as e:  # warn-only: never block the prompt
        print(f"claudelimit cache_guard: {type(e).__name__}: {e}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
