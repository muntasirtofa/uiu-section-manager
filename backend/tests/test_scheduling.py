from fastapi.testclient import TestClient

from backend.app.main import app, conflicts

client = TestClient(app)


def test_bundled_fall_catalog_and_source_are_available():
    overview = client.get("/api/overview").json()
    assert overview["term"] == "Fall 2026"
    assert overview["sections"] == 791
    assert overview["programs"] == 2
    assert client.get("/api/source/pdf").headers["content-type"] == "application/pdf"
    pages = [client.get("/api/sections", params={"limit": 500, "offset": offset}).json()["items"] for offset in (0, 500)]
    catalog = pages[0] + pages[1]
    assert len(catalog) == 791
    assert all(section["credits"] is not None for section in catalog)
    assert all("faculty_name" in section["source_fields"] for section in catalog)
    assert all(meeting["start"] < meeting["end"] for section in catalog for meeting in section["meetings"])


def test_catalog_filters_by_program_search_and_preserves_meetings():
    response = client.get("/api/sections", params={"program": "BSDS", "search": "DS 1115", "limit": 50})
    items = response.json()["items"]
    assert items
    assert all(item["program"] == "BSDS" and item["course_code"] == "DS 1115" for item in items)
    assert all(item["meetings"] and item["faculty_initial"] for item in items)


def test_conflicts_are_detected_and_touching_meetings_are_allowed():
    sections = [
        {"course_code": "CSE 1001", "section": "A", "meetings": [{"day": "Sun", "start": 540, "end": 600}]},
        {"course_code": "MAT 1001", "section": "B", "meetings": [{"day": "sun", "start": 599, "end": 650}]},
        {"course_code": "PHY 1001", "section": "C", "meetings": [{"day": "Sun", "start": 650, "end": 700}]},
    ]
    result = conflicts(sections)
    assert len(result) == 1
    assert result[0]["start"] == 599 and result[0]["end"] == 600


def test_generator_returns_conflict_free_options_for_requested_program():
    response = client.post("/api/routines/generate", json={"course_selections": [{"program": "BSDS", "course_code": "DS 1115"}], "limit": 3})
    assert response.status_code == 200
    data = response.json()
    assert data["routines"]
    assert all(not routine["conflicts"] for routine in data["routines"])
    assert all(section["program"] == "BSDS" for section in data["routines"][0]["sections"])


def test_ranked_faculty_preferences_raise_best_match():
    response = client.post("/api/routines/generate", json={
        "course_selections": [{"program": "BSCSE", "course_code": "CSE 1115"}],
        "faculty_preferences": {"BSCSE:CSE 1115": ["Ashraful Islam Paran", "Nusrat Jahan Tithi"]},
        "limit": 8,
    })
    assert response.status_code == 200
    routines = response.json()["routines"]
    assert routines[0]["sections"][0]["faculty"] == "Ashraful Islam Paran"


def test_saved_routine_pdf_and_png_exports():
    generated = client.post("/api/routines/generate", json={"course_selections": [{"program": "BSCSE", "course_code": "ACT 2111"}], "limit": 1}).json()["routines"][0]
    saved = client.post("/api/routines", json={"name": "Export test routine", "section_ids": generated["section_ids"]})
    assert saved.status_code == 200
    routine_id = saved.json()["id"]
    try:
        assert client.get(f"/api/routines/{routine_id}/export.pdf").headers["content-type"] == "application/pdf"
        assert client.get(f"/api/routines/{routine_id}/export.png").headers["content-type"] == "image/png"
    finally:
        client.delete(f"/api/routines/{routine_id}")
