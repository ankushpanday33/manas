import json
import os
import tempfile

os.environ.setdefault("MANAS_DB", os.path.join(tempfile.mkdtemp(), "integrations.db"))
os.environ["MANAS_LLM"] = "0"

from fastapi.testclient import TestClient  # noqa: E402

from app import analytics, messaging  # noqa: E402
from app.main import app  # noqa: E402

client = TestClient(app)


def test_vendor_event_shapes_map_to_manas_events():
    mp = analytics.from_mixpanel({"event": "Checkout Abandoned", "properties": {"distinct_id": "U1", "time": 1795700000,
                                                                                "$insert_id": "abc", "cta": "talk_to_astrologer"}})
    assert mp["event_name"] == "abandoned_checkout" and mp["customer_id"] == "U1" and mp["cta"] == "talk_to_astrologer"
    ph = analytics.from_posthog({"event": {"event": "$pageview", "distinct_id": "U2", "timestamp": "2026-11-20T13:34:00Z",
                                           "uuid": "u-1", "properties": {"$pathname": "/kundli"}}})
    assert ph["event_name"] == "viewed_screen" and ph["at"] == "2026-11-20T19:04:00" and ph["screen"] == "/kundli"


def test_collect_push_and_delivery_plan():
    client.post("/api/demo/load", json={"pack": "emi_collection", "customers": 30})
    client.post("/api/brains/build", json={})
    client.post("/api/decide/all", json={})
    cid = client.get("/api/customers").json()[0]["customer_id"]

    r = client.post("/api/collect/posthog", json=[{"event": {"event": "checkout_started", "distinct_id": cid, "timestamp": "2026-11-26T10:00:00Z", "uuid": "x1"}},
                                                  {"event": {"event": "payment_failed", "distinct_id": cid, "timestamp": "2026-11-26T10:01:00Z", "uuid": "x2"}}]).json()
    assert r["stored"] == 2 and "payment_failed -> abandoned_checkout" in r["mapped_names"]

    for provider in ("mixpanel", "posthog"):
        out = client.post(f"/api/integrations/{provider}/push", json={"customer_ids": [cid]}).json()
        assert out["dry_run"] is True and out["users"] == 1
        body = json.dumps(out["requests"])
        for banned in ("phone", "overdue", "dispute", "hardship", "collections_note"):
            assert banned not in body
    sync = client.post("/api/integrations/mixpanel/sync", json={"days": 3}).json()
    assert sync["dry_run"] and sync["request"]["url"].endswith("/api/2.0/export")

    for c in client.get("/api/customers").json():
        d = client.get(f"/api/customers/{c['customer_id']}").json()["decision"]
        if d["action"] == "contact":
            dl = d["delivery"]
            assert dl["provider"]["channel"] == d["channel"]
            assert dl["language"]["template_language"] and dl["message"]["body"]
            assert "{" not in dl["message"]["body"]
            break


def test_language_and_sms_rules():
    assert messaging.choose_language("hindi", ["naukri kab lagegi? bahut tension hai"])["template_language"] == "Hinglish"
    assert messaging.choose_language("Hindi", ["मेरा भविष्य कैसा रहेगा बताइए"])["template_language"] == "Hindi"
    m = messaging.compose("gentle", "Hindi", {"name": "Ravi", "amount": "₹4,200", "link": "x"}, "sms")
    assert m["sms"]["encoding"].startswith("UCS-2") and m["sms"]["segments"] >= 1
    mr = messaging.compose("gentle", "Marathi", {"name": "Ravi", "amount": "₹4,200", "link": "x"}, "push")
    assert mr["template_language"] == "Hindi" and mr["translation_needed"]
