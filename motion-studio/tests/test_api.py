import time
from pathlib import Path

from fastapi.testclient import TestClient

from studio.server import app

EXAMPLE = Path(__file__).resolve().parent.parent / "examples" / "demo_transcript.json"
client = TestClient(app)


def wait(jid, timeout=120):
    for _ in range(timeout * 10):
        j = client.get(f"/api/jobs/{jid}").json()
        if j["status"] in ("done", "error"):
            return j
        time.sleep(0.1)
    raise AssertionError("timeout")


def test_meta_lists_styles():
    m = client.get("/api/meta").json()
    keys = {s["key"] for s in m["styles"]}
    assert {"neon_tech", "editorial_minimal", "bold_pop", "corporate_clean"} <= keys
    assert "small" in m["whisper_models"]


def test_full_flow_from_imported_transcript():
    files = {"transcript": ("demo.json", EXAMPLE.read_bytes(), "application/json")}
    r = client.post("/api/projects", data={"name": "Prueba", "planner": "heuristic"}, files=files)
    assert r.status_code == 200, r.text
    pid, jid = r.json()["project_id"], r.json()["job_id"]
    job = wait(jid)
    assert job["status"] == "done", job
    detail = client.get(f"/api/projects/{pid}").json()
    assert detail["plan"]["scenes"] and detail["transcript"]["words"]

    # Cambia el tipo de la primera escena y guarda
    first = detail["plan"]["scenes"][0]
    r = client.put(f"/api/projects/{pid}/plan", json={"scenes": [{"id": first["id"], "kind": "question"}]})
    assert r.status_code == 200
    assert r.json()["plan"]["scenes"][0]["kind"] == "question"

    r = client.post(f"/api/projects/{pid}/render", json={"style": "bold_pop", "aspect": "9:16", "resolution": "720p", "fps": 24, "captions": True})
    assert r.status_code == 200, r.text
    job = wait(r.json()["job_id"], timeout=300)
    assert job["status"] == "done", job
    proj = client.get(f"/api/projects/{pid}").json()["project"]
    assert proj["outputs"][-1]["resolution"] == "720x1280"
    name = proj["outputs"][-1]["file"]
    vid = client.get(f"/api/projects/{pid}/files/{name}")
    assert vid.status_code == 200 and len(vid.content) > 1000
    assert client.delete(f"/api/projects/{pid}").status_code == 200


def test_rejects_missing_input_and_bad_style():
    assert client.post("/api/projects", data={"name": "x"}).status_code == 400
    r = client.post("/api/projects/aaaaaaaaaaaa/render", json={"style": "neon_tech"})
    assert r.status_code == 404
    bad_pid = "bad-id"
    assert client.get(f"/api/projects/{bad_pid}").status_code == 400
