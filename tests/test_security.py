"""Security boundaries exercised without real cookies, Keychain or network."""

import asyncio
import json
import sys
import uuid
from datetime import datetime, timedelta, timezone

import pytest
import requests

from mfp_mcp import security, server

COOKIES = {"__Secure-next-auth.session-token": "test-secret"}


@pytest.mark.parametrize("url", [
    "http://www.myfitnesspal.com/", "https://evil.example/",
    "https://www.myfitnesspal.com.evil.example/", "https://myfitnesspal.com/",
    "https://127.0.0.1/", "https://www.myfitnesspal.com:444/",
    "https://user:secret@www.myfitnesspal.com/", "file:///tmp/session",
])
def test_blocks_unapproved_destinations_before_transport(monkeypatch, url):
    def unexpected(*args, **kwargs):
        pytest.fail("Blocked URL reached the HTTP adapter")
    monkeypatch.setattr(requests.adapters.HTTPAdapter, "send", unexpected)
    with pytest.raises(security.SecurityError):
        security.RestrictedSession().get(url)


def test_redirect_cannot_escape_allowlist(monkeypatch):
    calls = []

    def adapter_send(self, request, **kwargs):
        calls.append(request.url)
        response = requests.Response()
        response.status_code = 302
        response.headers["Location"] = "https://evil.example/steal"
        response._content = b""
        response.url = request.url
        response.request = request
        return response

    monkeypatch.setattr(requests.adapters.HTTPAdapter, "send", adapter_send)
    with pytest.raises(security.SecurityError):
        security.RestrictedSession().get("https://www.myfitnesspal.com/")
    assert calls == ["https://www.myfitnesspal.com/"]


def test_transport_ignores_environment_and_keeps_cookies_off_api(monkeypatch):
    monkeypatch.setenv("HTTPS_PROXY", "http://evil.example:8080")
    monkeypatch.setenv("REQUESTS_CA_BUNDLE", "/untrusted/ca")
    calls = []

    def adapter_send(self, request, **kwargs):
        calls.append((request, kwargs))
        response = requests.Response()
        response.status_code = 200
        response._content = b"{}"
        response.url = request.url
        response.request = request
        return response

    monkeypatch.setattr(requests.adapters.HTTPAdapter, "send", adapter_send)
    session = security.RestrictedSession()
    session.cookies.update(security.dict_to_cookiejar(COOKIES))
    session.get("https://www.myfitnesspal.com/", timeout=None)
    session.get("https://api.myfitnesspal.com/v2/foods",
                headers={"Cookie": "test-secret", "Authorization": "Bearer test-token"})
    assert "test-secret" in calls[0][0].headers["Cookie"]
    assert "Cookie" not in calls[1][0].headers
    assert calls[1][0].headers["Authorization"] == "Bearer test-token"
    assert all(kw["verify"] is True and not kw["proxies"] and kw["timeout"] == 30
               for _, kw in calls)


@pytest.mark.parametrize("options", [{"verify": False}, {"verify": "/custom/ca"},
                                      {"proxies": {"https": "http://proxy"}}])
def test_no_tls_bypass_or_explicit_proxy(options):
    with pytest.raises(security.SecurityError):
        security.RestrictedSession().get("https://www.myfitnesspal.com/", **options)


@pytest.mark.parametrize("cookies", [None, {}, {"google_session": "secret"},
                                        {"_mfp_session": "value\r\nInjected: true"}])
def test_only_session_cookies_are_accepted(cookies):
    with pytest.raises(security.SecurityError):
        security.validate_cookies(cookies)


def test_keychain_round_trip_and_expiry(monkeypatch, tmp_path):
    class FakeKeychain:
        raw = None

        def get_password(self, service, account):
            assert (service, account) == (security.SERVICE, security.ACCOUNT)
            return self.raw

        def set_password(self, service, account, value):
            self.raw = value

    backend = FakeKeychain()
    monkeypatch.setattr(security, "_keychain", lambda: backend)
    monkeypatch.chdir(tmp_path)
    security.save_cookies(COOKIES)
    assert security.load_cookies() == COOKIES
    assert not list(tmp_path.iterdir())
    old = datetime.now(timezone.utc) - timedelta(days=31)
    backend.raw = json.dumps({"cookies": COOKIES, "saved_at": old.isoformat()})
    with pytest.raises(security.SecurityError, match="too old"):
        security.load_cookies()


def test_keychain_denial_does_not_fall_back(monkeypatch):
    def denied():
        raise RuntimeError("sensitive backend diagnostic")
    monkeypatch.setattr(security, "_keychain", denied)
    with pytest.raises(security.SecurityError) as error:
        security.load_cookies()
    assert "sensitive" not in str(error.value)


@pytest.mark.skipif(sys.platform != "darwin", reason="Requires native macOS Keychain")
def test_native_macos_keychain_round_trip(monkeypatch):
    monkeypatch.setattr(security, "SERVICE", "mfp-mcp-test-" + str(uuid.uuid4()))
    backend = security._keychain()
    try:
        security.save_cookies(COOKIES)
        assert security.load_cookies() == COOKIES
    finally:
        if backend.get_password(security.SERVICE, security.ACCOUNT) is not None:
            backend.delete_password(security.SERVICE, security.ACCOUNT)


def test_client_never_uses_browser_or_dependency_constructor(monkeypatch):
    import browser_cookie3
    import cloudscraper
    import myfitnesspal

    def forbidden(*args, **kwargs):
        pytest.fail("Legacy authentication was invoked")

    monkeypatch.setattr(browser_cookie3, "load", forbidden)
    monkeypatch.setattr(cloudscraper, "create_scraper", forbidden)
    monkeypatch.setattr(myfitnesspal.Client, "__init__", forbidden)
    monkeypatch.setattr(server, "load_cookies", lambda: COOKIES)
    seen = []

    def adapter_send(self, request, **kwargs):
        seen.append(request)
        response = requests.Response()
        response.status_code = 200
        response.headers["Content-Type"] = "application/json"
        payload = ({"user_id": "123", "access_token": "test-token"}
                   if "/user/auth_token" in request.url
                   else {"item": {"username": "test-user"}})
        response._content = json.dumps(payload).encode()
        response.url = request.url
        response.request = request
        return response

    monkeypatch.setattr(requests.adapters.HTTPAdapter, "send", adapter_send)
    client = server.get_mfp_client()
    assert isinstance(client.session, security.RestrictedSession)
    assert client.access_token == "test-token"
    assert client.effective_username == "test-user"
    assert len(seen) == 2
    assert "Cookie" in seen[0].headers
    assert "Cookie" not in seen[1].headers
    assert client._log_requests_to is None


def test_missing_session_stops_before_client_network(monkeypatch):
    def missing():
        raise security.SecurityError("No session")

    def forbidden(*args, **kwargs):
        pytest.fail("Network access occurred without a session")

    monkeypatch.setattr(server, "load_cookies", missing)
    monkeypatch.setattr(requests.adapters.HTTPAdapter, "send", forbidden)
    with pytest.raises(security.SecurityError):
        server.get_mfp_client()


def test_mcp_keeps_write_delete_tools_but_has_no_browser_import_tool():
    names = {tool.name for tool in asyncio.run(server.mcp.list_tools())}
    assert "refresh_browser_cookies" not in names
    assert {"mfp_add_food_to_diary", "mfp_remove_food_from_diary",
            "mfp_set_measurement", "mfp_set_goals", "mfp_set_water",
            "mfp_create_custom_food", "mfp_delete_custom_food",
            "mfp_log_fast", "mfp_update_fast", "mfp_delete_fast"} <= names


def test_mcp_error_does_not_expose_dependency_secrets(monkeypatch):
    def failed():
        raise RuntimeError("Cookie: secret-token; Authorization: Bearer secret-token")
    monkeypatch.setattr(server, "get_mfp_client", failed)
    result = asyncio.run(server.mfp_get_diary(server.GetDiaryInput()))
    assert result.startswith("Error")
    assert "secret-token" not in result


def test_importer_refuses_noninteractive_input(monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["mfp-session", "import"])
    monkeypatch.setattr(sys.stdin, "isatty", lambda: False)
    with pytest.raises(SystemExit):
        security.session_cli()
    assert "interactive Terminal" in capsys.readouterr().err


def test_importer_refuses_getpass_echo_fallback(monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["mfp-session", "import"])
    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)

    def unsafe_prompt(*args):
        import warnings
        warnings.warn("Cannot disable echo", security.getpass.GetPassWarning)
        pytest.fail("Importer continued after echo warning")

    monkeypatch.setattr(security.getpass, "getpass", unsafe_prompt)
    with pytest.raises(SystemExit):
        security.session_cli()
    assert "Traceback" not in capsys.readouterr().err


def test_stdio_server_initializes_and_lists_tools_without_a_session():
    import anyio
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    async def check():
        parameters = StdioServerParameters(
            command=sys.executable,
            args=["-c", "from mfp_mcp.server import main; main()"],
        )
        with anyio.fail_after(20):
            async with (
                stdio_client(parameters) as (reader, writer),
                ClientSession(reader, writer) as session,
            ):
                await session.initialize()
                result = await session.list_tools()
                assert any(tool.name == "mfp_get_diary" for tool in result.tools)
                assert all(tool.name != "refresh_browser_cookies" for tool in result.tools)

    asyncio.run(check())
