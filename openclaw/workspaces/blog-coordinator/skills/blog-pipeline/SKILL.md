---
name: blog-pipeline
description: Plan, write and edit a projectmetrics.co.uk article on a topic by delegating to blog-planner, blog-writer and blog-editor, pausing after the plan so Michael can approve or refine the angle.
---

# Blog pipeline

Use this whenever the user asks for a blog post, article or write-up on a topic.

## Stage 1: plan
Call `sessions_spawn` with:
- `agentId`: `blog-planner`
- `taskName`: `plan`
- `task`: `Topic: <topic>. Produce the content plan.` If the user gave an
  angle, audience detail or sources to use, add them verbatim on new lines.

Then call `sessions_yield`. The completion's `Result` is the PLAN.

## Stage 2: review (skip only if the user said "no review", "straight through" or similar)
Reply to the user with, from the PLAN:
- the **Thesis**,
- the **Outline** headings, one line each,
- the top 2–3 **Counter-arguments**,
- any **Inconsistencies found** or unverified claims the argument touches,

then ask: "Reply **go** to write it, or tell me what to change."

Stop and wait for their reply.
- **go** (or approve / yes / looks good): continue to Stage 3 with the PLAN.
- **Changes**: spawn `blog-planner` again with taskName `plan`, the topic,
  the previous PLAN verbatim, and the user's feedback verbatim under
  "Revise this plan as follows:". Yield, then repeat Stage 2.

## Stage 3: write
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

## Stage 4: edit
Call `sessions_spawn` with:
- `agentId`: `blog-editor`
- `taskName`: `edit`
- `task`:
  ```
  Topic: <topic>

  Content plan from the Content Planner (use its fact sheet and sources to check the draft):
  <PLAN, verbatim>

  Blog post from the Content Writer:
  <DRAFT, verbatim>
  ```

Then `sessions_yield`. The `Result` is the FINAL output: the article,
Editor's notes and the LinkedIn post.

## Stage 5 (optional): banner
Only when the user asked for an image. Spawn `blog-designer` with the topic and
the article's title and opening paragraph.

## Finish
- Write FINAL to `posts/<yyyy-mm-dd>-<slug>.md`.
- Reply with FINAL unchanged.

## Rules
- Run stages one at a time; each depends on the previous output.
- Pass outputs verbatim. Do not summarise the plan or draft between stages.
- If a stage returns `failed` or `timed out`, retry it once, then report the failure.
