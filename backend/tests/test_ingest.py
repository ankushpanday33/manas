import io
import os
import tempfile

os.environ.setdefault("MANAS_DB", os.path.join(tempfile.mkdtemp(), "ingest.db"))
os.environ["MANAS_LLM"] = "0"

from fastapi.testclient import TestClient  # noqa: E402
from openpyxl import Workbook  # noqa: E402

from app.main import app  # noqa: E402

client = TestClient(app)


def _up(source, name, content, mode="append"):
    return client.post(f"/api/ingest/{source}", files={"file": (name, content)}, data={"mode": mode, "pack": "emi_collection"})


def test_own_csv_with_own_headers_and_indian_dates():
    client.post("/api/data/reset", json={"confirm": True})
    r = _up("customers", "c.csv", b"Cust ID;Full Name;Mobile;Language\nA1;Ravi Kumar;9876543210;Hindi\nA2;Sita Devi;9876500000;Marathi\n;Nobody;1;x\n").json()
    assert r["loaded"] == 2 and r["skipped"] == 1 and r["column_mapping"]["Cust ID"] == "customer_id"
    r = _up("loans", "l.csv", b"customer_id,loan_no,outstanding,dpd,emi,remarks,note_date\n"
                              b"A1,L1,8400,12,4200,salary late will pay after the 5th,02/10/2026\nA2,L2,,40,3000,,\n").json()
    assert r["loaded"] == 1 and "missing overdue_amount" in r["skipped_rows"][0]["reason"]
    assert r["preview"][0]["note_date"] == "2026-10-02"
    # Excel works too
    wb = Workbook(); ws = wb.active
    ws.append(["customer_id", "amount", "payment date", "method", "on_time"])
    ws.append(["A1", 4200, "05/09/2026", "UPI", "yes"])
    buf = io.BytesIO(); wb.save(buf)
    r = _up("payments", "p.xlsx", buf.getvalue()).json()
    assert r["loaded"] == 1 and r["preview"][0]["paid_at"] == "2026-09-05"
    assert client.post("/api/brains/build", json={}).json()["built"] == 2
    assert client.post("/api/decide/all", json={}).json()["decided"] == 2
    brain = client.get("/api/customers/A1").json()["brain"]
    assert any(m["kind"] == "salary_dependent" for m in brain["memory"])


def test_schema_and_template():
    s = client.get("/api/ingest/schema?pack=emi_collection").json()
    assert {x["source"] for x in s["sources"]} == {"customers", "loans", "payments", "promises", "communications", "events"}
    t = client.get("/api/ingest/template/loans?pack=emi_collection")
    assert t.status_code == 200 and t.text.startswith("loan_id,")


def test_rejects_file_without_customer_id():
    r = _up("customers", "bad.csv", b"foo,bar\n1,2\n")
    assert r.status_code == 400 and "customer id" in r.json()["detail"]


def test_events_upload_drives_prediction():
    client.post("/api/data/reset", json={"confirm": True})
    _up("customers", "c.csv", b"customer_id,name\nE1,Asha Rao\n")
    _up("loans", "l.csv", b"customer_id,loan_id,overdue_amount,days_past_due,emi_amount\nE1,L9,6000,10,3000\n")
    rows = ["viewed_login", "interacted_login", "completed_login", "clicked_cta", "viewed_payment_page", "started_payment",
            "abandoned_payment", "clicked_cta", "viewed_payment_page"]
    body = "customer_id,event,event_time,cta\n" + "".join(f"E1,{e},2{6 - i % 5}/11/2026 20:0{i % 9},pay_now\n" for i, e in enumerate(rows))
    assert _up("events", "e.csv", body.encode()).json()["loaded"] == 9
    client.post("/api/brains/build", json={})
    d = client.post("/api/customers/E1/decide", json={"use_llm": False}).json()
    brain = client.get("/api/customers/E1").json()["brain"]
    fv = {f["id"]: f["value"] for f in brain["facts"]}
    assert fv["abandoned_checkout"] == "pay_now" and brain["predictions"]["purchase_propensity_7d"]["status"] == "ok"
    if d["action"] == "contact":
        assert any("halfway" in m["why"] for c in d["twin"]["candidates"][:3] for m in c["modifiers"])
