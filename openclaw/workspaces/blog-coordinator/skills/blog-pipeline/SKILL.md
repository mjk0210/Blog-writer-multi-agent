---
name: blog-pipeline
description: Plan, write and edit a blog post for projectmetrics.co.uk on a topic by delegating to the blog-planner, blog-writer and blog-editor agents in sequence.
---

# Blog pipeline

Use this whenever the user asks for a blog post, article or write-up on a topic.

## Stage 1: plan
Call `sessions_spawn` with:
- `agentId`: `blog-planner`
- `taskName`: `plan`
- `task`: `Topic: <topic>. Produce the content plan.`

Then call `sessions_yield`. The completion's `Result` is the PLAN.

## Stage 2: write
Call `sessions_spawn` with:
- `agentId`: `blog-writer`
- `taskName`: `draft`
- `task`:
  ```
  Topic: <topic>

  Content plan from the Content Planner:
  <PLAN, verbatim>
  ```

Then `sessions_yield`. The `Result` is the DRAFT.

## Stage 3: edit
Call `sessions_spawn` with:
- `agentId`: `blog-editor`
- `taskName`: `edit`
- `task`:
  ```
  Topic: <topic>

  Blog post from the Content Writer:
  <DRAFT, verbatim>
  ```

Then `sessions_yield`. The `Result` is the FINAL post.

## Stage 4 (optional): banner
Only when the user asked for an image. Spawn `blog-designer` with the topic and
the post's title and introduction.

## Finish
- Write FINAL to `posts/<yyyy-mm-dd>-<slug>.md`.
- Reply with FINAL unchanged.

## Rules
- Run stages one at a time; each depends on the previous output.
- Pass outputs verbatim. Do not summarise the plan or draft between stages.
- If a stage returns `failed` or `timed out`, retry it once, then report the failure.
