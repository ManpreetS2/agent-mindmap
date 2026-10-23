# Browser QA harness

This harness exercises the T3 canvas view and the legacy React Flow dashboard against a production build. It writes screenshots and `results.json` to `OUT_DIR` (default `/tmp/e2e-out`).

## Run

From the repository root:

```sh
cd web
npm ci
npm i --no-save playwright-core
npm run build
node e2e/run.mjs
```

Install `playwright-core` after `npm ci`, as it is intentionally not a product dependency. The default Chromium executable is:

```text
~/Library/Caches/ms-playwright/chromium-1248/chrome-mac-arm64/Google Chrome for Testing.app/Contents/MacOS/Google Chrome for Testing
```

Set `CHROME_PATH` to override it. The harness expects the static demo at `http://127.0.0.1:8931/`, replay at `http://127.0.0.1:8933/`, and a legacy static server at `http://127.0.0.1:8932/`. These ports can be overridden with `DEMO_URL`, `REPLAY_URL`, and `LEGACY_URL`; screenshot output can be changed with `OUT_DIR`.

Start the two T3 feeds from the repository root (with its project virtualenv):

```sh
.venv/bin/python -m ingest.live --source t3-demo --port 8931 --static-dir "$PWD/web/dist"
.venv/bin/python -m ingest.live --source t3-demo --port 8933 --static-dir "$PWD/web/dist" --demo-replay --demo-step-sec 5
```

For port 8932, serve `web/dist` as static files and map `/activity.json` to the repository's `fixtures/sample-activity.json` (the legacy loader requests `/activity.json`). A minimal local Python handler can do this mapping without copying or modifying fixture files.

Replay samples are taken every 200 ms for one complete 10-stage, 5-second-per-stage cycle. The report records status transitions, roster delegation-edge transitions, pair spacing, frame displacement, and any large jumps. The new-delegation particle is rendered only into the canvas; the harness documents this limitation and checks the observable edge appearance transition as its proxy.

The harness is diagnostic: failures are reported with repro screenshots and do not change product code.
