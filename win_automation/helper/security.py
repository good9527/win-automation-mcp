"""
Helper Security and Authentication Barrier for win-automation-mcp.
Implements cryptographically secure session token generation and
strict HTTP Host / X-Helper-Token verification to protect against
unauthorized local access and DNS rebinding attacks.
"""

from __future__ import annotations

import hmac
import re
import secrets
from typing import Dict, Tuple


def generate_session_token() -> str:
    """
    Generate a 256-bit cryptographically secure session token.
    Uses secrets.token_urlsafe(32) which produces a URL-safe Base64 string.
    """
    return secrets.token_urlsafe(32)


def verify_request(headers: Dict[str, str], expected_token: str) -> Tuple[bool, int, str]:
    """
    Verify incoming HTTP request headers against security policies.

    Requirements enforced:
    1. Server expected_token must be non-empty.
    2. Host header must strictly match 127.0.0.1, 127.0.0.1:<port>, localhost, or localhost:<port>.
    3. X-Helper-Token header must match expected_token using constant-time comparison.

    Returns:
        (is_valid: bool, status_code: int, message: str)
    """
    if not expected_token:
        return False, 403, "Forbidden: Server token not initialized"

    # Normalize header keys to lowercase
    normalized_headers: Dict[str, str] = {
        str(k).strip().lower(): str(v).strip() for k, v in headers.items()
    }

    # Validate Host header against 127.0.0.1 and localhost with strict numeric port validation
    host = normalized_headers.get("host", "").lower()
    if not host:
        return False, 403, "Forbidden: Missing Host header"

    host_match = re.match(r"^(127\.0\.0\.1|localhost)(?::([0-9]{1,5}))?$", host)
    if not host_match:
        return False, 403, f"Forbidden: Invalid Host header '{host}'"

    port_str = host_match.group(2)
    if port_str is not None:
        port = int(port_str)
        if port < 1 or port > 65535:
            return False, 403, f"Forbidden: Invalid Host port '{port}'"

    # Validate X-Helper-Token header
    auth_header = normalized_headers.get("x-helper-token", "")
    if not auth_header:
        return False, 403, "Forbidden: Missing X-Helper-Token"

    # Constant-time token comparison to prevent timing attacks
    if not hmac.compare_digest(auth_header, expected_token):
        return False, 403, "Forbidden: Invalid X-Helper-Token"

    return True, 200, "OK"
