#!/usr/bin/env python3
"""Record what each blog post cost and report it on Telegram.

Runs after each new post appears in posts/ (via a systemd path unit) and:
  * reads the actual spend of the blog's dedicated OpenRouter key
    (GET https://openrouter.ai/api/v1/key) and attributes the increase since
    the previous post to this post;
  * reads token counts and OpenClaw's own cost estimate for the blog agents
    (`openclaw gateway usage-cost --agent <id> --json`);
  * appends a row to a CSV ledger and sends a Telegram summary.

Usage:
  blog-cost.py --pending     record every post not recorded yet (used by systemd)
  blog-cost.py --report      print totals by month from the ledger
  blog-cost.py --baseline    take a fresh reading without recording a post
                             (use after setting up, or after spend outside a post run)

Settings (environment, usually from ~/.config/projectmetrics/cost.env):
  OPENROUTER_BLOG_KEY  the OpenRouter key used only by the blog agents.
                       Without it, only OpenClaw's estimate is reported.
  COST_AGENTS          agents whose tokens count (default: the five blog-* agents)
  COST_NOTIFY_TARGET   Telegram chat ID to send the summary to (optional)
  COST_NOTIFY_ACCOUNT  OpenClaw Telegram account for the summary (e.g. blog)
  COST_GBP_PER_USD     optional fixed rate to also show pounds, e.g. 0.79
  COST_SETTLE_SECONDS  wait before reading, so the last calls are counted (default 90)
  POSTS_DIR            default: ~/blog-writer/openclaw/workspaces/blog-coordinator/posts
  COST_STATE_DIR       default: ~/.local/state/projectmetrics-cost
"""

from __future__ import annotations

import csv
import datetime as dt
import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

DEFAULT_AGENTS = "blog-coordinator,blog-planner,blog-writer,blog-editor,blog-designer"
LEDGER_FIELDS = [
    "recorded_at", "post", "title", "actual_usd", "estimated_usd",
    "input_tokens", "output_tokens", "cache_tokens", "total_tokens", "wp_edit_url", "note",
]
TOKEN_KEYS = ("input", "output", "cacheRead", "cacheWrite", "totalTokens", "totalCost")


def env(name: str, default: str = "") -> str:
    return os.environ.get(name, default)


def state_dir() -> Path:
    path = Path(env("COST_STATE_DIR", str(Path.home() / ".local/state/projectmetrics-cost")))
    path.mkdir(parents=True, exist_ok=True)
    return path


def posts_dir() -> Path:
    return Path(env("POSTS_DIR", str(Path.home() / "blog-writer/openclaw/workspaces/blog-coordinator/posts")))


# ---------- readings ----------

def openrouter_usage() -> float | None:
    key = env("OPENROUTER_BLOG_KEY")
    if not key:
        return None
    request = urllib.request.Request(env("OPENROUTER_API_BASE", "https://openrouter.ai/api/v1").rstrip("/") + "/key")
    request.add_header("Authorization", f"Bearer {key}")
    request.add_header("User-Agent", "projectmetrics-blog-cost/1.0")
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            body = json.loads(response.read().decode())
    except (urllib.error.URLError, ValueError) as err:
        print(f"warning: could not read OpenRouter key usage: {err}", file=sys.stderr)
        return None
    data = body.get("data", body)
    usage = data.get("usage")
    return float(usage) if isinstance(usage, (int, float)) else None


def openclaw_usage() -> dict:
    """Per agent, per date: token and estimated-cost totals from OpenClaw."""
    readings: dict = {}
    for agent in [a.strip() for a in env("COST_AGENTS", DEFAULT_AGENTS).split(",") if a.strip()]:
        try:
            out = subprocess.run(
                ["openclaw", "gateway", "usage-cost", "--agent", agent, "--days", "3", "--json"],
                capture_output=True, text=True, timeout=120, check=False,
            ).stdout
            report = json.loads(out)
        except (OSError, subprocess.TimeoutExpired, ValueError):
            continue
        readings[agent] = {
            day["date"]: {k: day.get(k, 0) or 0 for k in TOKEN_KEYS}
            for day in report.get("daily", []) if "date" in day
        }
    return readings


def usage_delta(now: dict, before: dict) -> dict:
    total = {k: 0.0 for k in TOKEN_KEYS}
    for agent, days in now.items():
        for date, values in days.items():
            previous = before.get(agent, {}).get(date, {})
            for k in TOKEN_KEYS:
                total[k] += max(0.0, float(values.get(k, 0)) - float(previous.get(k, 0)))
    return total


def take_reading() -> dict:
    return {"taken_at": time.time(), "openrouter_usd": openrouter_usage(), "openclaw": openclaw_usage()}


# ---------- ledger ----------

def ledger_path() -> Path:
    return state_dir() / "ledger.csv"


def recorded_posts() -> set[str]:
    if not ledger_path().exists():
        return set()
    with ledger_path().open(newline="") as fh:
        return {row["post"] for row in csv.DictReader(fh)}


def append_row(row: dict) -> None:
    new_file = not ledger_path().exists()
    with ledger_path().open("a", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=LEDGER_FIELDS)
        if new_file:
            writer.writeheader()
        writer.writerow(row)


def month_total(month: str) -> tuple[int, float]:
    count, spent = 0, 0.0
    if ledger_path().exists():
        with ledger_path().open(newline="") as fh:
            for row in csv.DictReader(fh):
                if row["recorded_at"].startswith(month) and row["note"] != "baseline":
                    count += 1
                    spent += float(row["actual_usd"] or row["estimated_usd"] or 0)
    return count, spent


def last_reading() -> dict | None:
    path = state_dir() / "last-reading.json"
    return json.loads(path.read_text()) if path.exists() else None


def save_reading(reading: dict) -> None:
    (state_dir() / "last-reading.json").write_text(json.dumps(reading))


# ---------- helpers ----------

def post_title(post: Path) -> str:
    match = re.search(r"^#\s+(.+?)\s*$", post.read_text(encoding="utf-8"), re.MULTILINE)
    return match.group(1) if match else post.stem


def wp_edit_url(post: Path) -> str:
    marker = Path(env("STATE_DIR", str(Path.home() / ".local/state/projectmetrics-wp"))) / (post.name + ".json")
    try:
        return json.loads(marker.read_text()).get("edit_url", "")
    except (OSError, ValueError):
        return ""


def money(usd: float) -> str:
    text = f"${usd:.2f}" if usd >= 0.01 else f"${usd:.4f}"
    rate = env("COST_GBP_PER_USD")
    if rate:
        try:
            text += f" (≈£{usd * float(rate):.2f})"
        except ValueError:
            pass
    return text


def notify(message: str) -> None:
    target = env("COST_NOTIFY_TARGET")
    if not target:
        return
    cmd = ["openclaw", "message", "send", "--channel", "telegram", "--target", target, "-m", message]
    if env("COST_NOTIFY_ACCOUNT"):
        cmd += ["--account", env("COST_NOTIFY_ACCOUNT")]
    try:
        result = subprocess.run(cmd, check=False, timeout=60, capture_output=True, text=True)
        if result.returncode != 0:
            print(f"warning: Telegram notification failed: {result.stderr.strip()[:300]}", file=sys.stderr)
    except (OSError, subprocess.TimeoutExpired) as err:
        print(f"warning: Telegram notification failed: {err}", file=sys.stderr)


# ---------- commands ----------

def cmd_baseline() -> int:
    reading = take_reading()
    save_reading(reading)
    for post in sorted(posts_dir().glob("*.md")) if posts_dir().is_dir() else []:
        if str(post) not in recorded_posts():
            append_row({"recorded_at": dt.datetime.now().isoformat(timespec="seconds"), "post": str(post),
                        "title": post_title(post), "note": "baseline"})
    usd = reading["openrouter_usd"]
    print("baseline taken" + (f"; OpenRouter key spend so far {money(usd)}" if usd is not None else
                              "; OPENROUTER_BLOG_KEY not set, so only estimates will be reported"))
    return 0


def cmd_pending() -> int:
    if last_reading() is None:
        return cmd_baseline()
    new_posts = [p for p in sorted(posts_dir().glob("*.md"), key=lambda p: p.stat().st_mtime)
                 if str(p) not in recorded_posts()] if posts_dir().is_dir() else []
    if not new_posts:
        return 0
    time.sleep(float(env("COST_SETTLE_SECONDS", "90")))
    before, now = last_reading(), take_reading()
    tokens = usage_delta(now["openclaw"], before.get("openclaw", {}))
    actual = None
    if now["openrouter_usd"] is not None and before.get("openrouter_usd") is not None:
        actual = max(0.0, now["openrouter_usd"] - before["openrouter_usd"])
    save_reading(now)

    for index, post in enumerate(new_posts):
        first = index == 0
        row = {
            "recorded_at": dt.datetime.now().isoformat(timespec="seconds"),
            "post": str(post), "title": post_title(post),
            "actual_usd": f"{actual:.6f}" if (first and actual is not None) else ("0" if actual is not None else ""),
            "estimated_usd": f"{tokens['totalCost']:.6f}" if first else "0",
            "input_tokens": int(tokens["input"]) if first else 0,
            "output_tokens": int(tokens["output"]) if first else 0,
            "cache_tokens": int(tokens["cacheRead"] + tokens["cacheWrite"]) if first else 0,
            "total_tokens": int(tokens["totalTokens"]) if first else 0,
            "wp_edit_url": wp_edit_url(post),
            "note": "" if first else f"cost included in {new_posts[0].name}",
        }
        append_row(row)
        if not first:
            continue
        count, spent = month_total(dt.date.today().strftime("%Y-%m"))
        cost_line = (f"Cost: {money(actual)} (OpenRouter, actual)" if actual is not None
                     else f"Cost: {money(tokens['totalCost'])} (OpenClaw estimate)")
        lines = [
            f"Post cost: {row['title']}",
            cost_line,
            f"Tokens: {int(tokens['totalTokens']):,} total "
            f"({int(tokens['input']):,} in / {int(tokens['output']):,} out / "
            f"{int(tokens['cacheRead'] + tokens['cacheWrite']):,} cache)",
            f"This month: {count} post{'s' if count != 1 else ''}, {money(spent)}",
        ]
        if actual is not None and tokens["totalCost"]:
            lines.insert(2, f"OpenClaw estimate: {money(tokens['totalCost'])}")
        if row["wp_edit_url"]:
            lines.append(f"Draft: {row['wp_edit_url']}")
        if len(new_posts) > 1:
            lines.append(f"Includes {len(new_posts) - 1} other new post(s) recorded at the same time.")
        message = "\n".join(lines)
        print(message)
        notify(message)
    return 0


def cmd_report() -> int:
    if not ledger_path().exists():
        print("no posts recorded yet")
        return 0
    months: dict[str, list[float]] = {}
    with ledger_path().open(newline="") as fh:
        for row in csv.DictReader(fh):
            if row["note"] == "baseline":
                continue
            value = float(row["actual_usd"] or row["estimated_usd"] or 0)
            months.setdefault(row["recorded_at"][:7], []).append(value)
    print(f"{'Month':<9} {'Posts':>5} {'Total':>18} {'Average':>18}")
    for month in sorted(months):
        values = months[month]
        print(f"{month:<9} {len(values):>5} {money(sum(values)):>18} {money(sum(values) / len(values)):>18}")
    print(f"\nLedger: {ledger_path()}")
    return 0


def main(argv: list[str]) -> int:
    commands = {"--pending": cmd_pending, "--report": cmd_report, "--baseline": cmd_baseline}
    if len(argv) != 1 or argv[0] not in commands:
        print(__doc__)
        return 0 if argv and argv[0] in ("-h", "--help") else 2
    return commands[argv[0]]()


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
