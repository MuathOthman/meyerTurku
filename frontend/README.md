# Keel frontend

React app for Keel. It holds no compliance logic and no data of its own: every screen reads from
the FastAPI backend in `../backend`. See the [root README](../README.md) to run both together.

```bash
npm install
npm run dev        # http://localhost:5173, proxies /api to 127.0.0.1:8000
npm test
npm run build      # dist/, which the backend serves on its own port
```

| Where | What |
|---|---|
| `src/lib/api.ts` | Every call to the backend, and the response types |
| `src/routes/` | Pages. File names set the URLs. `src/routeTree.gen.ts` is generated |
| `src/components/` | Deck plan, finding detail, sidebar |
| `src/styles.css` | All styling |
