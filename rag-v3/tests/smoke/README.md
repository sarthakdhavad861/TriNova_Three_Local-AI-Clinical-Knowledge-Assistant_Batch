# Browser smoke test (sandbox substitute, NOT the real build)

These files exist because the Phase 6 UI was developed in an environment where `npm install` was blocked, so the real
Vite build could not run. They bundle `src/main.jsx` with **esbuild** against tiny **stubs** of the third-party
packages (`react-markdown`, `react-virtuoso`, `react-syntax-highlighter`, …), serve it from a **mock backend** that
replays NDJSON produced by the real backend pipeline, and drive it with Playwright/Chromium.

What it proves: the React components, context and API layer work together in a real browser — urgent banner and
record cards render before the answer, failed evidence checks and abstentions are labelled, sources expand to full
text, token/ID handling in `sessionStorage`, history restored from the backend after reload, a wrong token yields
"encounter gone", upload requires licence + origin, erase removes the encounter.

What it does **not** prove: the real Vite build, real markdown rendering/sanitising, Tailwind styling/layout
(the page is unstyled), the real FastAPI server (CORS, headers, streaming), a real LLM. Run the real app per
`docs/SETUP.md` for those.

```bash
# from rag-v3/ — needs esbuild + playwright resolvable (set the *_ENTRY / NODE_MODULES_DIR env vars if not)
python tests/smoke/gen_fixtures.py ../backend tests/smoke/fixtures     # optional: regenerate fixtures (TMPDIR must be writable)
node tests/smoke/build.mjs . /tmp/smoke-dist                             # → /tmp/smoke-dist/bundle.js + index.html
cp -r /tmp/smoke-dist tests/smoke/dist
python tests/smoke/mock_backend.py 8765 &                                # serves dist/ + mock API on one origin
node tests/smoke/smoke.mjs http://127.0.0.1:8765  /tmp/smoke.png         # 20 checks
node tests/smoke/smoke2.mjs http://127.0.0.1:8765                        # wrong token / network failure
```
`dist/` is generated and is git-ignored. The mock backend is **not** the real API: its `meta` events mirror the real
route format but can drift — `backend/tests/test_streaming.py` and the route probe are the contract tests.
