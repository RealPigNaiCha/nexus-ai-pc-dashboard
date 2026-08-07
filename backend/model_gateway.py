from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from ipaddress import ip_address
from time import perf_counter
from urllib.parse import SplitResult, quote, urlsplit, urlunsplit

import httpx

from .credentials import ApiCredentialStore


OFFICIAL_PROVIDER_HOSTS = {
    "openai": "api.openai.com",
    "anthropic": "api.anthropic.com",
    "google-gemini": "generativelanguage.googleapis.com",
    "deepseek": "api.deepseek.com",
    "alibaba-bailian": "dashscope.aliyuncs.com",
}

MODEL_ROLES = ("reasoning", "fast", "vision", "embedding")


@dataclass(frozen=True)
class ModelProbeResult:
    provider: str
    latency_ms: int


@dataclass(frozen=True)
class ModelGenerationResult:
    provider: str
    model: str
    role: str
    latency_ms: int
    content: str
    prompt_tokens: int | None
    completion_tokens: int | None
    total_tokens: int | None


class ModelGatewayError(RuntimeError):
    def __init__(self, code: str, detail: str, status_code: int, duration_ms: int = 0) -> None:
        super().__init__(detail)
        self.code = code
        self.detail = detail
        self.status_code = status_code
        self.duration_ms = duration_ms


class ModelRequestCancelled(asyncio.CancelledError):
    def __init__(self, duration_ms: int) -> None:
        super().__init__()
        self.duration_ms = duration_ms


class ModelProbeCancelled(ModelRequestCancelled):
    """Backward-compatible alias for connection-test cancellation."""


def _is_loopback(host: str) -> bool:
    if host.casefold() == "localhost":
        return True
    try:
        return ip_address(host).is_loopback
    except ValueError:
        return False


def _validated_endpoint(provider: str, endpoint: str) -> SplitResult:
    parsed = urlsplit(endpoint)
    host = parsed.hostname or ""
    if (
        not host
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
    ):
        raise ModelGatewayError("invalid_endpoint", "Model endpoint is not allowed", 422)

    official_host = OFFICIAL_PROVIDER_HOSTS.get(provider)
    if official_host:
        if parsed.scheme != "https" or host.casefold() != official_host or parsed.port not in {None, 443}:
            raise ModelGatewayError("invalid_endpoint", "Model endpoint does not match the provider", 422)
    elif provider == "openai-compatible":
        if parsed.scheme != "https" and not (parsed.scheme == "http" and _is_loopback(host)):
            raise ModelGatewayError("insecure_endpoint", "Compatible model endpoints must use HTTPS", 422)
    else:
        raise ModelGatewayError("unsupported_provider", "Unsupported model provider", 422)
    return parsed


def build_probe_url(provider: str, endpoint: str) -> str:
    parsed = _validated_endpoint(provider, endpoint)
    path = parsed.path.rstrip("/")
    if not path.endswith("/models"):
        path = f"{path}/models"
    safe_url = SplitResult(parsed.scheme, parsed.netloc, path, "", "")
    return urlunsplit(safe_url)


def build_chat_url(provider: str, endpoint: str, model: str | None = None) -> str:
    parsed = _validated_endpoint(provider, endpoint)
    base_path = parsed.path.rstrip("/")
    if provider == "anthropic":
        path = f"{base_path}/messages"
    elif provider == "google-gemini":
        if not model:
            raise ModelGatewayError("role_not_configured", "Model role is not configured", 409)
        path = f"{base_path}/models/{quote(model, safe='')}:generateContent"
    else:
        path = f"{base_path}/chat/completions"
    return urlunsplit(SplitResult(parsed.scheme, parsed.netloc, path, "", ""))


def _generation_body(
    *,
    provider: str,
    model: str,
    prompt: str,
    system: str | None,
    max_tokens: int,
    temperature: float,
) -> dict[str, object]:
    if provider == "anthropic":
        anthropic_temperature = max(0.0, min(1.0, temperature))
        body: dict[str, object] = {
            "model": model,
            "max_tokens": max_tokens,
            "temperature": anthropic_temperature,
            "messages": [{"role": "user", "content": prompt}],
        }
        if system:
            body["system"] = system
        return body
    if provider == "google-gemini":
        body = {
            "contents": [{"role": "user", "parts": [{"text": prompt}]}],
            "generationConfig": {
                "maxOutputTokens": max_tokens,
                "temperature": temperature,
            },
        }
        if system:
            body["systemInstruction"] = {"parts": [{"text": system}]}
        return body
    messages: list[dict[str, str]] = [{"role": "user", "content": prompt}]
    if system:
        messages.insert(0, {"role": "system", "content": system})
    return {
        "model": model,
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": temperature,
        "stream": False,
    }


def _parse_generation_response(provider: str, payload: dict[str, object]) -> tuple[str, dict[str, int | None]]:
    if provider == "anthropic":
        blocks = payload.get("content") or []
        text = "".join(
            block.get("text", "")
            for block in blocks
            if isinstance(block, dict) and block.get("type") == "text" and block.get("text")
        )
        usage = payload.get("usage") or {}
        prompt_tokens = usage.get("input_tokens")
        completion_tokens = usage.get("output_tokens")
        total_tokens = None
        if prompt_tokens is not None and completion_tokens is not None:
            total_tokens = int(prompt_tokens) + int(completion_tokens)
        return text, {
            "prompt_tokens": int(prompt_tokens) if prompt_tokens is not None else None,
            "completion_tokens": int(completion_tokens) if completion_tokens is not None else None,
            "total_tokens": total_tokens,
        }
    if provider == "google-gemini":
        candidates = payload.get("candidates") or []
        parts: list[str] = []
        if candidates and isinstance(candidates[0], dict):
            content = candidates[0].get("content") or {}
            for part in content.get("parts") or []:
                if isinstance(part, dict) and part.get("text"):
                    parts.append(str(part["text"]))
        usage = payload.get("usageMetadata") or {}
        return "".join(parts), {
            "prompt_tokens": usage.get("promptTokenCount"),
            "completion_tokens": usage.get("candidatesTokenCount"),
            "total_tokens": usage.get("totalTokenCount"),
        }
    choices = payload.get("choices") or []
    content: object = ""
    if choices and isinstance(choices[0], dict):
        message = choices[0].get("message") or {}
        content = message.get("content") or ""
    if isinstance(content, str):
        generated_text = content
    elif isinstance(content, list):
        generated_text = "".join(
            str(part.get("text", ""))
            for part in content
            if isinstance(part, dict) and part.get("text")
        )
    else:
        generated_text = ""
    usage = payload.get("usage") or {}
    return generated_text, {
        "prompt_tokens": usage.get("prompt_tokens"),
        "completion_tokens": usage.get("completion_tokens"),
        "total_tokens": usage.get("total_tokens"),
    }


class ModelGateway:
    def __init__(
        self,
        credential_store: ApiCredentialStore,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
        timeout_seconds: float = 10.0,
    ) -> None:
        self._credential_store = credential_store
        self._client = httpx.AsyncClient(
            transport=transport,
            timeout=httpx.Timeout(timeout_seconds, connect=min(timeout_seconds, 5.0)),
            follow_redirects=False,
        )

    async def close(self) -> None:
        await self._client.aclose()

    async def probe(self, provider: str, endpoint: str) -> ModelProbeResult:
        probe_url = build_probe_url(provider, endpoint)
        secret = self._credential_store.get(provider)
        if secret is None:
            raise ModelGatewayError("credential_missing", "Model credential is not configured", 409)

        headers = self._headers(provider, secret)
        started = perf_counter()

        def elapsed_ms() -> int:
            return max(0, round((perf_counter() - started) * 1000))

        try:
            request = self._client.build_request("GET", probe_url, headers=headers)
            response = await self._client.send(request, stream=True)
            try:
                response_status = response.status_code
            finally:
                await response.aclose()
        except asyncio.CancelledError:
            raise ModelProbeCancelled(elapsed_ms()) from None
        except httpx.TimeoutException:
            raise ModelGatewayError(
                "timeout", "Model service timed out", 504, elapsed_ms()
            ) from None
        except httpx.RequestError:
            raise ModelGatewayError(
                "network_error", "Model service is unavailable", 502, elapsed_ms()
            ) from None
        finally:
            headers.clear()
            secret = ""

        duration_ms = elapsed_ms()
        if response_status in {401, 403}:
            raise ModelGatewayError(
                "authentication_failed", "Model service rejected the credential", 401, duration_ms
            )
        if response_status == 429:
            raise ModelGatewayError(
                "rate_limited", "Model service quota or rate limit was reached", 429, duration_ms
            )
        if response_status >= 400:
            raise ModelGatewayError(
                "upstream_error", "Model service rejected the connection test", 502, duration_ms
            )
        return ModelProbeResult(provider=provider, latency_ms=duration_ms)

    async def generate(
        self,
        *,
        provider: str,
        endpoint: str,
        model: str,
        prompt: str,
        system: str | None = None,
        max_tokens: int = 1024,
        temperature: float = 0.2,
        role: str = "reasoning",
    ) -> ModelGenerationResult:
        model = model.strip()
        if not model:
            raise ModelGatewayError("role_not_configured", "Model role is not configured", 409)
        chat_url = build_chat_url(provider, endpoint, model)
        secret = self._credential_store.get(provider)
        if secret is None:
            raise ModelGatewayError("credential_missing", "Model credential is not configured", 409)

        headers = self._headers(provider, secret)
        body = _generation_body(
            provider=provider,
            model=model,
            prompt=prompt,
            system=system,
            max_tokens=max_tokens,
            temperature=temperature,
        )
        started = perf_counter()

        def elapsed_ms() -> int:
            return max(0, round((perf_counter() - started) * 1000))

        try:
            request = self._client.build_request("POST", chat_url, headers=headers, json=body)
            response = await self._client.send(request, stream=True)
            try:
                response_status = response.status_code
                response_body = await response.aread()
            finally:
                await response.aclose()
        except asyncio.CancelledError:
            raise ModelRequestCancelled(elapsed_ms()) from None
        except httpx.TimeoutException:
            raise ModelGatewayError(
                "timeout", "Model service timed out", 504, elapsed_ms()
            ) from None
        except httpx.RequestError:
            raise ModelGatewayError(
                "network_error", "Model service is unavailable", 502, elapsed_ms()
            ) from None
        finally:
            headers.clear()
            secret = ""

        duration_ms = elapsed_ms()
        if response_status in {401, 403}:
            raise ModelGatewayError(
                "authentication_failed", "Model service rejected the credential", 401, duration_ms
            )
        if response_status == 429:
            raise ModelGatewayError(
                "rate_limited", "Model service quota or rate limit was reached", 429, duration_ms
            )
        if response_status >= 400:
            raise ModelGatewayError(
                "upstream_error", "Model service rejected the generation request", 502, duration_ms
            )

        try:
            payload = json.loads(response_body.decode("utf-8", errors="replace"))
        except ValueError:
            raise ModelGatewayError(
                "upstream_error", "Model service returned an invalid response", 502, duration_ms
            ) from None
        if not isinstance(payload, dict):
            raise ModelGatewayError(
                "upstream_error", "Model service returned an invalid response", 502, duration_ms
            )
        content, usage = _parse_generation_response(provider, payload)
        if not content:
            raise ModelGatewayError(
                "upstream_error", "Model service returned an empty response", 502, duration_ms
            )
        return ModelGenerationResult(
            provider=provider,
            model=model,
            role=role,
            latency_ms=duration_ms,
            content=content,
            prompt_tokens=usage["prompt_tokens"],
            completion_tokens=usage["completion_tokens"],
            total_tokens=usage["total_tokens"],
        )

    @staticmethod
    def _headers(provider: str, secret: str) -> dict[str, str]:
        headers = {
            "Accept": "application/json",
            "User-Agent": "Nexus-AI-PC/0.1",
        }
        if provider == "anthropic":
            headers.update({"x-api-key": secret, "anthropic-version": "2023-06-01"})
        elif provider == "google-gemini":
            headers["x-goog-api-key"] = secret
        else:
            headers["Authorization"] = f"Bearer {secret}"
        return headers
