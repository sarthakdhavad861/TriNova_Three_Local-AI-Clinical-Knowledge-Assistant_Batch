# Mock backend for the browser smoke test. Replays NDJSON fixtures produced by the REAL backend pipeline and mimics the
# encounter contract (token header, uniform 404, history + notes per encounter). It is NOT the real backend.
import json, pathlib, secrets, sys, time, uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse
ROOT = pathlib.Path(__file__).parent; DIST = ROOT / "dist"; FIX = ROOT / "fixtures"
ENC = {}      # id -> {token, label, messages, notes}
LOG = []      # (method, path, token_header_present) for assertions
class H(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.0"
    def log_message(self, *a): pass
    def _json(self, obj, status=200):
        b = json.dumps(obj).encode(); self.send_response(status)
        self.send_header("Content-Type", "application/json"); self.send_header("Content-Length", str(len(b))); self.end_headers(); self.wfile.write(b)
    def _enc(self, eid):
        e = ENC.get(eid)
        if not e or not secrets.compare_digest(e["token"], self.headers.get("X-Encounter-Token") or ""):
            self._json({"detail": "Encounter not found"}, 404); return None
        return e
    def body(self):
        n = int(self.headers.get("Content-Length") or 0); return self.rfile.read(n)
    def do_GET(self):
        p = urlparse(self.path).path; LOG.append(("GET", p, bool(self.headers.get("X-Encounter-Token"))))
        if p == "/__reset": ENC.clear(); LOG.clear(); return self._json({"ok": True})
        if p == "/__log": return self._json(LOG)
        if p == "/__state": return self._json({k: {"messages": len(v["messages"]), "notes": len(v["notes"])} for k, v in ENC.items()})
        if p == "/" and "text/html" not in (self.headers.get("Accept") or ""): return self._json({"status": "ok", "knowledge": {"sources": 1, "chunks": 3, "records": 3}, "total_chunks": 3})
        if p == "/sources": return self._json({"totals": {"sources": 1, "chunks": 3, "records": 3}, "sources": [
            {"source_id": "fict-md", "display_name": "fict.md", "kind": "text", "category": None, "license": "synthetic test data", "origin": "unit-test", "version": 1, "chunk_count": 3, "record_count": 0, "warnings": []}]})
        if p.startswith("/chunks/"): return self._json(json.loads((FIX / "chunk.json").read_text()))
        if p.startswith("/jobs/"): return self._json({"status": "success", "message": "Indexed.", "total_chunks": 4})
        if p.startswith("/encounters/"):
            parts = p.split("/"); e = self._enc(parts[2])
            if not e: return
            if parts[3:] == ["messages"]: return self._json({"messages": e["messages"]})
            if parts[3:] == ["context"]: return self._json({"notes": e["notes"]})
            return self._json({"encounter_id": parts[2], "label": e["label"]})
        if p == "/" or p == "/index.html" or p == "": p = "/index.html"
        f = DIST / p.lstrip("/")
        if f.is_file():
            b = f.read_bytes(); self.send_response(200); self.send_header("Content-Type", "text/html" if f.suffix == ".html" else "text/javascript")
            self.send_header("Content-Length", str(len(b))); self.end_headers(); self.wfile.write(b); return
        self._json({"detail": "not found"}, 404)
    def do_POST(self):
        p = urlparse(self.path).path; LOG.append(("POST", p, bool(self.headers.get("X-Encounter-Token")))); raw = self.body()
        if p == "/encounters":
            eid, tok = uuid.uuid4().hex, secrets.token_urlsafe(32); label = json.loads(raw or b"{}").get("label", "")
            ENC[eid] = {"token": tok, "label": label, "messages": [], "notes": [], "n": 0}
            return self._json({"encounter_id": eid, "access_token": tok, "label": label, "created_at": time.time(), "notice": "x"}, 201)
        if p == "/sources": return self._json({"status": "accepted", "job_id": "1"}, 202)
        parts = p.split("/")
        if p.startswith("/encounters/") and len(parts) == 4:
            e = self._enc(parts[2])
            if not e: return
            if parts[3] == "context":
                e["n"] += 1; e["notes"].append({"note_id": e["n"], "text": json.loads(raw)["text"], "created_at": time.time()}); return self._json({"note_id": e["n"]}, 201)
            if parts[3] == "query":
                q = json.loads(raw)["query"]; e["messages"].append({"message_id": len(e["messages"]) + 1, "role": "user", "content": q, "meta": {}, "created_at": time.time()})
                name = "urgent_unverified" if "chest pain" in q else "records_only" if "Examplometer" in q else "abstain" if "violin" in q else "answered"
                lines = (FIX / f"{name}.ndjson").read_text(encoding="utf-8").splitlines()
                self.send_response(200); self.send_header("Content-Type", "application/x-ndjson; charset=utf-8"); self.send_header("Cache-Control", "no-store"); self.end_headers()
                evs = [json.loads(l) for l in lines]
                for i, l in enumerate(lines):
                    b = (l + "\n").encode("utf-8")
                    mid = len(b) // 2 if i % 3 == 0 else len(b)     # sometimes split a line (and a UTF-8 sequence) across writes
                    self.wfile.write(b[:mid]); self.wfile.flush(); time.sleep(0.03); self.wfile.write(b[mid:]); self.wfile.flush()
                meta = evs[0]; fin = evs[-1]; rec = next((x for x in evs if x["type"] == "records"), {}); ver = next((x for x in evs if x["type"] == "verification"), {})
                note = next((x for x in evs if x["type"] == "notices"), {})
                e["messages"].append({"message_id": len(e["messages"]) + 1, "role": "assistant", "content": fin["text"], "created_at": time.time(), "meta": {
                    "status": fin["status"], "workflow": meta["workflow"], "notices": note.get("items", []), "issues": ver.get("issues", []),
                    "record_cards": rec.get("items", []), "record_views": rec.get("views", []), "urgent_flags": meta["urgent_flags"],
                    "patient_specific": meta["patient_specific"], "sources": [{"ref": s["ref"], "source_id": s["source_id"], "version": s["version"], "chunk_id": s["chunk_id"], "label": s["label"], "score": s["score"], "page": None, "section": s["section"]} for s in meta["sources"]]}})
                return
        self._json({"detail": "not found"}, 404)
    def do_DELETE(self):
        p = urlparse(self.path).path; LOG.append(("DELETE", p, bool(self.headers.get("X-Encounter-Token")))); parts = p.split("/")
        e = self._enc(parts[2]) if len(parts) > 2 else None
        if not e: return
        if len(parts) == 3: ENC.pop(parts[2]); self.send_response(204); self.end_headers(); return
        if parts[3] == "context": e["notes"] = [n for n in e["notes"] if str(n["note_id"]) != parts[4]]; self.send_response(204); self.end_headers(); return
if __name__ == "__main__":
    ThreadingHTTPServer(("127.0.0.1", int(sys.argv[1])), H).serve_forever()
