import io
import os
import tempfile

_tmp = tempfile.mkdtemp()
os.environ["DATABASE_URL"] = f"sqlite:///{_tmp}/test.db"
os.environ["DATA_DIR"] = _tmp
os.environ["UPLOAD_DIR"] = f"{_tmp}/uploads"
os.environ["SEED_DEMO"] = "false"
os.environ["OTP_MODE"] = "demo"
os.environ["SECRET_KEY"] = "test-secret-key-that-is-comfortably-longer-than-32-bytes"

from fastapi.testclient import TestClient  # noqa: E402

from app.ai_engine import analyze_local  # noqa: E402
from app.main import app  # noqa: E402

PNG = (b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15\xc4\x89"
       b"\x00\x00\x00\rIDATx\x9cc\xf8\xff\xff?\x00\x05\xfe\x02\xfe\xa7\x9a\xa0\xa0\x00\x00\x00\x00IEND\xaeB`\x82")


def login(client, contact, role, **extra):
    r = client.post("/api/auth/request-otp", json={"contact": contact, "role": role, "mode": "register", **extra})
    assert r.status_code == 200, r.text
    assert r.json()["demo_otp"] == "123456"
    r = client.post("/api/auth/verify-otp", json={"contact": contact, "code": "123456"})
    assert r.status_code == 200, r.text
    return {"Authorization": "Bearer " + r.json()["token"]}


def test_ai_engine_local():
    r = analyze_local("Open manhole next to hospital entrance", "Hospital Chowk")
    assert r.category == "Drainage & Sewage" and r.sub_category == "Open Manhole"
    assert r.severity >= 4 and r.vulnerability and not r.needs_review
    assert analyze_local("something is wrong").category == "Other"


def test_full_lifecycle():
    with TestClient(app) as c:
        assert c.get("/health").json() == {"status": "ok"}
        assert c.get("/").status_code == 200  # frontend served

        # bad OTP, wrong role, duplicates
        c.post("/api/auth/request-otp", json={"contact": "9111111111", "role": "citizen", "mode": "register", "name": "Asha"})
        assert c.post("/api/auth/verify-otp", json={"contact": "9111111111", "code": "000000"}).status_code == 400
        c.post("/api/auth/verify-otp", json={"contact": "9111111111", "code": "123456"})
        assert c.post("/api/auth/request-otp", json={"contact": "9111111111", "role": "citizen", "mode": "register", "name": "Asha"}).status_code == 409
        assert c.post("/api/auth/request-otp", json={"contact": "9111111111", "role": "official", "mode": "login"}).status_code == 400

        a = login(c, "9222222222", "citizen", name="Ravi")
        b = login(c, "9333333333", "citizen", name="Meera")
        o = login(c, "9444444444", "official", name="Officer", department="Roads & Public Works", ward="W7")
        other = login(c, "9555555555", "official", name="Water Officer", department="Water Supply Department")

        data = {"text": "Big pothole near the school gate, very dangerous", "lat": "16.705", "lon": "74.243", "address": "Station Road"}
        r = c.post("/api/complaints", data=data, files=[("files", ("p.png", io.BytesIO(PNG), "image/png"))], headers=a)
        assert r.status_code == 200, r.text
        first = r.json()
        assert first["issue"]["department"] == "Roads & Public Works" and not first["merged"]
        cid = first["issue"]["id"]

        # second citizen reports same pothole 40m away -> merged into the same cluster
        data2 = {**data, "lat": "16.7053", "lon": "74.2432", "text": "pothole on station road near school"}
        r = c.post("/api/complaints", data=data2, headers=b)
        assert r.json()["merged"] and r.json()["issue"]["id"] == cid and r.json()["issue"]["reports"] == 2

        # officials cannot file, citizens cannot act
        assert c.post("/api/complaints", data=data, headers=o).status_code == 403
        assert c.post(f"/api/issues/{cid}/acknowledge", json={}, headers=a).status_code == 403
        assert c.post(f"/api/issues/{cid}/acknowledge", json={}, headers=other).status_code == 403  # wrong department

        # stages cannot be skipped
        assert c.post(f"/api/issues/{cid}/progress", data={"progress": "50"}, headers=o).status_code == 400
        r = c.post(f"/api/issues/{cid}/acknowledge", json={"target_date": "2099-01-01"}, headers=o)
        assert r.status_code == 200 and r.json()["stage"] == "acknowledged"
        r = c.post(f"/api/issues/{cid}/progress", data={"progress": "60", "note": "filling"}, headers=o)
        assert r.json()["progress"] == 60

        # completion needs a photo
        assert c.post(f"/api/issues/{cid}/complete", data={"note": "done"}, headers=o).status_code == 400
        r = c.post(f"/api/issues/{cid}/complete", data={"note": "done"},
                   files=[("photo", ("after.png", io.BytesIO(PNG), "image/png"))], headers=o)
        assert r.json()["stage"] == "completed" and r.json()["progress"] == 100

        # citizen confirms once, then reopens
        assert c.post(f"/api/issues/{cid}/confirm", headers=a).status_code == 200
        assert c.post(f"/api/issues/{cid}/confirm", headers=a).status_code == 409
        assert c.post(f"/api/issues/{cid}/reopen", json={"reason": "x"}, headers=a).status_code == 400
        r = c.post(f"/api/issues/{cid}/reopen", json={"reason": "Hole is still there"}, headers=b)
        assert r.status_code == 200 and r.json()["stage"] == "reopened" and r.json()["reopen_count"] == 1

        # timeline is complete and ordered; reporters see their notifications
        stages = [e["stage"] for e in c.get(f"/api/issues/{cid}").json()["timeline"]]
        assert stages == ["received", "merged", "acknowledged", "in_progress", "completed", "reopened"]
        assert c.get("/api/notifications", headers=a).json()["unread"] >= 3

        # official views
        q = c.get("/api/official/queue", headers=o).json()
        assert q["items"][0]["id"] == cid and "breakdown" in q["items"][0]["priority"]
        assert c.get("/api/official/analytics", headers=o).status_code == 200
        r = c.post(f"/api/issues/{cid}/override", json={"priority": 99, "reason": "ministerial visit"}, headers=o)
        assert r.json()["priority"]["score"] == 99 and r.json()["priority"]["overridden"]

        # public layer exposes no personal data
        pub = c.get("/api/public/issues").json()
        assert pub and "reporters" not in pub[0] and c.get("/api/public/stats").json()["total"] == 1
        detail = c.get(f"/api/issues/{cid}").json()
        assert "reporters" not in detail
        assert "reporters" in c.get(f"/api/issues/{cid}", headers=o).json()
