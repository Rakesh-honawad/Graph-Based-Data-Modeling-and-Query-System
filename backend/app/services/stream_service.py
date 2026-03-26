"""
Streaming chat service — yields SSE tokens from Gemini or Groq,
then executes the SQL and streams the final answer token-by-token.

SSE format:
  data: {"type": "token",  "text": "..."}\n\n
  data: {"type": "sql",    "sql": "SELECT ..."}\n\n
  data: {"type": "rows",   "rows": [...]}\n\n
  data: {"type": "nodes",  "highlighted_nodes": [...]}\n\n
  data: {"type": "done"}\n\n
  data: {"type": "error",  "message": "..."}\n\n
"""

import os, json, re
import urllib.request
from typing import Generator

from app.services.chat_service import (
    LLM_PROVIDER, GEMINI_API_KEY, GROQ_API_KEY,
    GEMINI_URL, GROQ_URL, GROQ_MODEL,
    SYSTEM_PROMPT, _is_domain_query, _is_safe_sql,
    _run_sql, _extract_referenced_nodes, _strip_fences,
    _sessions, _build_prompt_with_history,
)


def _sse(obj: dict) -> str:
    return f"data: {json.dumps(obj)}\n\n"


def _stream_gemini(prompt: str) -> Generator[str, None, None]:
    """Stream tokens from Gemini using the streaming generateContent endpoint."""
    url = (
        "https://generativelanguage.googleapis.com/v1beta/models/"
        f"gemini-2.0-flash:streamGenerateContent?alt=sse&key={GEMINI_API_KEY}"
    )
    payload = json.dumps({
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": 0.2, "maxOutputTokens": 512},
    }).encode()
    req = urllib.request.Request(
        url, data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=60) as resp:
        for raw_line in resp:
            line = raw_line.decode("utf-8").strip()
            if not line.startswith("data:"):
                continue
            chunk_text = line[5:].strip()
            if chunk_text == "[DONE]":
                break
            try:
                chunk = json.loads(chunk_text)
                text = chunk["candidates"][0]["content"]["parts"][0].get("text", "")
                if text:
                    yield text
            except (KeyError, json.JSONDecodeError):
                continue


def _stream_groq(prompt: str) -> Generator[str, None, None]:
    """Stream tokens from Groq using OpenAI-compatible SSE."""
    payload = json.dumps({
        "model": GROQ_MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.2,
        "max_tokens": 512,
        "stream": True,
    }).encode()
    req = urllib.request.Request(
        GROQ_URL, data=payload,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {GROQ_API_KEY}",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=60) as resp:
        for raw_line in resp:
            line = raw_line.decode("utf-8").strip()
            if not line.startswith("data:"):
                continue
            chunk_text = line[5:].strip()
            if chunk_text == "[DONE]":
                break
            try:
                chunk = json.loads(chunk_text)
                delta = chunk["choices"][0]["delta"].get("content", "")
                if delta:
                    yield delta
            except (KeyError, json.JSONDecodeError):
                continue


def stream_answer(question: str, session_id: str = "default") -> Generator[str, None, None]:
    """
    Main streaming entry point.
    Phase 1: Call LLM (non-streaming) to get SQL — fast, <1s.
    Phase 2: Execute SQL.
    Phase 3: Stream the natural-language answer token by token.
    """
    question = question.strip()

    if not question:
        yield _sse({"type": "error", "message": "Please ask a question."})
        return

    # Guardrail
    if not _is_domain_query(question):
        msg = ("This system is designed to answer questions related to the "
               "Order-to-Cash dataset only — sales orders, deliveries, billing "
               "documents, payments, customers, and products.")
        for word in msg.split():
            yield _sse({"type": "token", "text": word + " "})
        yield _sse({"type": "out_of_domain"})
        yield _sse({"type": "done"})
        return

    # API key check
    if LLM_PROVIDER == "groq" and not GROQ_API_KEY:
        yield _sse({"type": "error", "message": "GROQ_API_KEY not set in .env"})
        return
    if LLM_PROVIDER == "gemini" and not GEMINI_API_KEY:
        yield _sse({"type": "error", "message": "GEMINI_API_KEY not set in .env"})
        return

    # ── Phase 1: SQL generation (non-streaming, need structured JSON) ──
    history = _sessions.get(session_id, [])
    sql_prompt = _build_prompt_with_history(question, history)

    yield _sse({"type": "status", "text": "Generating query…"})

    try:
        if LLM_PROVIDER == "groq":
            payload = json.dumps({
                "model": GROQ_MODEL,
                "messages": [{"role": "user", "content": sql_prompt}],
                "temperature": 0.1,
                "max_tokens": 1024,
            }).encode()
            req = urllib.request.Request(
                GROQ_URL, data=payload,
                headers={"Content-Type": "application/json",
                         "Authorization": f"Bearer {GROQ_API_KEY}"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=30) as resp:
                result = json.loads(resp.read())
            raw = result["choices"][0]["message"]["content"]
        else:
            payload = json.dumps({
                "contents": [{"parts": [{"text": sql_prompt}]}],
                "generationConfig": {"temperature": 0.1, "maxOutputTokens": 1024},
            }).encode()
            req = urllib.request.Request(
                GEMINI_URL.format(key=GEMINI_API_KEY), data=payload,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=30) as resp:
                result = json.loads(resp.read())
            raw = result["candidates"][0]["content"]["parts"][0]["text"]

        llm_result = json.loads(_strip_fences(raw))
    except Exception as e:
        yield _sse({"type": "error", "message": f"LLM error: {e}"})
        return

    intent = llm_result.get("intent", "")
    sql    = llm_result.get("sql", "").strip()

    if intent == "out_of_domain" or not sql:
        msg = "This system is designed to answer questions related to the Order-to-Cash dataset only."
        for word in msg.split():
            yield _sse({"type": "token", "text": word + " "})
        yield _sse({"type": "out_of_domain"})
        yield _sse({"type": "done"})
        return

    if not _is_safe_sql(sql):
        yield _sse({"type": "error", "message": "Only read operations are permitted."})
        return

    # Emit the SQL so the frontend can show it
    yield _sse({"type": "sql", "sql": sql})

    # ── Phase 2: Execute SQL ──
    yield _sse({"type": "status", "text": "Running query…"})
    try:
        rows = _run_sql(sql)
    except ValueError as e:
        yield _sse({"type": "error", "message": str(e)})
        return

    yield _sse({"type": "rows", "rows": rows[:50], "total": len(rows)})

    # Emit highlighted nodes
    highlighted = _extract_referenced_nodes(rows)
    if highlighted:
        yield _sse({"type": "nodes", "highlighted_nodes": highlighted})

    # ── Phase 3: Stream the natural language answer ──
    if not rows:
        msg = "No matching records found in the dataset for your query."
        for word in msg.split():
            yield _sse({"type": "token", "text": word + " "})
        yield _sse({"type": "done"})
        return

    yield _sse({"type": "status", "text": "Writing answer…"})

    preview = rows[:10]
    answer_prompt = (
        f"The user asked: \"{question}\"\n"
        f"SQL used: {sql}\n"
        f"Results ({len(rows)} rows, showing first {len(preview)}): "
        f"{json.dumps(preview, default=str)}\n\n"
        "Write a clear, concise answer in 2-4 sentences. "
        "Mention specific numbers and names from the data. "
        "Do not repeat the SQL. Do not use markdown. Be direct and factual."
    )

    full_answer = ""
    try:
        streamer = _stream_groq(answer_prompt) if LLM_PROVIDER == "groq" else _stream_gemini(answer_prompt)
        for token in streamer:
            full_answer += token
            yield _sse({"type": "token", "text": token})
    except Exception as e:
        # Fallback: summarise from rows without streaming
        col_names = list(rows[0].keys())
        fallback = f"Found {len(rows)} result(s). Top result: " + \
                   ", ".join(f"{k}: {rows[0][k]}" for k in col_names[:4])
        for word in fallback.split():
            yield _sse({"type": "token", "text": word + " "})
        full_answer = fallback

    # Save to conversation memory
    if session_id not in _sessions:
        _sessions[session_id] = []
    _sessions[session_id].append({
        "question": question, "sql": sql, "answer": full_answer
    })
    if len(_sessions[session_id]) > 20:
        _sessions[session_id] = _sessions[session_id][-20:]

    yield _sse({"type": "done"})
