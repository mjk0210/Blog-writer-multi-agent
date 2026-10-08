# BlogGPT on OpenClaw

This folder runs the BlogGPT pipeline on an [OpenClaw](https://openclaw.ai)
gateway instead of CrewAI, alongside a small set of task-routed agents. The blog
agents, prompts and stage order match `server/app/main.py`. The difference is
that each agent becomes an isolated OpenClaw agent with its own workspace, model
and tool permissions.

**Requires OpenClaw 2026.9 or later.** That release changed the config format
(`agents.entries` instead of `agents.list`, `tools.alsoAllow` to add tools to a
profile, `mediaModels.image` for image generation). Tested on 2026.9.8.

## Agents and models

All models go through [OpenRouter](https://openrouter.ai) with one API key.

| Agent              | Job                                        | Model (OpenRouter)        | Tools                          |
| ------------------ | ------------------------------------------ | ------------------------- | ------------------------------ |
| `main`             | Everyday chat; hands work to the others    | MiniMax (`General`)       | your existing setup            |
| (heartbeat)        | Periodic checks, `main` only               | Gemini Flash (`Flash`)    |                                |
| `coder`            | Programming, scripts, config               | DeepSeek (`Coder`)        | `coding` profile               |
| `thinker`          | Complex analysis, planning, decisions      | Claude Opus (`Opus`)      | `coding` profile               |
| `writer`           | Emails, posts, rewrites                    | Claude Sonnet (`Sonnet`)  | files + web                    |
| `blog-coordinator` | Runs the blog pipeline                     | MiniMax                   | spawn/yield sub-agents, files  |
| `blog-planner`     | Research and outline                       | Gemini Flash              | `web_search`, `web_fetch`      |
| `blog-writer`      | Drafts the post                            | Claude Sonnet             | none                           |
| `blog-editor`      | Edits the post                             | Claude Sonnet             | none                           |
| `blog-designer`    | Optional banner image                      | Gemini Flash              | `image_generate`               |

The names in brackets are aliases: `/model Opus` in chat switches the current
conversation's model.

## Architecture

```
                    ┌──────────────────── OpenClaw Gateway (:18789, loopback) ───────────────────┐
 Telegram / Slack   │                                                                            │
 Discord / WebChat ─┼─► main ──sessions_spawn──► coder / thinker / writer                        │
                    │    │                                                                       │
                    │    └──► blog-coordinator ──sessions_spawn──► blog-planner  (web_search)    │
                    │         (blog-pipeline skill) + sessions_yield ► blog-writer               │
                    │                                               ► blog-editor               │
                    │                                               ► blog-designer (image_gen) │
                    │                                                                            │
 Next.js client     │                                                                            │
   │ POST /generate-blog/                                                                        │
   ▼                │                                                                            │
 FastAPI (:8002) ───┼─► /v1/chat/completions  model=openclaw/blog-planner → blog-writer → editor │
 BLOG_BACKEND=openclaw                                                                           │
                    └────────────────────────────────────────────────────────────────────────────┘
```

There are two ways into the blog pipeline, and both use the same specialist agents:

1. **Chat path (agentic).** Ask `main` for a blog post, or talk to
   `blog-coordinator` directly. Its `blog-pipeline` skill spawns each specialist
   as a sub-agent, waits for it with `sessions_yield`, and passes the output to
   the next stage. Specialists start from an isolated context, so the
   coordinator sends the plan or draft in full in each task, the same way
   CrewAI passes task context. A spawned agent runs on its own configured
   model, not the caller's.
2. **HTTP path (deterministic).** The existing Next.js app keeps calling
   `POST /generate-blog/`. With `BLOG_BACKEND=openclaw`, FastAPI calls each
   specialist in turn through the gateway's OpenAI-compatible endpoint
   (`server/app/openclaw_backend.py`). The response format is unchanged.

### CrewAI → OpenClaw mapping

| CrewAI (`server/app/main.py`)        | OpenClaw                                              |
| ------------------------------------ | ----------------------------------------------------- |
| `Agent(role, goal, backstory)`       | `workspaces/<id>/AGENTS.md` + `SOUL.md`               |
| `Task(description, expected_output)` | "Task" / "Output" sections of `AGENTS.md`             |
| `Crew(process=sequential)`           | `blog-coordinator` + `skills/blog-pipeline/SKILL.md`  |
| `SerperDevTool`                      | `web_search` (DuckDuckGo, Gemini or another provider) |
| `DallETool` (notebook)               | `image_generate` via `agents.defaults.mediaModels.image` |
| `LLM(model=gemini/...)`              | per-agent `model` in `agents.entries`                 |
| `allow_delegation=False`             | only the coordinator and `main` have spawn tools      |

### Design choices

- **Least-privilege tools.** Each blog agent starts from the `minimal`
  profile and adds only what it needs with `alsoAllow`. Only the planner can
  reach the web and only the designer can generate images. The coordinator has
  no `exec` or browser access and can spawn only the four blog agents
  (`subagents.allowAgents` and `requireAgentId`).
- **Model per job.** Cheap, fast models for routing and research; Sonnet for
  prose; Opus only for work that needs it.
- **Non-destructive install.** `openclaw.json5` is a patch. Because agents are
  keyed by id in `agents.entries`, merging it keeps your other agents,
  channels and gateway settings.
- **Prompts live in git.** The workspaces are symlinked into `~/.openclaw/`, so
  a `git pull` updates the agents' instructions.

## Files

| Path                     | What it is                                                    |
| ------------------------ | ------------------------------------------------------------- |
| `openclaw.json5`         | Config patch: agents, models, aliases, tool policies          |
| `workspaces/<id>/`       | Each agent's `AGENTS.md` (and `SOUL.md` for blog agents)      |
| `main-delegation.md`     | Handoff rules appended to your `main` agent's `AGENTS.md`     |
| `scripts/install.sh`     | Links workspaces, merges the patch, adds the handoff rules    |
| `gateway-http.json5`     | Optional patch enabling `/v1/chat/completions` for FastAPI    |
| `.env.example`           | Keys to put in `~/.openclaw/.env`                             |

## Setup

You need a working OpenClaw 2026.9+ install (`openclaw onboard` done, gateway
running) and an OpenRouter API key.

```bash
git clone -b claude/exciting-edison-ydil7z https://github.com/mjk0210/Blog-writer-multi-agent.git ~/blog-writer
cd ~/blog-writer

# 1. Check the model names your OpenRouter account offers
echo 'OPENROUTER_API_KEY=sk-or-...' >> ~/.openclaw/.env
openclaw models list --provider openrouter | grep -i -E "minimax|gemini.*flash|deepseek|opus|sonnet"

# 2. Install (shows a dry run, then asks before applying; backs up your config)
./openclaw/scripts/install.sh
#    Different model names? Override any of them:
#    GENERAL_MODEL=openrouter/minimax/... CODING_MODEL=... ./openclaw/scripts/install.sh

# 3. Web search for the planner: pick one provider (DuckDuckGo needs no key)
openclaw config get tools.web.search.provider || openclaw config set tools.web.search.provider duckduckgo

# 4. Restart and check
openclaw gateway restart
openclaw agents list
openclaw skills list --agent blog-coordinator | grep blog-pipeline   # "ready"
```

Running `install.sh` again is safe: it re-applies the same patch and adds the
handoff rules only once. If a `~/.openclaw/workspace-<id>` folder already exists
as a real directory (not a link), the script leaves it alone and says so.

Undo with the backup the script prints:
`cp ~/.openclaw/openclaw.json.bak-<timestamp> ~/.openclaw/openclaw.json && openclaw gateway restart`.

## Testing

```bash
# Each specialist on its own (quick, cheap)
openclaw agent --agent blog-planner --timeout 300 -m "Topic: Raspberry Pi home labs. Produce the content plan."
openclaw agent --agent coder --timeout 300 -m "One-liner to show the 5 largest files in my home folder"

# The full pipeline (a few minutes)
openclaw agent --agent blog-coordinator --timeout 900 -m "Write a blog post about Raspberry Pi home labs"

# In a second terminal: watch every agent's progress live (plan -> draft -> edit)
openclaw sessions --all-agents tail --follow
```

### Following a run

| Where     | Command                                                | Shows                                          |
| --------- | ------------------------------------------------------ | ---------------------------------------------- |
| Terminal  | `openclaw sessions --all-agents tail --follow`         | Live progress lines from all agents            |
| Terminal  | `openclaw sessions --all-agents --active 15`           | Which agent sessions ran in the last 15 min    |
| Terminal  | `openclaw logs --follow --plain \| grep -i -E "subagent\|spawn\|blog-"` | Spawn and completion events  |
| Chat      | `/subagents list`, `/subagents info 1`, `/subagents log 1 tools` | Each stage, its status, and its output |
| Chat      | `/status`                                              | Running and finished sub-agents, tokens, cost  |
| Dashboard | `openclaw dashboard` → the coordinator's session       | Sub-agent runs inside the session transcript   |

The `/subagents` commands only see runs started from the conversation you type
them in. Use them in the same chat where you asked for the post.

**Where the post goes.** The coordinator waits for each stage with
`sessions_yield`, which ends its turn, so `openclaw agent` usually returns after
a short acknowledgement while the stages carry on in the background. The
finished post lands in the coordinator's session and in
`workspaces/blog-coordinator/posts/` (ignored by git), not in the terminal:

```bash
ls -lt ~/blog-writer/openclaw/workspaces/blog-coordinator/posts/
openclaw sessions tail --agent blog-coordinator --tail 40      # or --follow while it runs
```

From chat the result comes back to the same conversation: ask your main agent
*"Ask blog-coordinator to write a post about X"*, and use `/subagents list` to
watch the stages.

## Raspberry Pi notes

- Startup on a Pi 4 can take over a minute, longer than `openclaw gateway
  restart` waits, so it may report a timeout even though the gateway comes up.
  Check with `openclaw gateway status | grep Connectivity`.
- Speed up restarts with a compile cache (`systemctl --user edit openclaw-gateway.service`):

  ```ini
  [Service]
  Environment=NODE_COMPILE_CACHE=/var/tmp/openclaw-compile-cache
  RestartSec=5
  TimeoutStartSec=180
  ```

  Then run `systemctl --user daemon-reload && systemctl --user restart openclaw-gateway.service`.
  2026.9 expects `RestartSec=5`; other values are flagged by `openclaw gateway status`.
- A USB SSD instead of the SD card makes the gateway's SQLite work much faster.
- Close forgotten `openclaw tui` or `openclaw logs --follow` sessions; they
  keep polling the gateway.

## Troubleshooting

| Error | Cause and fix |
| ----- | ------------- |
| `Unknown agent id "blog-coordinator"` | The agents aren't in the config. Re-run `install.sh`. |
| `No callable tools remain after resolving explicit tool allowlist` | An agent uses `tools.allow` with a limited profile. On 2026.9+ use `alsoAllow`; `install.sh` sets `allow: null` to remove old lists. |
| `Unknown config path: agents.list` | 2026.9+ stores agents in `agents.entries`; use the files in this folder, not older instructions. |
| `Unrecognized key: "imageGenerationModel"` | Renamed to `agents.defaults.mediaModels.image` in 2026.9. |
| `multi-agent rosters require agents.ownership...` | Run `openclaw doctor --fix`, then re-run `install.sh`. |
| `Failed to fetch OpenRouter models` | The Pi can't reach openrouter.ai, or it timed out during a slow start. Test with `curl -s -o /dev/null -w "%{http_code}\n" https://openrouter.ai/api/v1/models`. |
| Coordinator writes the post itself | Check `blog-pipeline` is "ready"; try a stronger coordinator model. |

## Use it from the existing web app

```bash
openclaw config patch --file openclaw/gateway-http.json5   # enable /v1/chat/completions
cd server
BLOG_BACKEND=openclaw OPENCLAW_GATEWAY_TOKEN=... \
  uv run uvicorn app.main:app --host 127.0.0.1 --port 8002 --reload
```

Or set `backend: openclaw` in `server/config/config.yaml`. Then start the
Next.js client as usual. The gateway must use token auth
(`gateway.auth.mode: "token"`) with the same `OPENCLAW_GATEWAY_TOKEN`.

## Extending

- **Automation.** Add an OpenClaw cron job that sends a topic to
  `blog-coordinator` on a schedule, or enable `hooks` and `POST /hooks/agent`
  with `agentId: "blog-coordinator"` from a CMS or webhook.
- **More stages.** Add an agent under `workspaces/` and in
  `agents.entries`, add it to the coordinator's `allowAgents`, then add a stage
  to `skills/blog-pipeline/SKILL.md` (and to `OpenClawPipeline.generate` for
  the HTTP path). An SEO reviewer or fact-checker would fit between the writer
  and editor.

## Security

`/v1/chat/completions` gives full operator access to the gateway. Keep
`bind: "loopback"` (or a tailnet), never expose port 18789 publicly, and keep
`OPENCLAW_GATEWAY_TOKEN` on the server only; the browser never sees it.
