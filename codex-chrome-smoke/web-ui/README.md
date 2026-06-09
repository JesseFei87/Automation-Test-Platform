# ICM AI Automation Platform UI

This is the Web UI for the local team edition of the ICM AI automation testing platform.

## Run

Start the backend from the repository root:

```bash
python -m pip install -e .
python -m uvicorn icm_platform.api:app --host 127.0.0.1 --port 8000
```

Start the frontend from this folder:

```bash
npm install
npm run dev
```

Default frontend URL:

```text
http://127.0.0.1:5175
```

## Notes

- `npm run dev` uses `build + preview` for better stability on this Windows/Codex environment.
- `npm run dev:vite` is available for normal Vite hot reload development.
- The UI falls back to local mock data if the backend is not running.
- The backend still keeps YAML, Python runner, reports, and screenshots as independent local assets.
