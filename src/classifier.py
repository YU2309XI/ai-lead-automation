"""Lead qualification: prompt, schema enforcement, and an offline fallback."""

import os
import re

from llm import LLMError, complete_json, is_configured

CATEGORIES = [
    "Data Automation",
    "API Integration",
    "AI Automation",
    "Web Development",
    "Other",
]
PRIORITIES = ["High", "Medium", "Low"]
QUALITIES = ["Qualified", "Needs Review", "Unqualified"]

SYSTEM_PROMPT = """You qualify inbound business leads for a freelance automation developer.

Return a single JSON object with exactly these fields:
{
  "category": one of ["Data Automation", "API Integration", "AI Automation", "Web Development", "Other"],
  "priority": one of ["High", "Medium", "Low"],
  "lead_quality": one of ["Qualified", "Needs Review", "Unqualified"],
  "budget_hint": a short string such as "$500-1000", or "" if the lead gives no budget signal,
  "summary": one sentence describing what the client needs,
  "suggested_reply": a short professional reply, 2-4 sentences, no greeting placeholder like [Name]
}

Category rules:
- Spreadsheet, CSV, Excel, reporting, data cleanup or Python data workflows -> Data Automation
- Connecting two systems, third-party APIs, webhooks, syncing -> API Integration
- LLM workflows, AI agents, classification, summarisation, AI email handling -> AI Automation
- Websites, web apps, frontend or backend product work -> Web Development
- Only use Other when none of the above clearly applies

Quality rules:
- Qualified: a specific, realistic problem a developer could quote on
- Needs Review: a real request, but too vague to quote
- Unqualified: spam, cold sales pitches, recruiting, or nothing to build

Priority reflects how ready the client is to pay: a clear problem plus urgency or
budget is High; a vague future idea is Low.

Output raw JSON only. No markdown, no code fences, no commentary."""


def _normalise(value, allowed, default):
    """Map loose model output onto the allowed set, case-insensitively."""
    if not isinstance(value, str):
        return default
    cleaned = value.strip()
    for option in allowed:
        if cleaned.lower() == option.lower():
            return option
    return default


def _as_text(value, default=""):
    if isinstance(value, str) and value.strip():
        return value.strip()
    return default


def enforce_schema(raw, lead):
    """Guarantee a complete, valid record no matter what the model returned.

    n8n and Google Sheets break on missing keys, so every field is always
    present and every enum is always one of the allowed values.
    """
    raw = raw if isinstance(raw, dict) else {}
    return {
        "name": _as_text(lead.get("name"), "Unknown"),
        "company": _as_text(lead.get("company")),
        "email": _as_text(lead.get("email")),
        "message": _as_text(lead.get("message")),
        "category": _normalise(raw.get("category"), CATEGORIES, "Other"),
        "priority": _normalise(raw.get("priority"), PRIORITIES, "Medium"),
        "lead_quality": _normalise(raw.get("lead_quality"), QUALITIES, "Needs Review"),
        "budget_hint": _as_text(raw.get("budget_hint")),
        "summary": _as_text(raw.get("summary"), "No summary returned."),
        "suggested_reply": _as_text(raw.get("suggested_reply")),
    }


# --------------------------------------------------------------------------
# Offline fallback
# --------------------------------------------------------------------------

_KEYWORDS = {
    "Data Automation": ("excel", "csv", "spreadsheet", "data clean", "pandas",
                        "invoice", "pdf", "report", "data entry", "retype"),
    "API Integration": ("api", "integrat", "webhook", "sync", "shopify", "crm",
                        "hubspot", "salesforce", "zapier", "postgres",
                        "google sheets", "slack", "two-way", "both ways"),
    "AI Automation": ("llm", "gpt", "chatbot", "classif", "summaris",
                      "summariz", "ai assistant", "ai agent", "inbox",
                      "spam", "enquir", "inquir", "reads our"),
    "Web Development": ("website", "web app", "frontend", "front-end",
                        "backend", "react", "landing page"),
}

_SPAM = ("seo services", "seo agency", "guest post", "backlink", "unsubscribe",
         "crypto", "investment opportunity", "we are a leading", "free audit")

_URGENT = ("urgent", "asap", "this week", "this month", "deadline", "losing",
           "quote")

_VAGUE = ("not sure", "thinking about", "what do you offer", "do you build",
          "do you do", "next year", "just exploring", "some ideas",
          "what can you do", "any suggestions")

_BUDGET_RE = re.compile(r"[$€£]\s?\d[\d,]*(?:\s?[-–]\s?[$€£]?\d[\d,]*)?")


def _budget_hint(text):
    match = _BUDGET_RE.search(text)
    return match.group(0).strip() if match else ""


def classify_offline(lead):
    """Keyword classifier used for demos and tests. No network, no API key."""
    original = " ".join(
        str(lead.get(field, "")) for field in ("message", "company", "name")
    )
    text = original.lower()
    message = str(lead.get("message", "")).strip()

    if any(token in text for token in _SPAM) or len(message) < 25:
        raw = {
            "category": "Other",
            "priority": "Low",
            "lead_quality": "Unqualified",
            "summary": "Message does not describe a real project.",
            "suggested_reply": "",
        }
        return enforce_schema(raw, lead)

    # Score every category and take the strongest signal, rather than letting
    # whichever category happens to be listed first win on a single match.
    scores = {
        name: sum(1 for token in tokens if token in text)
        for name, tokens in _KEYWORDS.items()
    }
    best = max(scores, key=lambda name: scores[name])
    category = best if scores[best] > 0 else "Other"

    budget = _budget_hint(original)
    vague = any(token in text for token in _VAGUE)
    urgent = any(token in text for token in _URGENT) or bool(budget)
    detailed = len(message.split()) >= 25

    if vague or category == "Other":
        quality = "Needs Review"
        priority = "Low"
    elif detailed or budget:
        # A stated budget is a stronger buying signal than message length.
        # A short, specific request with a number attached is a real lead.
        quality = "Qualified"
        priority = "High" if urgent else "Medium"
    else:
        quality = "Needs Review"
        priority = "Medium"

    raw = {
        "category": category,
        "priority": priority,
        "lead_quality": quality,
        "budget_hint": budget,
        "summary": f"Client is asking about {category.lower()} work.",
        "suggested_reply": (
            "Thanks for reaching out. This is the kind of automation I build "
            "regularly, and it sounds like a good fit. Could you share a sample "
            "of your current data or workflow so I can scope it accurately? "
            "I can usually turn around a fixed quote within a day."
        ),
    }
    return enforce_schema(raw, lead)


# --------------------------------------------------------------------------
# Entry point
# --------------------------------------------------------------------------


def demo_mode_enabled():
    return os.environ.get("DEMO_MODE", "").strip().lower() in ("1", "true", "yes")


def classify_lead(lead):
    """Classify one lead. Falls back to the offline classifier on any failure."""
    if demo_mode_enabled() or not is_configured():
        record = classify_offline(lead)
        record["engine"] = "offline"
        return record

    user_prompt = (
        "Qualify this inbound lead.\n\n"
        f"Name: {lead.get('name', '')}\n"
        f"Company: {lead.get('company', '')}\n"
        f"Email: {lead.get('email', '')}\n"
        f"Message: {lead.get('message', '')}\n"
    )

    try:
        raw = complete_json(SYSTEM_PROMPT, user_prompt)
    except LLMError as exc:
        record = classify_offline(lead)
        record["engine"] = "offline"
        record["fallback_reason"] = str(exc)
        return record

    record = enforce_schema(raw, lead)
    record["engine"] = "llm"
    return record
