"""麦当劳 MCP 只读客户端（仅使用 Python 标准库）。"""
from __future__ import annotations

import json
import os
import threading
import time
import urllib.error
import urllib.request
import codecs
from typing import Any, Iterable


ENDPOINT = "https://mcp.mcd.cn"
PROTOCOL_VERSION = "2025-03-26"
READ_TOOLS = frozenset({"query-nearby-stores", "query-meals", "query-meal-detail"})
RETRY_STATUSES = frozenset({429, 502, 503, 504})


class McdError(Exception):
    """安全、适合直接展示的客户端错误。"""

    def __init__(self, code: int | str, message: str):
        self.code = code
        self.message = message
        super().__init__(message)


def _sse_messages(chunks: Iterable[bytes | str]) -> Iterable[str]:
    """从任意边界的 SSE 分块中产出完整 data 字段。"""
    buffer = ""
    data: list[str] = []
    decoder = codecs.getincrementaldecoder("utf-8")("replace")
    for chunk in chunks:
        buffer += decoder.decode(chunk, final=False) if isinstance(chunk, bytes) else chunk
        while "\n" in buffer:
            line, buffer = buffer.split("\n", 1)
            line = line.rstrip("\r")
            if line == "":
                if data:
                    yield "\n".join(data)
                    data.clear()
            elif not line.startswith(":"):
                field, sep, value = line.partition(":")
                if field == "data":
                    data.append(value[1:] if sep and value.startswith(" ") else value)
    buffer += decoder.decode(b"", final=True)
    if buffer:
        line = buffer.rstrip("\r")
        if line.startswith("data:"):
            value = line[5:]
            data.append(value[1:] if value.startswith(" ") else value)
    if data:
        yield "\n".join(data)


class McdClient:
    """面向麦当劳官方 MCP 的并发安全只读客户端。"""

    def __init__(self, token: str | None = None, timeout: float = 20,
                 requests_per_second: float = 4):
        self._token = token if token is not None else os.environ.get("MCD_MCP_TOKEN", "")
        if not self._token:
            raise McdError("缺少令牌", "请先设置环境变量 MCD_MCP_TOKEN。")
        if timeout <= 0 or requests_per_second <= 0:
            raise ValueError("timeout 和 requests_per_second 必须大于 0。")
        self.timeout = timeout
        self._interval = 1.0 / requests_per_second
        self._rate_lock = threading.Lock()
        self._last_request = 0.0
        self._init_lock = threading.Lock()
        self._initialized = False
        self._request_id = 0
        self._id_lock = threading.Lock()
        self._session_id: str | None = None
        self.server_protocol_version: str | None = None
        self.response_protocol_version: str | None = None

    def __enter__(self) -> "McdClient":
        self.initialize()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        return None

    def _next_id(self) -> int:
        with self._id_lock:
            self._request_id += 1
            return self._request_id

    def _limit_rate(self) -> None:
        with self._rate_lock:
            now = time.monotonic()
            delay = self._interval - (now - self._last_request)
            if delay > 0:
                time.sleep(delay)
            self._last_request = time.monotonic()

    def _headers(self) -> dict[str, str]:
        headers = {
            "Authorization": "Bearer " + self._token,
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
            "MCP-Protocol-Version": self.server_protocol_version or PROTOCOL_VERSION,
        }
        if self._session_id:
            headers["Mcp-Session-Id"] = self._session_id
        return headers

    def _post(self, payload: dict[str, Any], expected_id: int | None = None) -> dict[str, Any] | None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        for attempt in range(3):
            self._limit_rate()
            request = urllib.request.Request(ENDPOINT, data=body, headers=self._headers(), method="POST")
            try:
                with urllib.request.urlopen(request, timeout=self.timeout) as response:
                    session = response.headers.get("Mcp-Session-Id")
                    if session:
                        self._session_id = session
                    version = response.headers.get("MCP-Protocol-Version")
                    if version:
                        self.response_protocol_version = version
                    content_type = response.headers.get("Content-Type", "").lower()
                    if response.status == 202:
                        return None
                    if "text/event-stream" in content_type:
                        # _read_sse 已按本次 JSON-RPC id 选中 response。
                        return self._read_sse(response, expected_id)
                    else:
                        try:
                            result = json.loads(response.read().decode("utf-8"))
                        except (UnicodeDecodeError, json.JSONDecodeError):
                            raise McdError("响应格式错误", "MCP 服务返回了无法解析的 JSON。") from None
                    return self._matching_response(result, expected_id)
            except urllib.error.HTTPError as exc:
                status = exc.code
                retry_after = exc.headers.get("Retry-After", "") if exc.headers else ""
                if status in RETRY_STATUSES and attempt < 2:
                    try:
                        delay = min(2.0, max(0.0, float(retry_after)))
                    except ValueError:
                        delay = 0.25 * (2 ** attempt)
                    time.sleep(delay)
                    continue
                messages = {401: "令牌无效或已过期。", 403: "当前令牌无权访问麦当劳 MCP 服务。",
                            404: "麦当劳 MCP 接口不存在。", 429: "请求过于频繁，请稍后重试。"}
                raise McdError(status, messages.get(status, f"麦当劳 MCP 服务返回 HTTP {status}。")) from None
            except (urllib.error.URLError, TimeoutError, OSError):
                if attempt < 2:
                    # 网络异常不重试，避免未知执行状态下重复触发业务请求。
                    raise McdError("网络错误", "连接麦当劳 MCP 服务失败或请求超时。") from None
                raise McdError("网络错误", "连接麦当劳 MCP 服务失败或请求超时。") from None
        raise McdError("服务繁忙", "麦当劳 MCP 服务暂时繁忙，请稍后重试。")

    def _read_sse(self, response: Any, expected_id: int | None) -> Any:
        def chunks():
            reader = getattr(response, "read1", response.read)
            while True:
                chunk = reader(4096)
                if not chunk:
                    break
                yield chunk
        for data in _sse_messages(chunks()):
            try:
                message = json.loads(data)
            except json.JSONDecodeError:
                continue
            match = self._matching_response(message, expected_id, allow_unmatched=True)
            if match is not _NO_MATCH:
                return match
        raise McdError("响应不完整", "MCP 服务的事件流未包含本次请求的响应。")

    def _matching_response(self, message: Any, expected_id: int | None,
                           allow_unmatched: bool = False) -> Any:
        if isinstance(message, list):
            for item in message:
                found = self._matching_response(item, expected_id, allow_unmatched=True)
                if found is not _NO_MATCH:
                    return found
            if allow_unmatched:
                return _NO_MATCH
            raise McdError("响应不完整", "MCP 服务未返回本次请求的响应。")
        if not isinstance(message, dict):
            raise McdError("响应格式错误", "MCP 服务返回了无效的 JSON-RPC 响应。")
        if expected_id is not None and message.get("id") != expected_id:
            return _NO_MATCH if allow_unmatched else self._raise_missing_response()
        if "error" in message:
            error = message.get("error") or {}
            code = error.get("code", "JSON-RPC 错误") if isinstance(error, dict) else "JSON-RPC 错误"
            raise McdError(code, "MCP 服务处理请求失败。")
        if "result" not in message:
            return _NO_MATCH if allow_unmatched else self._raise_missing_response()
        return message["result"]

    @staticmethod
    def _raise_missing_response():
        raise McdError("响应不完整", "MCP 服务未返回本次请求的响应。")

    def initialize(self) -> dict[str, Any]:
        with self._init_lock:
            if self._initialized:
                return {"initialized": True, "protocolVersion": self.server_protocol_version}
            request_id = self._next_id()
            payload = {"jsonrpc": "2.0", "id": request_id, "method": "initialize",
                       "params": {"protocolVersion": PROTOCOL_VERSION, "capabilities": {},
                                  "clientInfo": {"name": "maimai-toy-finder", "version": "0.1.0"}}}
            result = self._post(payload, request_id)
            if not isinstance(result, dict):
                raise McdError("初始化失败", "MCP 服务初始化响应格式错误。")
            self.server_protocol_version = result.get("protocolVersion")
            self._post({"jsonrpc": "2.0", "method": "notifications/initialized"})
            self._initialized = True
            return result

    def list_tools(self) -> list[dict[str, Any]]:
        self._ensure_initialized()
        result = self._rpc("tools/list", {})
        tools = result.get("tools") if isinstance(result, dict) else None
        if not isinstance(tools, list):
            raise McdError("响应格式错误", "工具列表响应格式错误。")
        return tools

    def call(self, tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        if tool_name not in READ_TOOLS:
            raise McdError("工具不允许", "此客户端仅允许查询门店、餐品和餐品详情。")
        if not isinstance(arguments, dict):
            raise McdError("参数错误", "工具参数必须是 JSON 对象。")
        self._ensure_initialized()
        result = self._rpc("tools/call", {"name": tool_name, "arguments": arguments})
        if not isinstance(result, dict):
            raise McdError("响应格式错误", "工具响应格式错误。")
        if result.get("isError") is True:
            raise McdError("工具调用失败", "麦当劳查询未成功，请检查参数或稍后重试。")
        business = result.get("structuredContent")
        if not isinstance(business, dict):
            business = self._content_json(result.get("content"))
        if not isinstance(business, dict):
            raise McdError("响应格式错误", "工具未返回可识别的业务 JSON。")
        if business.get("success") is False or ("code" in business and business.get("code") != 200):
            code = business.get("code", "业务错误")
            raise McdError(code, "麦当劳查询未成功，请检查参数或稍后重试。")
        return business

    @staticmethod
    def _content_json(content: Any) -> dict[str, Any] | None:
        if not isinstance(content, list):
            return None
        for item in content:
            if isinstance(item, dict) and isinstance(item.get("text"), str):
                try:
                    parsed = json.loads(item["text"])
                except json.JSONDecodeError:
                    continue
                if isinstance(parsed, dict):
                    return parsed
        return None

    def _rpc(self, method: str, params: dict[str, Any]) -> Any:
        request_id = self._next_id()
        response = self._post({"jsonrpc": "2.0", "id": request_id, "method": method,
                               "params": params}, request_id)
        if response is None:
            raise McdError("响应不完整", "MCP 服务未返回本次请求的响应。")
        return response

    def _ensure_initialized(self) -> None:
        if not self._initialized:
            self.initialize()


_NO_MATCH = object()
