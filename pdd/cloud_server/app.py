"""Self-hosted API compatible with the PDD CLI and browser relay contracts."""

from __future__ import annotations

import hmac
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request
from fastapi import Path as PathParameter
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from fastapi.staticfiles import StaticFiles
from starlette.concurrency import run_in_threadpool
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from pdd.cloud_server import store
from pdd.cloud_server.config import ServerSettings, load_settings
from pdd.cloud_server.inference import InferenceRequest, invoke
from pdd.cloud_server.models import (
    CommandReference,
    CommandRequest,
    CommandUpdate,
    CrashCode,
    ExampleSubmission,
    FixCode,
    GenerateBugTest,
    GenerateCode,
    GenerateExample,
    GenerateTest,
    LLMInvoke,
    RegisterSession,
    SessionRequest,
    VerifyCode,
)
from pdd.cloud_server.store import JsonObject, StoreError

logger = logging.getLogger(__name__)
bearer = HTTPBearer(auto_error=False)


class RequestSizeLimit:
    """ASGI middleware that bounds streamed bodies before JSON decoding."""

    def __init__(self, app: ASGIApp, limit: int) -> None:
        self.app = app
        self.limit = limit

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        messages: list[Message] = []
        size = 0
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                return
            size += len(message.get("body", b""))
            if size > self.limit:
                await JSONResponse(
                    {"error": "Request body is too large"}, status_code=413
                )(scope, receive, send)
                return
            messages.append(message)
            if not message.get("more_body", False):
                break
        position = 0

        async def replay() -> Message:
            nonlocal position
            if position < len(messages):
                result = messages[position]
                position += 1
                return result
            return await receive()

        await self.app(scope, replay, send)


def create_app(settings: ServerSettings | None = None) -> FastAPI:
    configuration = settings or load_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        await run_in_threadpool(store.initialize_database, configuration.database)
        yield

    app = FastAPI(title="PDD self-hosted server", version="1.0.0", lifespan=lifespan)
    app.add_middleware(RequestSizeLimit, limit=configuration.max_body_bytes)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(configuration.allowed_origins),
        allow_methods=["GET", "POST"],
        allow_headers=["Authorization", "Content-Type", "Idempotency-Key"],
    )

    def authenticate(
        credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
    ) -> str:
        if credentials:
            for owner, token in configuration.tokens:
                if hmac.compare_digest(
                    credentials.credentials.encode(), token.encode()
                ):
                    return owner
        raise HTTPException(
            status_code=401,
            detail="Invalid bearer token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    @app.exception_handler(HTTPException)
    async def handle_http_error(request: Request, error: HTTPException) -> JSONResponse:
        return JSONResponse(
            {"error": str(error.detail)},
            status_code=error.status_code,
            headers=error.headers,
        )

    @app.exception_handler(StoreError)
    async def handle_store_error(request: Request, error: StoreError) -> JSONResponse:
        return JSONResponse({"error": str(error)}, status_code=error.status_code)

    @app.exception_handler(RequestValidationError)
    async def handle_validation_error(
        request: Request, error: RequestValidationError
    ) -> JSONResponse:
        details = [
            {
                "field": ".".join(str(part) for part in item["loc"]),
                "message": item["msg"],
            }
            for item in error.errors()
        ]
        return JSONResponse(
            {"error": "Invalid request", "details": details}, status_code=422
        )

    @app.get("/health")
    def get_health() -> JsonObject:
        return {"status": "ok"}

    @app.get("/getCreditBalance")
    def get_credit_balance(owner: str = Depends(authenticate)) -> JsonObject:
        return {"billingEnabled": False, "currentBalance": None, "balance": None}

    @app.post("/registerSession")
    def register_session(
        request: RegisterSession,
        owner: str = Depends(authenticate),
        request_key: str | None = Header(
            default=None, alias="Idempotency-Key", min_length=1, max_length=128
        ),
    ) -> JsonObject:
        return store.register_session(
            configuration.database,
            owner,
            request,
            configuration.public_url,
            request_key,
        )

    @app.get("/listSessions")
    def list_sessions(
        owner: str = Depends(authenticate),
    ) -> dict[str, list[JsonObject]]:
        return {
            "sessions": store.list_sessions(
                configuration.database, owner, configuration.session_timeout
            )
        }

    @app.post("/heartbeatSession")
    def heartbeat_session(
        request: SessionRequest, owner: str = Depends(authenticate)
    ) -> JsonObject:
        store.save_heartbeat(configuration.database, owner, request.session_id)
        return {"success": True}

    @app.post("/deregisterSession")
    def deregister_session(
        request: SessionRequest, owner: str = Depends(authenticate)
    ) -> JsonObject:
        store.close_session(configuration.database, owner, request.session_id)
        return {"success": True}

    @app.post("/submitCommand")
    def submit_command(
        request: CommandRequest,
        owner: str = Depends(authenticate),
        request_key: str | None = Header(
            default=None, alias="Idempotency-Key", min_length=1, max_length=128
        ),
    ) -> JsonObject:
        return store.submit_command(
            configuration.database,
            owner,
            request,
            configuration.session_timeout,
            request_key,
        )

    @app.get("/getCommands")
    def get_commands(
        session_id: str = Query(alias="sessionId", min_length=1, max_length=128),
        owner: str = Depends(authenticate),
    ) -> dict[str, list[JsonObject]]:
        return {
            "commands": store.get_commands(configuration.database, owner, session_id)
        }

    @app.get("/getCommandStatus")
    def get_command_status(
        session_id: str = Query(alias="sessionId", min_length=1, max_length=128),
        command_id: str = Query(alias="commandId", min_length=1, max_length=128),
        owner: str = Depends(authenticate),
    ) -> dict[str, JsonObject]:
        return {
            "command": store.get_command(
                configuration.database, owner, session_id, command_id
            )
        }

    @app.post("/updateCommand")
    def update_command(
        request: CommandUpdate, owner: str = Depends(authenticate)
    ) -> JsonObject:
        return {
            "success": True,
            "command": store.update_command(configuration.database, owner, request),
        }

    @app.post("/cancelCommand")
    def cancel_command(
        request: CommandReference, owner: str = Depends(authenticate)
    ) -> JsonObject:
        update = CommandUpdate(
            session_id=request.session_id,
            command_id=request.command_id,
            status="cancelled",
        )
        command = store.update_command(configuration.database, owner, update)
        return {"success": True, "message": "Command cancelled", "command": command}

    @app.post("/submitExample")
    def submit_example(
        request: ExampleSubmission, owner: str = Depends(authenticate)
    ) -> JsonObject:
        return {
            "success": True,
            "exampleId": store.submit_example(configuration.database, owner, request),
        }

    @app.get("/listExamples")
    def list_examples(
        owner: str = Depends(authenticate),
        limit: int = Query(default=20, ge=1, le=100),
        offset: int = Query(default=0, ge=0),
    ) -> dict[str, list[JsonObject]]:
        return {
            "examples": store.list_examples(
                configuration.database, owner, limit, offset
            )
        }

    @app.get("/searchExamples")
    def search_examples(
        query: str = Query(min_length=1, max_length=8192),
        language: str | None = Query(default=None, max_length=128),
        limit: int = Query(default=3, ge=1, le=10),
        owner: str = Depends(authenticate),
    ) -> dict[str, list[JsonObject]]:
        return {
            "examples": store.search_examples(
                configuration.database, owner, query, language, limit
            )
        }

    def run_inference(request: InferenceRequest, owner: str) -> JsonObject:
        examples: list[JsonObject] = []
        if isinstance(request, GenerateCode):
            examples = store.search_examples(
                configuration.database,
                owner,
                request.search_input or request.prompt_content,
                request.language,
                configuration.example_limit,
            )
        elif isinstance(request, LLMInvoke) and request.prompt and not request.messages:
            examples = store.search_examples(
                configuration.database,
                owner,
                request.prompt,
                request.language,
                configuration.example_limit,
            )
        try:
            return invoke(request, examples)
        except Exception:
            logger.exception("Model execution failed for %s", type(request).__name__)
            raise HTTPException(
                status_code=502, detail="Model execution failed; check the server log"
            ) from None

    @app.post("/generateCode")
    def generate_code(
        request: GenerateCode, owner: str = Depends(authenticate)
    ) -> JsonObject:
        return run_inference(request, owner)

    @app.post("/generateExample")
    def generate_example(
        request: GenerateExample, owner: str = Depends(authenticate)
    ) -> JsonObject:
        return run_inference(request, owner)

    @app.post("/generateTest")
    def generate_test(
        request: GenerateTest, owner: str = Depends(authenticate)
    ) -> JsonObject:
        return run_inference(request, owner)

    @app.post("/generateBugTest")
    def generate_bug_test(
        request: GenerateBugTest, owner: str = Depends(authenticate)
    ) -> JsonObject:
        return run_inference(request, owner)

    @app.post("/fixCode")
    def fix_code(request: FixCode, owner: str = Depends(authenticate)) -> JsonObject:
        return run_inference(request, owner)

    @app.post("/crashCode")
    def crash_code(
        request: CrashCode, owner: str = Depends(authenticate)
    ) -> JsonObject:
        return run_inference(request, owner)

    @app.post("/verifyCode")
    def verify_code(
        request: VerifyCode, owner: str = Depends(authenticate)
    ) -> JsonObject:
        return run_inference(request, owner)

    @app.post("/llmInvoke")
    def llm_invoke(
        request: LLMInvoke, owner: str = Depends(authenticate)
    ) -> JsonObject:
        return run_inference(request, owner)

    @app.post("/syncState")
    @app.post("/trackUsage")
    def reject_reserved_contract(owner: str = Depends(authenticate)) -> None:
        raise HTTPException(
            status_code=501,
            detail="Reserved endpoint: the public client defines no request contract",
        )

    frontend = Path(__file__).resolve().parents[1] / "frontend" / "dist"
    if (frontend / "assets").is_dir():
        app.mount("/assets", StaticFiles(directory=frontend / "assets"), name="assets")

    @app.get("/")
    def redirect_dashboard() -> RedirectResponse:
        return RedirectResponse("cloud")

    @app.get("/cloud")
    def serve_dashboard() -> FileResponse:
        index = frontend / "index.html"
        if not index.is_file():
            raise HTTPException(
                status_code=503,
                detail="Build the frontend with bun ci && bun run build in pdd/frontend",
            )
        return FileResponse(index, headers={"Cache-Control": "no-store"})

    @app.get("/connect/{session_id}")
    def serve_session_dashboard(
        session_id: Annotated[str, PathParameter(min_length=1, max_length=128)],
    ) -> FileResponse:
        return serve_dashboard()

    @app.get("/logo.svg")
    def serve_logo() -> FileResponse:
        logo = frontend / "logo.svg"
        if not logo.is_file():
            raise HTTPException(status_code=404, detail="Logo not found")
        return FileResponse(logo)

    return app
