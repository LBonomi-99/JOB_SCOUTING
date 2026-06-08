"""Reusable LLM backend (Claude), shared by scorer and init_profile.

Two backends selectable in config.SCORER_BACKEND:
- "claude_cli"    -> headless `claude` CLI (subscription, free, no API key).
- "anthropic_api" -> token-billed Anthropic SDK (needs ANTHROPIC_API_KEY).

Exposes content-neutral functions:
- complete_text(user_prompt, system, prefill, max_tokens) -> str
- complete_json(...)                                      -> dict | list
- parse_json(text)                                        -> dict | list

The caller is responsible for instructing the model to reply in JSON: here we
only dispatch on the backend and parse robustly.
"""

import json
import re
import shutil
import subprocess

import config

_client = None


def _get_client():
    """Initializes the Anthropic client on first call (lazy import)."""
    global _client
    if _client is None:
        import anthropic
        _client = anthropic.Anthropic()
    return _client


def parse_json(text: str):
    """Robust JSON parsing (array or object).

    Tries json.loads directly; as a fallback extracts the first [...] or {...}
    block. Raises ValueError if neither works.
    """
    text = text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    # Choose array vs object based on the first delimiter that appears, so an
    # array nested inside an object is not extracted by mistake.
    candidates = [(text.find(c), pat) for c, pat in
                  (("[", r"\[.*\]"), ("{", r"\{.*\}")) if text.find(c) != -1]
    for _, pattern in sorted(candidates):
        match = re.search(pattern, text, re.DOTALL)
        if match:
            try:
                return json.loads(match.group(0))
            except json.JSONDecodeError:
                continue
    raise ValueError("Model response is not valid JSON")


def _call_api(user_prompt: str, system, prefill, max_tokens: int) -> str:
    """Token-billed SDK backend. `prefill` forces the reply start (e.g. '[')."""
    messages = [{"role": "user", "content": user_prompt}]
    if prefill:
        messages.append({"role": "assistant", "content": prefill})
    kwargs = {
        "model": config.ANTHROPIC_MODEL,
        "max_tokens": max_tokens,
        "messages": messages,
    }
    if system:
        kwargs["system"] = system
    message = _get_client().messages.create(**kwargs)
    return (prefill or "") + message.content[0].text


def _call_cli(user_prompt: str, system) -> str:
    """Headless `claude` CLI backend (subscription, no API key).

    In agent mode the CLI ignores --append-system-prompt, so system and
    user_prompt are concatenated into a single prompt passed via stdin. Prefill
    is not supported: we rely on robust parsing.
    """
    exe = shutil.which("claude")
    if exe is None:
        raise RuntimeError("CLI 'claude' not found in PATH")
    prompt = f"{system}\n\n{user_prompt}" if system else user_prompt
    proc = subprocess.run(
        [exe, "-p", "--output-format", "json",
         "--model", config.CLAUDE_CLI_MODEL],
        input=prompt,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=config.CLI_TIMEOUT,
    )
    if proc.returncode != 0:
        raise RuntimeError(
            f"CLI exit {proc.returncode}: {(proc.stderr or '').strip()[:300]}")
    envelope = json.loads(proc.stdout)
    result_text = envelope.get("result", "")
    if not result_text:
        raise ValueError("Empty 'result' field in the CLI output")
    return result_text


def complete_text(user_prompt: str, system: str = None, prefill: str = None,
                  max_tokens: int = None) -> str:
    """Completes a prompt on the configured backend and returns the raw text."""
    if max_tokens is None:
        max_tokens = config.MAX_TOKENS_PER_BATCH
    if config.SCORER_BACKEND == "claude_cli":
        return _call_cli(user_prompt, system)
    if config.SCORER_BACKEND == "anthropic_api":
        return _call_api(user_prompt, system, prefill, max_tokens)
    raise ValueError(f"unknown SCORER_BACKEND: {config.SCORER_BACKEND}")


def complete_json(user_prompt: str, system: str = None, prefill: str = None,
                  max_tokens: int = None):
    """Like complete_text, but parses the response as JSON (array or object)."""
    text = complete_text(user_prompt, system=system, prefill=prefill,
                         max_tokens=max_tokens)
    return parse_json(text)
