# Generates NDJSON fixtures with the REAL backend event pipeline (api/streaming.py + knowledge/clinical.py).
import sys, json, asyncio, os, tempfile, pathlib, unittest
sys.dont_write_bytecode = True
sys.path.insert(0, sys.argv[1]); out = pathlib.Path(sys.argv[2])
from api.streaming import answer_events, render_ndjson
from knowledge.clinical import ground, plan_clinical
from tests.test_clinical import ClinicalBase
from tests.test_grounded import FICTITROL, ref_for

class T(ClinicalBase):
    def runTest(self): pass
t = T(); t.setUp(); t.load(("fict.md", FICTITROL))

def scenario(name, question, fn):
    cp = plan_clinical(t.store, question)
    plan = ground(question, cp, t.retriever.retrieve(question))
    async def llm(prompt):
        for tok in fn(prompt).split(" "): yield tok + " "
    async def go():
        evs = [{"type": "meta", "workflow": cp.workflow, "model": "llama3.1:latest", "urgent_flags": [f.code for f in cp.red_flags],
                "patient_specific": cp.patient_specific,
                "sources": [{"id": e.chunk_id, "chunk_id": e.chunk_id, "ref": e.ref, "label": e.label(), "text": e.text[:240], "score": e.score,
                             "source_id": e.source_id, "version": e.version, "page_number": e.page or 0, "section": e.section,
                             "full_text_url": f"/chunks/{e.chunk_id}"} for e in plan.used], "encounter": True}]
        evs += [e async for e in answer_events(cp, plan, llm)]
        return evs
    evs = asyncio.run(go())
    (out / f"{name}.ndjson").write_text("".join(render_ndjson(e) for e in evs), encoding="utf-8")
    print(name, [e["type"] for e in evs][:12])
    return plan

q1 = "My patient has chest pain; what is the maximum dose of Fictitrol?"
scenario("urgent_unverified", q1, lambda p: f"The maximum dose is 999 mg per day [{ref_for(p, '100 mg per day')}].")
scenario("answered", "What is the maximum dose of Fictitrol?", lambda p: f"The maximum dose is 100 mg per day [{ref_for(p, '100 mg per day')}].")
scenario("records_only", "Examplometer", lambda p: "unused")
scenario("abstain", "how do I repair a violin", lambda p: "unused")
# chunk fixture for GET /chunks/{id}
cid = next(iter(t.store.get_active_chunks([c["chunk_id"] for c in t.store.list_chunks("fict-md")]).items()))
(out / "chunk.json").write_text(json.dumps({"chunk_id": cid[0], **cid[1]}), encoding="utf-8")
(out / "chunk_id.txt").write_text(cid[0])
print("chunk", cid[0])
