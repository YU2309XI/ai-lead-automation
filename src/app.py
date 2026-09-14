"""HTTP service that n8n calls to qualify an inbound lead."""

import os

from flask import Flask, jsonify, request

from classifier import classify_lead, demo_mode_enabled
from llm import is_configured

app = Flask(__name__)

MAX_BATCH = 50


@app.get("/health")
def health():
    return jsonify(
        {
            "status": "ok",
            "demo_mode": demo_mode_enabled(),
            "llm_configured": is_configured(),
            "model": os.environ.get("LLM_MODEL", "gpt-4o-mini"),
        }
    )


def _read_lead(payload):
    """Accept either a bare lead object or n8n's {"body": {...}} wrapper."""
    if isinstance(payload, dict) and isinstance(payload.get("body"), dict):
        return payload["body"]
    return payload


@app.post("/classify")
def classify():
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return jsonify({"error": "Expected a JSON object body"}), 400

    lead = _read_lead(payload)
    if not str(lead.get("message", "")).strip():
        return jsonify({"error": "Field 'message' is required"}), 400

    return jsonify(classify_lead(lead))


@app.post("/classify/batch")
def classify_batch():
    payload = request.get_json(silent=True)

    if isinstance(payload, list):
        leads = payload
    elif isinstance(payload, dict) and isinstance(payload.get("leads"), list):
        leads = payload["leads"]
    else:
        return jsonify({"error": "Expected a JSON array or {'leads': [...]}"}), 400

    if len(leads) > MAX_BATCH:
        return jsonify({"error": f"Batch limit is {MAX_BATCH} leads"}), 400

    results = [classify_lead(lead) for lead in leads if isinstance(lead, dict)]
    return jsonify({"count": len(results), "results": results})


@app.errorhandler(500)
def server_error(exc):
    return jsonify({"error": "Internal error", "details": str(exc)}), 500


if __name__ == "__main__":
    # 0.0.0.0 matters: n8n usually runs in Docker and cannot reach a service
    # bound to 127.0.0.1 on the host.
    app.run(
        host=os.environ.get("HOST", "0.0.0.0"),
        port=int(os.environ.get("PORT", "8000")),
        debug=False,
    )
