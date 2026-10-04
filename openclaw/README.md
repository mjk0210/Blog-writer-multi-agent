# BlogGPT on OpenClaw

This folder runs the BlogGPT pipeline on an [OpenClaw](https://openclaw.ai)
gateway instead of CrewAI. The agents, prompts and stage order are the same as
`server/app/main.py`. The difference is that each agent becomes an isolated
OpenClaw agent with its own workspace, model and tool permissions.

## Architecture

```
                    ┌──────────────── OpenClaw Gateway (:18789, loopback) ────────────────┐
 Telegram / Slack   │                                                                     │
 Discord / WebChat ─┼─► blog-coordinator ──sessions_spawn──► blog-planner  (web_search)   │
                    │   (default agent,     + sessions_yield ► blog-writer   (no tools)   │
                    │    blog-pipeline skill)                ► blog-editor   (no tools)   │
                    │                                        ► blog-designer (image_gen)  │
                    │                                                                     │
 Next.js client     │                                                                     │
   │ POST /generate-blog/                                                                 │
   ▼                │                                                                     │
 FastAPI (:8002) ───┼─► /v1/chat/completions  model=openclaw/blog-planner                 │
 BLOG_BACKEND=      │                         model=openclaw/blog-writer                  │
   openclaw         │                         model=openclaw/blog-editor                  │
                    └─────────────────────────────────────────────────────────────────────┘
```

There are two ways in, and both use the same specialist agents:

1. **Chat path (agentic).** You message the `blog-coordinator` agent from any
   OpenClaw channel. Its `blog-pipeline` skill spawns each specialist as a
   sub-agent, waits for it with `sessions_yield`, and passes the output to the
   next stage. Specialists start from an isolated context, so the coordinator
   sends the plan or draft in full in each task, the same way CrewAI passes
   task context.
2. **HTTP path (deterministic).** The existing Next.js app keeps calling
   `POST /generate-blog/`. With `BLOG_BACKEND=openclaw`, FastAPI calls each
   specialist in turn through the gateway's OpenAI-compatible endpoint
   (`server/app/openclaw_backend.py`). Each call is a stateless session. The
   response format is unchanged, so the frontend needs no changes.

### CrewAI → OpenClaw mapping

| CrewAI (`server/app/main.py`) | OpenClaw                                                  |
| ----------------------------- | --------------------------------------------------------- |
| `Agent(role, goal, backstory)`| `workspaces/<id>/AGENTS.md` + `SOUL.md`                   |
| `Task(description, expected_output)` | "Task" / "Output" sections of `AGENTS.md`          |
| `Crew(process=sequential)`    | `blog-coordinator` + `skills/blog-pipeline/SKILL.md`      |
| `SerperDevTool`               | `web_search` with the Gemini provider (Google Search grounding) |
| `DallETool` (notebook)        | `image_generate` with `google/gemini-3.1-flash-image-preview` |
| `LLM(model=gemini/...)`       | `agents.defaults.model` / per-agent `model`               |
| `allow_delegation=False`      | `maxSpawnDepth: 1`; only the coordinator has session tools |

### Design choices

- **Least-privilege tools.** Every agent starts from the `minimal` profile.
  Only the planner can reach the web, and only the designer can generate
  images. The writer and editor have no tools. The coordinator has no
  `exec`/browser access and can spawn only the four blog agents
  (`subagents.allowAgents` and `requireAgentId`).
- **Cheaper models for the mechanical stages.** The planner and designer use
  `gemini-3-flash-preview`. The writer and editor use `gemini-3.1-pro-preview`.
  Change these per agent in `openclaw.json5`.
- **One API key.** Gemini covers the LLM, web search and images, so Serper and
  OpenAI keys are no longer needed.
- **Prompts live in git.** The workspaces in `openclaw/workspaces/` are
  symlinked into `~/.openclaw/`, so edits here take effect on the next run.

## Setup

Requires Node 22+ and OpenClaw 2026.6 or later (`npm i -g openclaw`).

```bash
# 1. Link the workspaces, then install the config (or merge it into an existing one)
./openclaw/scripts/install.sh

# 2. Put your keys in ~/.openclaw/.env
#    GEMINI_API_KEY=...
#    OPENCLAW_GATEWAY_TOKEN=<long random string>

# 3. Check and start
openclaw config validate
openclaw doctor
openclaw gateway restart
openclaw agents list --bindings
openclaw skills list --agent blog-coordinator   # blog-pipeline should be "ready"
```

### Use it from chat

Open WebChat (`openclaw dashboard`), or uncomment the `bindings` block in
`openclaw.json5` and connect a channel such as Telegram. Then send:

> Write a blog post about Agentic AI

### Use it from the existing web app

```bash
cd server
BLOG_BACKEND=openclaw OPENCLAW_GATEWAY_TOKEN=... \
  uv run uvicorn app.main:app --host 127.0.0.1 --port 8002 --reload
```

Or set `backend: openclaw` in `server/config/config.yaml`. Then start the
Next.js client as usual.

### Test one agent directly

```bash
curl -sS http://127.0.0.1:18789/v1/chat/completions \
  -H "Authorization: Bearer $OPENCLAW_GATEWAY_TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{"model":"openclaw/blog-planner","messages":[{"role":"user","content":"Topic: Agentic AI. Produce the content plan."}]}'
```

## Extending

- **Automation.** Add an OpenClaw cron job that sends a topic to
  `blog-coordinator` on a schedule, or enable `hooks` and `POST /hooks/agent`
  with `agentId: "blog-coordinator"` from a CMS or webhook.
- **More stages.** Add an agent under `workspaces/`, add it to `agents.list`
  and to the coordinator's `allowAgents`, then add a stage to
  `skills/blog-pipeline/SKILL.md` (and to `OpenClawPipeline.generate` for the
  HTTP path). An SEO reviewer or fact-checker would fit between the writer and
  editor.
- **Parallel research.** The planner could fan out several searches as
  sub-agents. That needs `maxSpawnDepth: 2` and session tools on the planner.

## Security

`/v1/chat/completions` gives full operator access to the gateway. Keep
`bind: "loopback"` (or a tailnet), never expose port 18789 publicly, and keep
`OPENCLAW_GATEWAY_TOKEN` on the server only; the browser never sees it.
