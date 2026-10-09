# PDD browser UI

Use Bun from `.bun-version` to build the project UI and self-hosted dashboard.
Provider credentials belong to the Python process, outside browser bundles.

```sh
bun ci
bun --bun run build
```

`pdd connect` serves the generated `dist/` directory on port 9876.
`pdd-cloud-server` serves its dashboard at `/cloud` or `/connect/{session_id}`.
Build before packaging the Python wheel so its UI assets are included.

For UI development:

```sh
bun --bun run dev
bun --bun run test
bun --bun run typecheck
```

Set `VITE_API_URL` to change the development proxy's project server.
The project server discovers `PDD_CLOUD_URL` and configured bearer credentials.
There is no implicit hosted service URL. The service dashboard uses its own origin.

`typecheck` applies strict checks to the service UI and shared API.
The legacy whole-project configuration has separate pre-existing type errors.
See [self-hosting](../../docs/self-hosting.md) for startup and operator settings.
