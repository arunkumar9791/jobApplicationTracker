from datetime import date


def make(client, **kw):
    body = {"company": "Acme", "title": "Engineer", "date_applied": "2026-10-20", "status": "Applied", **kw}
    r = client.post("/api/applications", json=body)
    assert r.status_code == 201, r.text
    return r.json()


def test_create_and_read(client):
    a = make(client, job_id="00123", job_link="https://example.com/" + "x" * 600)
    assert a["id"] and a["job_id"] == "00123"          # leading zeros kept
    assert len(a["job_link"]) > 600
    assert client.get(f"/api/applications/{a['id']}").json()["company"] == "Acme"
    assert len(client.get("/api/applications").json()) == 1


def test_validation(client):
    assert client.post("/api/applications", json={"company": "  "}).status_code == 422
    assert client.post("/api/applications", json={"company": "A", "status": "Nope"}).status_code == 422
    assert client.post("/api/applications", json={"company": "A", "job_link": "example.com"}).status_code == 422
    assert client.post("/api/applications", json={"company": "A", "work_mode": "Office"}).status_code == 422
    assert client.post("/api/applications", json={"company": "A", "date_applied": "not a date"}).status_code == 422
    a = make(client)
    assert client.patch(f"/api/applications/{a['id']}", json={"company": ""}).status_code == 422


def test_whitespace_trimmed(client):
    a = make(client, company="  EY ", title="DE-Java-Senior ", status="Applied")
    assert a["company"] == "EY" and a["title"] == "DE-Java-Senior"


def test_status_change_logs_history_and_touches_last_updated(client):
    a = make(client)
    r = client.patch(f"/api/applications/{a['id']}", json={"status": "Screening"})
    assert r.json()["status"] == "Screening"
    assert r.json()["last_updated"] >= a["last_updated"]
    hist = client.get(f"/api/applications/{a['id']}/history").json()
    assert [(h["from_status"], h["to_status"]) for h in hist] == [(None, "Applied"), ("Applied", "Screening")]
    assert hist[0]["changed_at"].startswith("2026-10-20")   # initial entry dated on the applied date


def test_create_past_applied_seeds_applied_entry(client):
    a = make(client, status="Rejected")
    hist = client.get(f"/api/applications/{a['id']}/history").json()
    assert [h["to_status"] for h in hist] == ["Applied", "Rejected"]


def test_non_status_edit_does_not_log(client):
    a = make(client)
    client.patch(f"/api/applications/{a['id']}", json={"notes": "called HR"})
    assert len(client.get(f"/api/applications/{a['id']}/history").json()) == 1


def test_editing_field_clears_its_flags(client, session):
    from app import services
    from app.models import ApplicationCreate
    app_ = services.create_application(
        session, ApplicationCreate(company="EY", date_applied=date(2029, 10, 23)),
        flags=["date_applied:future", "source:typo"])
    r = client.patch(f"/api/applications/{app_.id}", json={"date_applied": "2026-10-23"})
    assert r.json()["flags"] == ["source:typo"]
    r = client.patch(f"/api/applications/{app_.id}", json={"flags": []})
    assert r.json()["flags"] == []


def test_bulk_status_and_delete(client):
    ids = [make(client, company=c)["id"] for c in ("A", "B", "C")]
    assert client.post("/api/applications/bulk/status", json={"ids": ids[:2], "status": "Ghosted"}).json() == {"changed": 2}
    assert client.post("/api/applications/bulk/status", json={"ids": ids, "status": "Bogus"}).status_code == 422
    assert client.post("/api/applications/bulk/delete", json={"ids": ids[1:]}).json() == {"deleted": 2}
    remaining = client.get("/api/applications").json()
    assert [(a["id"], a["status"]) for a in remaining] == [(ids[0], "Ghosted")]


def test_delete_cascades_history(client, session):
    from sqlmodel import select
    from app.models import StatusHistory
    a = make(client)
    assert client.delete(f"/api/applications/{a['id']}").status_code == 204
    assert client.get(f"/api/applications/{a['id']}").status_code == 404
    assert session.exec(select(StatusHistory)).all() == []


def test_settings(client):
    s = client.get("/api/settings").json()
    assert s["stale_days"] == 14 and s["statuses"][0]["name"] == "Wishlist"
    s["statuses"].append({"name": "On Hold", "kind": "applied", "color": "gray"})
    assert client.put("/api/settings", json={"statuses": s["statuses"]}).status_code == 422   # dedicated endpoint
    assert client.put("/api/settings/statuses", json={"statuses": s["statuses"]}).status_code == 200
    r = client.put("/api/settings", json={"stale_days": 21})
    assert r.status_code == 200 and r.json()["stale_days"] == 21
    make(client, status="On Hold")
    assert client.put("/api/settings", json={"stale_days": 0}).status_code == 422
    assert client.put("/api/settings", json={"bogus": 1}).status_code == 422
    assert client.put("/api/settings/statuses", json={"statuses": [{"name": "X", "kind": "weird"}]}).status_code == 422


def _statuses(client):
    return client.get("/api/settings").json()["statuses"]


def test_rename_status_updates_records_and_history(client):
    a = make(client)
    client.patch(f"/api/applications/{a['id']}", json={"status": "First Round"})
    statuses = [{**s, "name": "Technical Round"} if s["name"] == "First Round" else s for s in _statuses(client)]
    r = client.put("/api/settings/statuses", json={"statuses": statuses, "renames": {"First Round": "Technical Round"}})
    assert r.status_code == 200, r.text
    assert client.get(f"/api/applications/{a['id']}").json()["status"] == "Technical Round"
    hist = client.get(f"/api/applications/{a['id']}/history").json()
    assert hist[-1]["to_status"] == "Technical Round"


def test_status_list_guards(client):
    a = make(client)
    client.patch(f"/api/applications/{a['id']}", json={"status": "Ghosted"})
    base = _statuses(client)
    without_ghosted = [s for s in base if s["name"] != "Ghosted"]
    r = client.put("/api/settings/statuses", json={"statuses": without_ghosted})
    assert r.status_code == 422 and "Ghosted" in r.json()["detail"] and "1 record" in r.json()["detail"]
    assert _statuses(client) == base                                       # nothing saved
    no_applied = [s for s in base if s["name"] != "Applied"]
    assert client.put("/api/settings/statuses", json={"statuses": no_applied}).status_code == 422
    rekinded = [{**s, "kind": "closed"} if s["name"] == "Wishlist" else s for s in base]
    assert client.put("/api/settings/statuses", json={"statuses": rekinded}).status_code == 422
    reordered = [base[0], base[1], *reversed(base[2:])]
    assert client.put("/api/settings/statuses", json={"statuses": reordered}).status_code == 200


def test_status_since(client):
    a = make(client)
    assert a["status_since"].startswith("2026-10-20")                     # initial Applied entry
    r = client.patch(f"/api/applications/{a['id']}", json={"status": "Screening"}).json()
    assert r["status_since"] > a["status_since"]
    assert client.get("/api/applications").json()[0]["status_since"] == r["status_since"]


def test_backup_restore_roundtrip(client):
    a = make(client, job_id="007", notes="line1\nline2")
    client.patch(f"/api/applications/{a['id']}", json={"status": "First Round"})
    make(client, company="Wish", status="Wishlist", date_applied=None)
    client.put("/api/settings", json={"stale_days": 10})
    snap = client.get("/api/backup").json()

    client.post("/api/applications/bulk/delete", json={"ids": [x["id"] for x in snap["applications"]]})
    client.put("/api/settings", json={"stale_days": 30})
    assert client.post("/api/restore", json=snap).json() == {"applications": 2, "status_history": 3}

    again = client.get("/api/backup").json()
    for key in ("applications", "status_history", "settings"):
        assert again[key] == snap[key]


def test_restore_rejects_bad_file(client):
    make(client)
    assert client.post("/api/restore", json={"version": 99}).status_code == 422
    assert client.post("/api/restore", json={"version": 1, "applications": [{"bad": 1}], "status_history": []}).status_code == 422
    assert len(client.get("/api/applications").json()) == 1   # untouched
