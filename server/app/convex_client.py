"""Thin wrapper for calling Convex mutations/queries from the server."""

import httpx
from .config import settings

CONVEX_URL = settings.convex_url


async def convex_mutation(name: str, args: dict) -> dict:
    """Call a Convex mutation by name."""
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"{CONVEX_URL}/api/mutation",
            json={"path": name, "args": args},
            headers={"Authorization": f"Convex {settings.convex_deploy_key}"},
        )
        resp.raise_for_status()
        return resp.json()


async def convex_query(name: str, args: dict) -> dict:
    """Call a Convex query by name."""
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"{CONVEX_URL}/api/query",
            json={"path": name, "args": args},
            headers={"Authorization": f"Convex {settings.convex_deploy_key}"},
        )
        resp.raise_for_status()
        return resp.json()
