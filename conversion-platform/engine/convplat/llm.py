"""Shared helpers for metadata-only model calls (Azure AI Foundry regional deployment, Entra ID auth).

Every agent in the platform follows the same pattern as the triage agent:
  1. build a context from metadata only (codes, counts, names of columns and fields, rule texts);
  2. pii_gate() the exact prompt and refuse to send anything that looks like personal data;
  3. chat_json() with a strict JSON schema, temperature 0 and a fixed seed;
  4. log_ai_call() into run.AiCall (endpoint, deployment, region, prompt hash and size, PII result, tokens, latency).
"""
from __future__ import annotations

import hashlib
import json
import time
import urllib.error
import urllib.request

from .triage import pii_gate  # noqa: F401  (re-exported: one PII gate for every agent)


def chat_json(cfg: dict, token: str, messages: list[dict], schema: dict, schema_name: str,
              attempts: int = 4, max_tokens: int = 16000, seed: int = 7) -> tuple[dict, dict]:
    """One chat completion constrained to `schema`. Returns (parsed JSON, usage)."""
    url = f"{cfg['endpoint'].rstrip('/')}/openai/deployments/{cfg['deployment']}/chat/completions?api-version={cfg['api_version']}"
    body = json.dumps({"messages": messages, "temperature": 0, "seed": seed, "max_tokens": max_tokens,
                       "response_format": {"type": "json_schema",
                                           "json_schema": {"name": schema_name, "strict": True, "schema": schema}}}).encode()
    for attempt in range(attempts):
        req = urllib.request.Request(url, data=body, method="POST",
                                     headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=600) as r:
                resp = json.loads(r.read())
            return json.loads(resp["choices"][0]["message"]["content"]), resp.get("usage", {})
        except urllib.error.HTTPError as e:
            detail = e.read().decode(errors="replace")[:500]
            if e.code in (429, 500, 502, 503, 504) and attempt < attempts - 1:
                time.sleep(int(e.headers.get("Retry-After", 10 * (attempt + 1))))
                continue
            raise RuntimeError(f"model call failed: HTTP {e.code} {detail}") from e
    raise RuntimeError("unreachable")


def log_ai_call(cn, client: str, take: str, agent: str, cfg: dict, prompt: str, items: int, pii: str, status: str,
                usage: dict | None = None, ms: int | None = None, message: str = "") -> int:
    """Audit one call in run.AiCall; returns its CallId (0 when there is no database connection)."""
    if cn is None:
        return 0
    cur = cn.cursor()
    cur.execute("INSERT run.AiCall (ClientId, TakeId, Agent, Endpoint, Deployment, Region, PromptSha256, PromptChars, ItemsSent, PiiCheck, "
                "Status, InputTokens, OutputTokens, LatencyMs, Message) OUTPUT INSERTED.CallId VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                client, take, agent, cfg["endpoint"][:200], cfg["deployment"], cfg["region"], hashlib.sha256(prompt.encode()).hexdigest(),
                len(prompt), items, pii, status, (usage or {}).get("prompt_tokens"), (usage or {}).get("completion_tokens"), ms, message[:2000])
    return int(cur.fetchone()[0])
