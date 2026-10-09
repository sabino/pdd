"""Validated request contracts shared by the relay and inference routes."""

from __future__ import annotations

from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, JsonValue, model_validator
from pydantic.alias_generators import to_camel


class RequestModel(BaseModel):
    model_config = ConfigDict(
        alias_generator=to_camel, populate_by_name=True, extra="forbid"
    )


class RegisterSession(RequestModel):
    project_path: str = Field(min_length=1, max_length=4096)
    metadata: dict[str, JsonValue] = Field(default_factory=dict)
    session_name: str | None = Field(default=None, max_length=256)


class SessionRequest(RequestModel):
    session_id: str = Field(min_length=1, max_length=128)


class CommandRequest(SessionRequest):
    type: str = Field(min_length=1, max_length=128)
    payload: dict[str, JsonValue] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_arguments(self) -> Self:
        for field_name in ("args", "options"):
            if field_name in self.payload and not isinstance(
                self.payload[field_name], dict
            ):
                raise ValueError(f"payload.{field_name} must be a JSON object")
        return self


class CommandReference(SessionRequest):
    command_id: str = Field(min_length=1, max_length=128)


class CommandUpdate(CommandReference):
    status: Literal["processing", "completed", "failed", "cancelled"]
    response: dict[str, JsonValue] | None = None


class ExampleSubmission(RequestModel):
    command: str = Field(min_length=1, max_length=128)
    search_input: str = Field(default="", max_length=1_000_000)
    input: dict[str, JsonValue]
    output: dict[str, JsonValue]
    metadata: dict[str, JsonValue] = Field(default_factory=dict)


class InferenceOptions(RequestModel):
    strength: float = Field(default=0.5, ge=0, le=1, allow_inf_nan=False)
    temperature: float = Field(default=0, ge=0, le=2, allow_inf_nan=False)
    time: float | None = Field(default=0.25, ge=0, le=1, allow_inf_nan=False)
    verbose: bool = False
    language: str = Field(default="python", min_length=1, max_length=128)


class GenerateCode(InferenceOptions):
    prompt_content: str = Field(min_length=1)
    search_input: str = ""
    compress: bool = False
    model: str | None = None


class GenerateExample(InferenceOptions):
    prompt_content: str = Field(min_length=1)
    code_content: str = Field(min_length=1)


class GenerateTest(InferenceOptions):
    prompt_content: str = Field(min_length=1)
    code_content: str | None = None
    example: str | None = None
    existing_tests: str | None = None
    coverage_report: str = ""
    source_file_path: str | None = None
    test_file_path: str | None = None
    module_name: str | None = None
    mode: Literal["generate", "increase"] = "generate"

    @model_validator(mode="after")
    def validate_sources(self) -> Self:
        if self.mode == "generate" and bool(self.code_content) == bool(self.example):
            raise ValueError("Exactly one of codeContent or example is required")
        if self.mode == "increase" and not all(
            (self.code_content, self.existing_tests, self.coverage_report)
        ):
            raise ValueError(
                "Increase mode requires codeContent, existingTests, and coverageReport"
            )
        return self


class GenerateBugTest(InferenceOptions):
    prompt_content: str = Field(min_length=1)
    code_content: str = Field(min_length=1)
    program_content: str = Field(min_length=1)
    current_output: str = Field(min_length=1)
    desired_output: str = Field(min_length=1)


class FixCode(InferenceOptions):
    unit_test: str = Field(min_length=1)
    code: str = Field(min_length=1)
    prompt: str = Field(min_length=1)
    errors: str = Field(min_length=1)
    protect_tests: bool = False
    code_file_ext: str | None = None


class CrashCode(InferenceOptions):
    program_content: str = Field(min_length=1)
    prompt_content: str = Field(min_length=1)
    code_content: str = Field(min_length=1)
    error_content: str = Field(min_length=1)
    program_path: str = ""
    code_path: str = ""


class VerifyCode(InferenceOptions):
    program_content: str = Field(min_length=1)
    prompt_content: str = Field(min_length=1)
    code_content: str = Field(min_length=1)
    output_content: str = Field(min_length=1)


class LLMInvoke(InferenceOptions):
    prompt: str | None = None
    input_json: dict[str, JsonValue] | list[dict[str, JsonValue]] | None = None
    messages: list[dict[str, JsonValue]] | list[list[dict[str, JsonValue]]] | None = (
        None
    )
    output_schema: dict[str, JsonValue] | None = None
    use_batch_mode: bool = False

    @model_validator(mode="after")
    def validate_prompt(self) -> Self:
        if not self.prompt and not self.messages:
            raise ValueError("A prompt or messages is required")
        return self
