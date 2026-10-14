import json
import unittest
from unittest.mock import patch

from scripts.mcd_client import McdClient, McdError, _sse_messages


class FakeResponse:
    def __init__(self, body, content_type="application/json", status=200, headers=None):
        self._body = body if isinstance(body, bytes) else body.encode("utf-8")
        self._pos = 0
        self.status = status
        self.headers = {"Content-Type": content_type, **(headers or {})}

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return None

    def read(self, size=-1):
        if size < 0:
            size = len(self._body)
        chunk = self._body[self._pos:self._pos + size]
        self._pos += len(chunk)
        return chunk

    read1 = read


class McdClientTests(unittest.TestCase):
    def client(self):
        client = McdClient(token="test-secret", requests_per_second=100000)
        client._limit_rate = lambda: None
        return client

    @staticmethod
    def rpc_response(request, result):
        return FakeResponse(json.dumps({"jsonrpc": "2.0", "id": request["id"], "result": result}))

    def test_sse_parser_handles_split_utf8_and_multiple_data_lines(self):
        encoded = "event: message\ndata: {\"msg\":\"麦当劳\",\ndata: \"ok\":true}\n\n".encode()
        chinese_start = encoded.index("麦".encode())
        # 将第一个汉字的 UTF-8 序列切在两个字节之间。
        chunks = [encoded[:chinese_start + 1], encoded[chinese_start + 1:chinese_start + 2],
                  encoded[chinese_start + 2:]]
        self.assertEqual(list(_sse_messages(chunks)), ['{"msg":"麦当劳",\n"ok":true}'])

    @patch("scripts.mcd_client.urllib.request.urlopen")
    def test_initialize_and_call_use_matching_jsonrpc_id_and_return_business_object(self, urlopen):
        def respond(request, timeout):
            payload = json.loads(request.data)
            if payload["method"] == "notifications/initialized":
                return FakeResponse("", status=202)
            if payload["method"] == "initialize":
                response = self.rpc_response(payload, {"protocolVersion": "2025-06-18", "capabilities": {}})
                response.headers["Mcp-Session-Id"] = "session-test"
                return response
            if payload["method"] == "tools/call":
                business = {"success": True, "code": 200, "data": [{"name": "测试门店"}]}
                # A stale response precedes the response for this request.
                body = "data: " + json.dumps({"jsonrpc": "2.0", "id": -1, "result": {}}) + "\n\n"
                body += "data: " + json.dumps({"jsonrpc": "2.0", "id": payload["id"],
                                                "result": {"structuredContent": business}}) + "\n\n"
                return FakeResponse(body, "text/event-stream")
            self.fail("出现了未预期的 MCP 方法")

        urlopen.side_effect = respond
        result = self.client().call("query-nearby-stores", {"keyword": "南京"})
        self.assertEqual(result, {"success": True, "code": 200, "data": [{"name": "测试门店"}]})
        first = json.loads(urlopen.call_args_list[0].args[0].data)
        self.assertEqual(first["method"], "initialize")
        self.assertEqual(first["params"]["protocolVersion"], "2025-03-26")
        self.assertEqual(urlopen.call_args_list[1].args[0].headers.get("Mcp-session-id"), "session-test")
        call_headers = urlopen.call_args_list[-1].args[0].headers
        self.assertEqual(call_headers.get("Mcp-protocol-version"), "2025-06-18")

    @patch("scripts.mcd_client.urllib.request.urlopen")
    def test_mcp_is_error_overrides_apparently_successful_business_json(self, urlopen):
        def respond(request, timeout):
            payload = json.loads(request.data)
            if payload["method"] == "notifications/initialized":
                return FakeResponse("", status=202)
            result = ({"protocolVersion": "2025-03-26"} if payload["method"] == "initialize"
                      else {"isError": True, "structuredContent":
                            {"success": True, "code": 200, "data": []}})
            return self.rpc_response(payload, result)
        urlopen.side_effect = respond
        with self.assertRaises(McdError) as caught:
            self.client().call("query-meals", {})
        self.assertEqual(caught.exception.code, "工具调用失败")

    @patch("scripts.mcd_client.urllib.request.urlopen")
    def test_business_failure_raises_mcd_error_without_server_text(self, urlopen):
        def respond(request, timeout):
            payload = json.loads(request.data)
            if payload["method"] == "notifications/initialized":
                return FakeResponse("", status=202)
            result = ({"protocolVersion": "2025-03-26"} if payload["method"] == "initialize"
                      else {"structuredContent": {"success": False, "code": 40101,
                                                   "message": "secret-test-secret"}})
            return self.rpc_response(payload, result)
        urlopen.side_effect = respond
        with self.assertRaises(McdError) as caught:
            self.client().call("query-meals", {})
        self.assertEqual(caught.exception.code, 40101)
        self.assertNotIn("secret", str(caught.exception))

    def test_write_tool_is_rejected_before_network_access(self):
        client = self.client()
        with patch("scripts.mcd_client.urllib.request.urlopen") as urlopen:
            with self.assertRaises(McdError) as caught:
                client.call("create-order", {})
        self.assertEqual(caught.exception.code, "工具不允许")
        urlopen.assert_not_called()

    @patch("scripts.mcd_client.urllib.request.urlopen")
    def test_token_is_never_in_transport_error(self, urlopen):
        import urllib.error
        urlopen.side_effect = urllib.error.URLError("https://test-secret@example.invalid/secret")
        with self.assertRaises(McdError) as caught:
            self.client().initialize()
        self.assertNotIn("test-secret", str(caught.exception))


if __name__ == "__main__":
    unittest.main()
