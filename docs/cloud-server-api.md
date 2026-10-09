# Self-hosted HTTP contract

This API implements the public CLI and browser contracts from upstream commit
`b2ceb65774c65c4056f48cd8b108822c20d0f0c9`. Keep these names when changing internals.
Wire fields use camelCase. The [OpenAPI snapshot](cloud-server-openapi.json) defines request types and bounds.

## Transport and authentication

Use JSON over HTTP(S). Every API below requires `Authorization: Bearer <operator-token>`.
`GET /health` is public and returns `{"status":"ok"}`.
The token selects a stable owner. Foreign sessions and commands return 404.
The service has no GitHub/Firebase exchange, refresh endpoint, or credit charge.

Responses use 200 on success. Errors use `{"error":"message"}`.
Validation errors add `details` with field/message entries and return 422.
Other statuses: 401 invalid token, 404 missing/foreign resource, 409 state conflict,
413 oversized body, 502 model failure, and 501 undefined legacy contract.
The request-body limit is 4 MiB. Allowed browser origins are explicit.

## Sessions and commands

| Method/path | Request | Success response |
| --- | --- | --- |
| `POST /registerSession` | `projectPath`, optional `sessionName`, `metadata` | `sessionId`, `cloudUrl` |
| `GET /listSessions` | None | `sessions: Session[]` |
| `POST /heartbeatSession` | `sessionId` | `success: true` |
| `POST /deregisterSession` | `sessionId` | `success: true` |
| `POST /submitCommand` | `sessionId`, `type`, optional `payload` | `commandId`, `status` |
| `GET /getCommands` | Query `sessionId` | `commands: Command[]`, pending only |
| `GET /getCommandStatus` | Query `sessionId`, `commandId` | `command: Command` |
| `POST /updateCommand` | `sessionId`, `commandId`, `status`, optional `response` | `success`, `command` |
| `POST /cancelCommand` | `sessionId`, `commandId` | `success`, `message`, `command` |

Session fields: `sessionId`, `cloudUrl`, `projectName`, `projectPath`, `metadata`,
`createdAt`, `lastHeartbeat`, and `status` (`active` or `stale`). Closed sessions are omitted.
Metadata preserves the client's hostname, platform, platformRelease, and pythonVersion.
Timestamps are UTC-aware ISO strings. Heartbeats older than the configured timeout make sessions stale.
Stale sessions reject submissions until another heartbeat arrives.

Command fields: `commandId`, `type`, `payload`, `status`, `createdAt`, `updatedAt`, and `response`.
The payload's `args` and `options` fields must be JSON objects when present.
Use semantic positional names or the ordered `args.args` list.
Global options precede the CLI subcommand; command options follow it.

```json
{
  "sessionId": "registered-session-id",
  "type": "sync",
  "payload": {"args": {"args": ["--help"]}, "options": {"local": true}}
}
```

The worker polls pending commands, reports processing, and executes through its local project API.
It sends streaming or final response fields such as `success`, `stdout`, `stderr`,
`exit_code`, `message`, `cost`, and `files_created`. The relay preserves that response JSON.
It runs neither the submitted CLI command nor generated code on the service host.

Registration and submission accept `Idempotency-Key`, 1..128 characters.
Retry the same body with the same key to recover its existing identifier.
Changing a body under the same key returns 409. Without a key, each submission creates separate work.
Example uploads deduplicate by content instead.

Command states: pending, processing, completed, failed, cancelled.
Terminal results are immutable; repeated identical updates succeed.
Cancellation remains sticky when a worker reports late output or completion.
Deregistration closes the session and cancels its pending/processing commands.
The worker observes cancellation through status polling and cancels its local job.
There is no automatic replay of processing commands after a worker crash.

## Inference

All inference routes use POST. Shared options: `strength` 0..1 (default .5),
`temperature` 0..2 (default 0), `time` 0..1 (default .25),
`verbose` (default false), and `language` (default python). Null `time` uses .25.
Responses include provider-reported `totalCost` and `modelName`.

| Path | Input fields | Result fields |
| --- | --- | --- |
| `/generateCode` | `promptContent`; optional `searchInput`, `compress`, `model` | `generatedCode`, `examplesUsed` |
| `/generateExample` | `promptContent`, `codeContent` | `generatedExample`, `examplesUsed` |
| `/generateTest` | `promptContent`; `codeContent` or `example`; optional `existingTests`, `coverageReport`, `sourceFilePath`, `testFilePath`, `moduleName`, `mode` | `generatedTest`, `examplesUsed` |
| `/generateBugTest` | `promptContent`, `codeContent`, `programContent`, `currentOutput`, `desiredOutput` | `generatedTest`, `examplesUsed` |
| `/fixCode` | `unitTest`, `code`, `prompt`, `errors`; optional `protectTests`, `codeFileExt` | `fixedUnitTest`, `fixedCode`, `analysis`, `updateUnitTest`, `updateCode`, `success` |
| `/crashCode` | `programContent`, `promptContent`, `codeContent`, `errorContent`; optional `programPath`, `codePath` | `fixedProgram`, `fixedCode`, `updateProgram`, `updateCode`, `analysis` |
| `/verifyCode` | `programContent`, `promptContent`, `codeContent`, `outputContent` | `fixedProgram`, `fixedCode`, `explanation`, `issuesCount` |
| `/llmInvoke` | `prompt` plus optional `inputJson`, or `messages`; optional `outputSchema`, `useBatchMode` | `result`, `thinkingOutput`, `examplesUsed` |

`generateTest.mode` defaults to generate. Increase mode requires `codeContent`,
`existingTests`, and `coverageReport`. `llmInvoke` supports batched inputs and message batches.
`generateCode.model` scopes the exact model to one request, including nested model calls.

Use server provider credentials. Inference never recursively calls the service.
Caller include/shell/web directives remain text; client-side preprocessing supplies workspace context.
File-path fields are model context, not paths the API opens or writes.
Fix analysis logs use a temporary directory. Clients receive errors without provider secrets.

## Example library

| Method/path | Request | Success response |
| --- | --- | --- |
| `POST /submitExample` | `command`, `input`, `output`; optional `searchInput`, `metadata` | `success`, `exampleId` |
| `GET /listExamples` | Query `limit` (1..100), `offset` | `examples` |
| `GET /searchExamples` | Query `query`, optional `language`, `limit` (1..10) | `examples` |

Input/output objects preserve file content, filename, and other JSON from existing clients.
Metadata can include title, description, language, framework, tags, isPublic, and price.
Price metadata is retained as data; the service does not sell examples.
Examples are private unless `metadata.isPublic` is exactly true.
Shared examples are visible to authenticated owners, never unauthenticated readers.

Search uses FTS5 lexical ranking and optional language filtering.
`generateCode` searches `searchInput` or `promptContent`; prompt-mode `llmInvoke` searches its prompt.
Only accessible examples are injected. `examplesUsed` includes real IDs, module IDs, and titles.
Set `PDD_SERVER_EXAMPLE_LIMIT=0` to disable automatic retrieval.

## Reserved and local-browser routes

`GET /getCreditBalance` returns `billingEnabled: false`, `currentBalance: null`, and `balance: null`.
`POST /syncState` and `POST /trackUsage` return authenticated 501 responses.
Their names exist in the public endpoint map, but no public caller defines request or response fields.

The separate project API retains `/api/v1/config/cloud-url` and `/api/v1/auth/*`.
Configuration adds `cloud_enabled`; an unconfigured service URL is empty.
Auth status reports configuration. The compatibility `jwt-token` route returns the configured bearer token only to loopback browsers.
Login reports configuration, polling reports unsupported OAuth, and logout explains operator revocation.
`POST /api/v1/auth/test` checks the configured service's listSessions endpoint.
