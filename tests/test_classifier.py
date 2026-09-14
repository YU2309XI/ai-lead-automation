import json
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from app import app  # noqa: E402
from classifier import (  # noqa: E402
    CATEGORIES,
    PRIORITIES,
    QUALITIES,
    classify_lead,
    enforce_schema,
)
from llm import LLMError, _extract_json, _message_content  # noqa: E402


@pytest.fixture(autouse=True)
def demo_mode(monkeypatch):
    monkeypatch.setenv("DEMO_MODE", "1")


@pytest.fixture
def client():
    app.config.update(TESTING=True)
    return app.test_client()


def test_enforce_schema_fills_missing_fields():
    record = enforce_schema({}, {"name": "Ada", "message": "hello"})
    assert record["category"] in CATEGORIES
    assert record["priority"] in PRIORITIES
    assert record["lead_quality"] in QUALITIES
    assert record["name"] == "Ada"


def test_enforce_schema_normalises_loose_casing():
    record = enforce_schema(
        {"category": "data automation", "priority": "HIGH", "lead_quality": "qualified"},
        {"message": "x"},
    )
    assert record["category"] == "Data Automation"
    assert record["priority"] == "High"
    assert record["lead_quality"] == "Qualified"


def test_enforce_schema_rejects_invented_values():
    record = enforce_schema({"category": "Blockchain", "priority": "Urgent"}, {"message": "x"})
    assert record["category"] == "Other"
    assert record["priority"] == "Medium"


def test_spam_is_unqualified():
    lead = {
        "name": "Growth Team",
        "message": "We are a leading SEO agency offering backlink and guest post packages.",
    }
    assert classify_lead(lead)["lead_quality"] == "Unqualified"


def test_detailed_data_request_is_qualified():
    lead = {
        "name": "Sarah",
        "message": (
            "We need to automate our weekly sales reports, our staff exports four "
            "CSV files every Friday and combines them in Excel by hand. Budget $800."
        ),
    }
    record = classify_lead(lead)
    assert record["lead_quality"] == "Qualified"
    assert record["category"] == "Data Automation"
    assert record["suggested_reply"]


def test_vague_request_needs_review():
    assert classify_lead({"message": "Hey, do you build websites?"})["lead_quality"] != "Qualified"


def test_sample_file_classifies_cleanly():
    path = os.path.join(os.path.dirname(__file__), "..", "sample-data", "leads.json")
    with open(path, encoding="utf-8") as handle:
        leads = json.load(handle)
    for lead in leads:
        record = classify_lead(lead)
        assert set(record) >= {"category", "priority", "lead_quality", "summary"}


def test_extract_json_survives_code_fences():
    assert _extract_json('```json\n{"a": 1}\n```') == {"a": 1}


def test_extract_json_survives_surrounding_prose():
    assert _extract_json('Sure! {"a": 1} Hope that helps.') == {"a": 1}


def test_message_content_raises_readable_error_on_empty_choices():
    with pytest.raises(LLMError):
        _message_content({"choices": []})


def test_message_content_handles_block_list():
    payload = {"choices": [{"message": {"content": [{"type": "text", "text": "{}"}]}}]}
    assert _message_content(payload) == "{}"


def test_health_endpoint(client):
    body = client.get("/health").get_json()
    assert body["status"] == "ok"
    assert body["demo_mode"] is True


def test_classify_requires_message(client):
    assert client.post("/classify", json={"name": "x"}).status_code == 400


def test_classify_accepts_n8n_body_wrapper(client):
    payload = {"body": {"name": "Dan", "message": "Automate our invoice data entry in Excel."}}
    body = client.post("/classify", json=payload).get_json()
    assert body["name"] == "Dan"
    assert body["category"] in CATEGORIES


def test_batch_endpoint(client):
    leads = [
        {"message": "Connect our Shopify store to Google Sheets through the API every day."},
        {"message": "Unsubscribe. We are a leading SEO agency with backlink packages."},
    ]
    body = client.post("/classify/batch", json={"leads": leads}).get_json()
    assert body["count"] == 2
    assert body["results"][1]["lead_quality"] == "Unqualified"
