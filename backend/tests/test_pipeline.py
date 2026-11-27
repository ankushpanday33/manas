import os
import tempfile
from datetime import date

os.environ["MANAS_DB"] = os.path.join(tempfile.mkdtemp(), "test.db")
os.environ["MANAS_LLM"] = "0"

from fastapi.testclient import TestClient  # noqa: E402

from app.brain.memory import _resolve_date  # noqa: E402
from app.main import app  # noqa: E402

client = TestClient(app)


def test_relative_dates_resolve_against_written_date():
    written = date(2026, 10, 2)
    assert _resolve_date("will pay tomorrow", written) == date(2026, 10, 3)
    assert _resolve_date("kal pakka de dunga", written) == date(2026, 10, 3)
    assert _resolve_date("salary late, will pay after the 5th", written) == date(2026, 10, 5)
    assert _resolve_date("5 tarikh ke baad", date(2026, 10, 9)) == date(2026, 11, 5)


def _run(pack: str):
    assert client.post("/api/demo/load", json={"pack": pack, "customers": 60}).status_code == 200
    built = client.post("/api/brains/build", json={}).json()
    assert built["built"] == 60
    res = client.post("/api/decide/all", json={"use_llm": False}).json()
    assert res["decided"] == 60
    customers = client.get("/api/customers").json()
    one = client.get(f"/api/customers/{customers[0]['customer_id']}").json()
    brain = one["brain"]
    assert brain["facts"] and all("formula" in f for f in brain["facts"])
    for b in brain["beliefs"]:
        assert b["status"] in {"formed", "insufficient_evidence", "needs_review"}
    d = one["decision"]
    assert d["action"] in {"contact", "hold", "human_review", "no_action"}
    assert [r["stage"] for r in d["receipts"]] == ["world", "memory", "facts", "beliefs", "twin", "council", "decision"]
    if d["action"] == "contact":
        assert d["channel"] and d["send_at"]
    p = one["brain"]["predictions"]
    assert p["purchase_propensity_7d"]["status"] in {"ok", "insufficient_evidence"}
    if p["purchase_propensity_7d"]["status"] == "ok":
        assert 0 < p["purchase_propensity_7d"]["value"] < 1 and p["purchase_propensity_7d"]["drivers"]
    assert any(b["id"] == "conversion_propensity" for b in brain["beliefs"])
    g = client.get(f"/api/customers/{customers[0]['customer_id']}/graph").json()
    assert any(n["type"] == "Event" for n in g["nodes"])
    assert client.post("/api/outcomes/simulate").status_code == 200
    stats = client.get("/api/stats").json()
    assert stats["uplift"]["simulated"] is True
    return customers


def test_emi_pipeline():
    customers = _run("emi_collection")
    # A dispute must never be auto-contacted.
    for c in customers:
        brain = client.get(f"/api/customers/{c['customer_id']}").json()
        fv = {f["id"]: f["value"] for f in brain["brain"]["facts"]}
        if fv.get("dispute_flag"):
            assert brain["decision"]["action"] == "human_review"


def test_subscription_pipeline():
    _run("subscription_renewal")


def test_ask_rules_mode():
    _run("emi_collection")
    cid = client.get("/api/customers").json()[0]["customer_id"]
    out = client.post(f"/api/customers/{cid}/ask", json={"question": "how much is overdue?"}).json()
    assert "overdue_amount" in out["cites"]
