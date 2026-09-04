from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any, Protocol

import httpx

from app.ai.model import (
    BatchCloseContext,
    BatchCloseProviderResponse,
    InvestigationContext,
    ProviderRecommendation,
    ToolRequest,
)
from app.ai.tools import GEMINI_TOOL_DECLARATIONS, GROQ_TOOL_DECLARATIONS
from app.config import Settings, settings


class ProviderError(RuntimeError):
    """Sanitized provider failure safe to persist in an audit trace."""

    def __init__(self, provider: str, model: str, code: str):
        self.provider = provider
        self.model = model
        self.code = code
        super().__init__(f"{provider} provider failure: {code}")


def provider_name(provider: Any) -> str:
    return str(getattr(provider, "name", provider.__class__.__name__.lower()))[:100]


def provider_model(provider: Any) -> str | None:
    value = getattr(provider, "model", None)
    return str(value)[:150] if value is not None else None


class InvestigationProvider(Protocol):
    name: str
    model: str

    async def investigate(
        self, context: InvestigationContext
    ) -> ProviderRecommendation: ...


class BatchCloseProvider(Protocol):
    name: str
    model: str

    async def assess_batch_close(
        self, context: BatchCloseContext
    ) -> BatchCloseProviderResponse: ...


def _recommendation_from_json(
    value: Mapping[str, Any], provider: str, model: str
) -> ProviderRecommendation:
    try:
        return ProviderRecommendation.model_validate(value)
    except Exception as error:
        raise ProviderError(provider, model, "malformed_response") from error


def _json_text(value: str, provider: str, model: str) -> ProviderRecommendation:
    try:
        decoded = json.loads(value)
    except (TypeError, ValueError) as error:
        raise ProviderError(provider, model, "malformed_response") from error
    if not isinstance(decoded, Mapping):
        raise ProviderError(provider, model, "malformed_response")
    return _recommendation_from_json(decoded, provider, model)


def _batch_close_json_text(
    value: str, provider: str, model: str
) -> BatchCloseProviderResponse:
    try:
        decoded = json.loads(value)
    except (TypeError, ValueError) as error:
        raise ProviderError(provider, model, "malformed_response") from error
    if not isinstance(decoded, Mapping):
        raise ProviderError(provider, model, "malformed_response")
    try:
        return BatchCloseProviderResponse.model_validate(decoded)
    except Exception as error:
        raise ProviderError(provider, model, "malformed_response") from error


def _response_json(response: httpx.Response, provider: str, model: str) -> dict[str, Any]:
    if response.status_code == 429:
        raise ProviderError(provider, model, "rate_limited")
    if response.status_code >= 400:
        raise ProviderError(provider, model, f"http_{response.status_code}")
    try:
        payload = response.json()
    except ValueError as error:
        raise ProviderError(provider, model, "malformed_response") from error
    if not isinstance(payload, dict):
        raise ProviderError(provider, model, "malformed_response")
    return payload


class _HttpProvider:
    name = ""

    def __init__(
        self,
        *,
        api_key: str,
        model: str,
        timeout_seconds: float | None = None,
        client: httpx.AsyncClient | None = None,
    ):
        self.api_key = api_key
        self.model = model
        self.timeout_seconds = timeout_seconds or settings.ai_timeout_seconds
        self.client = client

    async def _post(
        self,
        url: str,
        *,
        headers: dict[str, str],
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        try:
            if self.client is not None:
                response = await self.client.post(
                    url, headers=headers, json=payload, timeout=self.timeout_seconds
                )
                return _response_json(response, self.name, self.model)
            async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
                response = await client.post(url, headers=headers, json=payload)
                return _response_json(response, self.name, self.model)
        except ProviderError:
            raise
        except (httpx.TimeoutException, TimeoutError) as error:
            raise ProviderError(self.name, self.model, "timeout") from error
        except httpx.RequestError as error:
            raise ProviderError(self.name, self.model, "request_error") from error


class GeminiProvider(_HttpProvider):
    name = "gemini"

    def __init__(
        self,
        *,
        api_key: str,
        model: str | None = None,
        base_url: str | None = None,
        timeout_seconds: float | None = None,
        client: httpx.AsyncClient | None = None,
    ):
        super().__init__(
            api_key=api_key,
            model=model or settings.gemini_model,
            timeout_seconds=timeout_seconds,
            client=client,
        )
        self.base_url = (base_url or settings.gemini_base_url).rstrip("/")

    async def investigate(self, context: InvestigationContext) -> ProviderRecommendation:
        payload = {
            "contents": _gemini_contents(context),
            "tools": [{"functionDeclarations": GEMINI_TOOL_DECLARATIONS}],
        }
        response = await self._post(
            f"{self.base_url}/models/{self.model}:generateContent",
            headers={"Content-Type": "application/json", "x-goog-api-key": self.api_key},
            payload=payload,
        )
        try:
            parts = response["candidates"][0]["content"]["parts"]
        except (KeyError, IndexError, TypeError) as error:
            raise ProviderError(self.name, self.model, "malformed_response") from error
        for part in parts:
            function_call = part.get("functionCall")
            if isinstance(function_call, Mapping):
                name = function_call.get("name")
                arguments = function_call.get("args", {})
                if not isinstance(name, str) or not isinstance(arguments, Mapping):
                    raise ProviderError(self.name, self.model, "malformed_response")
                return ProviderRecommendation(
                    tool_request=ToolRequest(
                        tool=name,
                        arguments=dict(arguments),
                        call_id=function_call.get("id"),
                    )
                )
        for part in parts:
            text = part.get("text")
            if isinstance(text, str):
                return _json_text(text, self.name, self.model)
        raise ProviderError(self.name, self.model, "malformed_response")

    async def assess_batch_close(
        self, context: BatchCloseContext
    ) -> BatchCloseProviderResponse:
        response = await self._post(
            f"{self.base_url}/models/{self.model}:generateContent",
            headers={"Content-Type": "application/json", "x-goog-api-key": self.api_key},
            payload={"contents": _batch_close_gemini_contents(context)},
        )
        try:
            parts = response["candidates"][0]["content"]["parts"]
        except (KeyError, IndexError, TypeError) as error:
            raise ProviderError(self.name, self.model, "malformed_response") from error
        for part in parts:
            if isinstance(part.get("functionCall"), Mapping):
                raise ProviderError(self.name, self.model, "malformed_response")
            text = part.get("text")
            if isinstance(text, str):
                return _batch_close_json_text(text, self.name, self.model)
        raise ProviderError(self.name, self.model, "malformed_response")


class GroqProvider(_HttpProvider):
    name = "groq"

    def __init__(
        self,
        *,
        api_key: str,
        model: str | None = None,
        base_url: str | None = None,
        timeout_seconds: float | None = None,
        client: httpx.AsyncClient | None = None,
    ):
        super().__init__(
            api_key=api_key,
            model=model or settings.groq_model,
            timeout_seconds=timeout_seconds,
            client=client,
        )
        self.base_url = (base_url or settings.groq_base_url).rstrip("/")

    async def investigate(self, context: InvestigationContext) -> ProviderRecommendation:
        payload = {
            "model": self.model,
            "messages": _groq_messages(context),
            "tools": GROQ_TOOL_DECLARATIONS,
            "tool_choice": "auto",
        }
        response = await self._post(
            f"{self.base_url}/chat/completions",
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.api_key}",
            },
            payload=payload,
        )
        try:
            message = response["choices"][0]["message"]
        except (KeyError, IndexError, TypeError) as error:
            raise ProviderError(self.name, self.model, "malformed_response") from error
        tool_calls = message.get("tool_calls") or []
        if tool_calls:
            call = tool_calls[0]
            try:
                function = call["function"]
                name = function["name"]
                raw_arguments = function.get("arguments", "{}")
                arguments = (
                    json.loads(raw_arguments)
                    if isinstance(raw_arguments, str)
                    else raw_arguments
                )
            except (KeyError, TypeError, ValueError) as error:
                raise ProviderError(self.name, self.model, "malformed_response") from error
            if not isinstance(name, str) or not isinstance(arguments, Mapping):
                raise ProviderError(self.name, self.model, "malformed_response")
            return ProviderRecommendation(
                tool_request=ToolRequest(
                    tool=name,
                    arguments=dict(arguments),
                    call_id=call.get("id"),
                )
            )
        content = message.get("content")
        if not isinstance(content, str):
            raise ProviderError(self.name, self.model, "malformed_response")
        return _json_text(content, self.name, self.model)

    async def assess_batch_close(
        self, context: BatchCloseContext
    ) -> BatchCloseProviderResponse:
        response = await self._post(
            f"{self.base_url}/chat/completions",
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.api_key}",
            },
            payload={
                "model": self.model,
                "messages": _batch_close_groq_messages(context),
            },
        )
        try:
            message = response["choices"][0]["message"]
        except (KeyError, IndexError, TypeError) as error:
            raise ProviderError(self.name, self.model, "malformed_response") from error
        if message.get("tool_calls"):
            raise ProviderError(self.name, self.model, "malformed_response")
        content = message.get("content")
        if not isinstance(content, str):
            raise ProviderError(self.name, self.model, "malformed_response")
        return _batch_close_json_text(content, self.name, self.model)


def configured_providers(app_settings: Settings = settings) -> list[InvestigationProvider]:
    """Return providers in deterministic priority order, omitting unconfigured keys."""
    providers: list[InvestigationProvider] = []
    if app_settings.gemini_api_key:
        providers.append(
            GeminiProvider(
                api_key=app_settings.gemini_api_key,
                model=app_settings.gemini_model,
                base_url=app_settings.gemini_base_url,
                timeout_seconds=app_settings.ai_timeout_seconds,
            )
        )
    if app_settings.groq_api_key:
        providers.append(
            GroqProvider(
                api_key=app_settings.groq_api_key,
                model=app_settings.groq_model,
                base_url=app_settings.groq_base_url,
                timeout_seconds=app_settings.ai_timeout_seconds,
            )
        )
    return providers


def _gemini_contents(context: InvestigationContext) -> list[dict[str, Any]]:
    contents: list[dict[str, Any]] = [
        {"role": "user", "parts": [{"text": context.prompt()}]},
    ]
    for item in context.history:
        role = item.get("role")
        if role in {"model", "assistant"} and isinstance(
            item.get("functionCall"), Mapping
        ):
            contents.append({"role": "model", "parts": [{"functionCall": item["functionCall"]}]})
        elif role == "tool":
            contents.append({
                "role": "user",
                "parts": [{
                    "functionResponse": {
                        "name": item.get("name", "tool"),
                        "response": item.get("content", {}),
                    }
                }],
            })
        elif isinstance(item.get("content"), str):
            contents.append({"role": role or "user", "parts": [{"text": item["content"]}]})
    return contents


def _groq_messages(context: InvestigationContext) -> list[dict[str, Any]]:
    messages: list[dict[str, Any]] = [
        {
            "role": "system",
            "content": (
                "You are a read-only reconciliation investigator. "
                "Deterministic outcomes are authoritative. Never request SQL or mutations."
            ),
        },
        {"role": "user", "content": context.prompt()},
    ]
    for item in context.history:
        role = item.get("role")
        if role in {"model", "assistant"} and isinstance(
            item.get("functionCall"), Mapping
        ):
            function_call = item["functionCall"]
            messages.append(
                {
                    "role": "assistant",
                    "tool_calls": [
                        {
                            "id": item.get("callId", "tool-call"),
                            "type": "function",
                            "function": {
                                "name": function_call.get("name", "tool"),
                                "arguments": json.dumps(function_call.get("args", {})),
                            },
                        }
                    ],
                }
            )
        elif role == "tool":
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": item.get("callId", "tool-call"),
                    "content": json.dumps(item.get("content", {})),
                }
            )
        else:
            messages.append(item)
    return messages


def _batch_close_gemini_contents(context: BatchCloseContext) -> list[dict[str, Any]]:
    return [{"role": "user", "parts": [{"text": context.prompt()}]}]


def _batch_close_groq_messages(context: BatchCloseContext) -> list[dict[str, Any]]:
    return [
        {
            "role": "system",
            "content": (
                "You are a read-only reconciliation close assessor. "
                "Deterministic coverage and money totals are authoritative."
            ),
        },
        {"role": "user", "content": context.prompt()},
    ]
