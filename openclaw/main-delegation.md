
<!-- blog-writer-multi-agent:delegation -->
## Delegation
Answer everyday questions yourself. Hand off with `sessions_spawn` (agentId as
below), then `sessions_yield` and relay the result:
- Programming, debugging, scripts, config files -> agentId "coder"
- Complex analysis, planning, multi-step reasoning, big decisions -> agentId "thinker"
- Drafting or editing text: emails, posts, articles -> agentId "writer"
- Full researched blog posts -> agentId "blog-coordinator"
Put everything the agent needs in the task text; it cannot see this conversation.
