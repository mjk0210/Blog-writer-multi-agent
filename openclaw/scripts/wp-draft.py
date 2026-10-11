#!/usr/bin/env python3
"""Upload finished blog posts to WordPress as drafts for review.

Reads a post written by the blog pipeline (posts/<date>-<slug>.md), takes the
article (everything before "## Editor's notes"), converts it to HTML and
creates a WordPress *draft* through the REST API using an Application
Password. Nothing is ever published; a person reviews and publishes in
WordPress.

No AI agent runs this or sees the credentials: a systemd path unit runs it
when a new post appears (see openclaw/systemd/).

Usage:
  wp-draft.py --check            test the credentials and show the WordPress user
  wp-draft.py --pending          upload every post not uploaded yet
  wp-draft.py POST.md [...]      upload specific posts (skips ones already uploaded)
  wp-draft.py --force POST.md    upload again even if already uploaded

Settings (environment, usually from ~/.config/projectmetrics/wp.env):
  WP_URL              site URL, e.g. https://projectmetrics.co.uk
  WP_USER             WordPress username (Editor role is enough)
  WP_APP_PASSWORD     Application Password for that user
  WP_CATEGORIES       optional comma-separated category IDs, e.g. 3,7
  WP_INCLUDE_NOTES    1 to append the editor's notes and LinkedIn post to the
                      draft under a "delete before publishing" heading (default 0)
  WP_NOTIFY_TARGET    optional Telegram chat ID to notify with the draft link
  WP_NOTIFY_ACCOUNT   optional OpenClaw Telegram account id for the notice (e.g. blog)
  POSTS_DIR           default: ~/blog-writer/openclaw/workspaces/blog-coordinator/posts
  STATE_DIR           default: ~/.local/state/projectmetrics-wp
"""

from __future__ import annotations

import base64
import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

NOTES_HEADING = re.compile(r"^##\s+Editor.s notes\s*$", re.IGNORECASE | re.MULTILINE)
TITLE_LINE = re.compile(r"^#\s+(.+?)\s*$", re.MULTILINE)


def env(name: str, default: str | None = None, required: bool = False) -> str:
    value = os.environ.get(name, default)
    if required and not value:
        sys.exit(f"error: {name} is not set (see ~/.config/projectmetrics/wp.env)")
    return value or ""


def to_html(markdown_text: str) -> str:
    try:
        import markdown
    except ImportError:
        sys.exit("error: python3-markdown is missing. Install it with: sudo apt install python3-markdown")
    return markdown.markdown(markdown_text, extensions=["tables", "sane_lists", "fenced_code"])


def split_post(text: str) -> tuple[str, str, str]:
    """Return (title, article_markdown_without_title, notes_markdown)."""
    match = NOTES_HEADING.search(text)
    article, notes = (text[: match.start()], text[match.start():]) if match else (text, "")
    title_match = TITLE_LINE.search(article)
    if not title_match:
        raise ValueError("no '# Title' line found")
    title = title_match.group(1).strip()
    body = (article[: title_match.start()] + article[title_match.end():]).strip()
    return title, body, notes.strip()


def api(method: str, path: str, payload: dict | None = None) -> dict:
    url = env("WP_URL", required=True).rstrip("/") + "/wp-json/wp/v2" + path
    token = base64.b64encode(
        f"{env('WP_USER', required=True)}:{env('WP_APP_PASSWORD', required=True)}".encode()
    ).decode()
    data = json.dumps(payload).encode() if payload is not None else None
    request = urllib.request.Request(url, data=data, method=method)
    request.add_header("Authorization", f"Basic {token}")
    request.add_header("Accept", "application/json")
    request.add_header("User-Agent", "projectmetrics-wp-draft/1.0")
    if data is not None:
        request.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            return json.loads(response.read().decode() or "{}")
    except urllib.error.HTTPError as err:
        detail = err.read().decode(errors="replace")
        try:
            detail = json.loads(detail).get("message", detail)
        except ValueError:
            pass
        raise RuntimeError(f"WordPress returned HTTP {err.code}: {detail}") from None
    except urllib.error.URLError as err:
        raise RuntimeError(f"could not reach {url}: {err.reason}") from None


def state_file(post: Path) -> Path:
    state_dir = Path(env("STATE_DIR", str(Path.home() / ".local/state/projectmetrics-wp")))
    state_dir.mkdir(parents=True, exist_ok=True)
    return state_dir / (post.name + ".json")


def notify(message: str) -> None:
    target = env("WP_NOTIFY_TARGET")
    if not target:
        return
    cmd = ["openclaw", "message", "send", "--channel", "telegram", "--target", target, "-m", message]
    if env("WP_NOTIFY_ACCOUNT"):
        cmd[4:4] = ["--account", env("WP_NOTIFY_ACCOUNT")]
    try:
        subprocess.run(cmd, check=False, timeout=60, capture_output=True)
    except (OSError, subprocess.TimeoutExpired):
        pass


def upload(post: Path, force: bool = False) -> bool:
    marker = state_file(post)
    if marker.exists() and not force:
        return False
    title, body, notes = split_post(post.read_text(encoding="utf-8"))
    content = to_html(body)
    if notes and env("WP_INCLUDE_NOTES", "0") == "1":
        content += (
            "\n<hr />\n<h2>REVIEW NOTES – DELETE BEFORE PUBLISHING</h2>\n"
            + to_html(notes.replace("## ", "### "))
        )
    payload: dict = {"title": title, "content": content, "status": "draft"}
    categories = [int(c) for c in env("WP_CATEGORIES").split(",") if c.strip().isdigit()]
    if categories:
        payload["categories"] = categories
    created = api("POST", "/posts", payload)
    edit_url = f"{env('WP_URL').rstrip('/')}/wp-admin/post.php?post={created['id']}&action=edit"
    marker.write_text(json.dumps({
        "post": str(post), "id": created["id"], "title": title,
        "edit_url": edit_url, "uploaded_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
    }, indent=2))
    print(f"draft created: {title}\n  {edit_url}")
    notify(f"WordPress draft ready for review: {title}\n{edit_url}")
    return True


def main(argv: list[str]) -> int:
    if not argv or argv[0] in ("-h", "--help"):
        print(__doc__)
        return 0
    if argv[0] == "--check":
        try:
            me = api("GET", "/users/me?context=edit")
        except RuntimeError as err:
            print(f"error: {err}", file=sys.stderr)
            return 1
        roles = ", ".join(me.get("roles", [])) or "unknown"
        can_edit = me.get("capabilities", {}).get("edit_posts")
        print(f"connected as {me.get('name')} ({me.get('slug')}); roles: {roles}; can create posts: {bool(can_edit)}")
        return 0
    force = "--force" in argv
    args = [a for a in argv if a != "--force"]
    if args == ["--pending"]:
        posts_dir = Path(env("POSTS_DIR", str(Path.home() / "blog-writer/openclaw/workspaces/blog-coordinator/posts")))
        posts = sorted(posts_dir.glob("*.md")) if posts_dir.is_dir() else []
    else:
        posts = [Path(a) for a in args]
    failures = 0
    for post in posts:
        try:
            upload(post, force)
        except (RuntimeError, ValueError, OSError) as err:
            failures += 1
            print(f"{post.name}: {err}", file=sys.stderr)
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
