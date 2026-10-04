"""Run the blog pipeline through an OpenClaw gateway instead of CrewAI.

Calls each specialist agent through the gateway's OpenAI-compatible
/v1/chat/completions endpoint, in the same order as the CrewAI crew, and
passes each stage's output to the next. Each call is a fresh, stateless
session on the gateway.
"""

from __future__ import annotations

from typing import Any, Dict

import httpx


class OpenClawPipeline:
    def __init__(self, base_url: str, token: str, agents: Dict[str, str], timeout: float) -> None:
        self._client = httpx.AsyncClient(
            base_url=base_url.rstrip("/"),
            headers={"Authorization": f"Bearer {token}"},
            timeout=timeout,
        )
        self._agents = agents

    async def _run(self, stage: str, prompt: str) -> str:
        resp = await self._client.post(
            "/v1/chat/completions",
            json={
                "model": f"openclaw/{self._agents[stage]}",
                "messages": [{"role": "user", "content": prompt}],
            },
        )
        resp.raise_for_status()
        content = resp.json()["choices"][0]["message"]["content"]
        if not content or not content.strip():
            raise RuntimeError(f"OpenClaw agent for stage '{stage}' returned no content")
        return content.strip()

    async def generate(self, topic: str) -> str:
        plan = await self._run("planner", f"Topic: {topic}. Produce the content plan.")
        draft = await self._run(
            "writer", f"Topic: {topic}\n\nContent plan from the Content Planner:\n{plan}"
        )
        return await self._run(
            "editor", f"Topic: {topic}\n\nBlog post from the Content Writer:\n{draft}"
        )

    async def aclose(self) -> None:
        await self._client.aclose()


def build_pipeline(cfg: Dict[str, Any]) -> OpenClawPipeline:
    return OpenClawPipeline(
        base_url=cfg["base_url"],
        token=cfg["token"],
        agents=cfg["agents"],
        timeout=cfg["timeout_seconds"],
    )
