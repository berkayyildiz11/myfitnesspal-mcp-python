"""Restricted macOS session storage and MyFitnessPal HTTP transport.

This is application-level hardening, not an operating-system sandbox.
"""

import getpass
import json
import re
import sys
import warnings
from datetime import datetime, timedelta, timezone
from http.cookiejar import Cookie, CookieJar
from urllib.parse import urlsplit

import requests

SERVICE = "mfp-mcp-session"
ACCOUNT = "myfitnesspal"
ALLOWED_HOSTS = frozenset({"www.myfitnesspal.com", "api.myfitnesspal.com"})
SESSION_NAME = re.compile(
    r"(?:__Secure-next-auth\.session-token|__Host-next-auth\.session-token|"
    r"next-auth\.session-token|_mfp_session)(?:\.\d+)?\Z"
)


class SecurityError(RuntimeError):
    """A local security policy rejected an operation."""


def validate_cookies(cookies):
    if not isinstance(cookies, dict) or not cookies or len(cookies) > 16:
        raise SecurityError("Provide a JSON object containing only session cookies.")
    for name, value in cookies.items():
        if not isinstance(name, str) or not SESSION_NAME.fullmatch(name):
            raise SecurityError("Only MyFitnessPal session-token cookies are accepted.")
        if (not isinstance(value, str) or not value or len(value) > 32768
                or any(ord(c) < 33 or ord(c) > 126 or c in ';,' for c in value)):
            raise SecurityError("Invalid session cookie value.")
    return cookies


def _keychain():
    # Never select an alternative backend, including a plaintext file backend.
    if sys.platform != "darwin":
        raise SecurityError("Session storage requires macOS Keychain.")
    from keyring.backends.macOS import Keyring
    return Keyring()


def save_cookies(cookies):
    payload = {"cookies": validate_cookies(cookies),
               "saved_at": datetime.now(timezone.utc).isoformat()}
    try:
        _keychain().set_password(SERVICE, ACCOUNT, json.dumps(payload))
    except SecurityError:
        raise
    except Exception:  # noqa: BLE001 — never expose backend diagnostics or secrets.
        raise SecurityError("Could not save session to macOS Keychain.") from None


def load_cookies():
    try:
        raw = _keychain().get_password(SERVICE, ACCOUNT)
        if not raw:
            raise SecurityError("No session in Keychain. Run mfp-session import first.")
        payload = json.loads(raw)
        saved = datetime.fromisoformat(payload["saved_at"])
        age = datetime.now(timezone.utc) - saved
        if age < timedelta(0) or age > timedelta(days=30):
            raise SecurityError("Stored session is too old. Run mfp-session import again.")
        return validate_cookies(payload["cookies"])
    except SecurityError:
        raise
    except Exception:  # noqa: BLE001 — corrupt/backend data must fail closed.
        raise SecurityError("Could not read a valid session from macOS Keychain.") from None


def dict_to_cookiejar(cookies):
    jar = CookieJar()
    for name, value in validate_cookies(cookies).items():
        jar.set_cookie(Cookie(
            version=0, name=name, value=value, port=None, port_specified=False,
            domain="www.myfitnesspal.com", domain_specified=False,
            domain_initial_dot=False, path="/", path_specified=True, secure=True,
            expires=None, discard=True, comment=None, comment_url=None,
            rest={"HttpOnly": None}, rfc2109=False,
        ))
    return jar


def validate_url(url):
    try:
        parsed = urlsplit(url)
        valid = (parsed.scheme == "https" and parsed.hostname in ALLOWED_HOSTS
                 and parsed.port in (None, 443) and parsed.username is None
                 and parsed.password is None)
    except (ValueError, TypeError):
        valid = False
    if not valid:
        # Never include an attacker-controlled URL or credentials in the error.
        raise SecurityError("Request blocked: only approved MyFitnessPal HTTPS hosts are allowed.")


class RestrictedSession(requests.Session):
    def __init__(self):
        super().__init__()
        self.trust_env = False  # Ignore proxies, .netrc and custom CA environment variables.

    def send(self, request, **kwargs):
        # send() runs for every redirect as well as the initial request.
        validate_url(request.url)
        if kwargs.get("proxies") or self.proxies:
            raise SecurityError("Proxies are disabled for MyFitnessPal requests.")
        if kwargs.get("verify", True) is not True:
            raise SecurityError("TLS certificate verification must remain enabled.")
        kwargs["verify"] = True
        if kwargs.get("timeout") is None:
            kwargs["timeout"] = 30
        # CookieJar can apply permissive subdomain rules; also enforce at the wire boundary.
        if urlsplit(request.url).hostname != "www.myfitnesspal.com":
            request.headers.pop("Cookie", None)
        return super().send(request, **kwargs)


def session_cli():
    """Import a session without shell arguments, files, browser access or MCP."""
    try:
        if len(sys.argv) != 2 or sys.argv[1] not in {"import", "delete"}:
            raise SecurityError("Usage: mfp-session import | delete")
        if not sys.stdin.isatty():
            raise SecurityError("Run this command in an interactive Terminal.")
        if sys.argv[1] == "delete":
            _keychain().delete_password(SERVICE, ACCOUNT)
            print("Local Keychain session removed. This does not revoke the server session.")
            return
        with warnings.catch_warnings():
            warnings.simplefilter("error", getpass.GetPassWarning)
            raw = getpass.getpass("MyFitnessPal session cookies as JSON (hidden): ")
        try:
            cookies = json.loads(raw)
        except (ValueError, TypeError):
            raise SecurityError("Invalid JSON; session was not saved.") from None
        save_cookies(cookies)
        print("Session saved to macOS Keychain. No browser database was accessed.")
    except Exception as exc:  # noqa: BLE001 — do not print secret-bearing tracebacks.
        print(str(exc) if isinstance(exc, SecurityError) else "Keychain operation failed.",
              file=sys.stderr)
        raise SystemExit(1) from None
