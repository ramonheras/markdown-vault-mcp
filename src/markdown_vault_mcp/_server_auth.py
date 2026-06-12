"""Auth assembly for markdown-vault-mcp.

The pvl-core auth builder owns the generic mode dispatch.  This module keeps
that behaviour, but wires persistent encrypted client storage into OIDC proxy
mode so Dynamic Client Registration survives container restarts.
"""

from __future__ import annotations

import base64
import hashlib
import logging
import sys
from pathlib import Path
from typing import Any, cast
from urllib.parse import unquote, urlparse

from cryptography.fernet import Fernet
from fastmcp_pvl_core import (
    ServerConfig,
    build_bearer_auth,
    build_kv_store,
    build_remote_auth,
    env,
    resolve_auth_mode,
)
from fastmcp_pvl_core import (
    build_auth as _core_build_auth,
)
from key_value.aio.wrappers.encryption import FernetEncryptionWrapper

from markdown_vault_mcp.config import _ENV_PREFIX

logger = logging.getLogger(__name__)

_OIDC_PROXY_COLLECTIONS = (
    "mcp-upstream-tokens",
    "mcp-oauth-proxy-clients",
    "mcp-oauth-transactions",
    "mcp-authorization-codes",
    "mcp-jti-mappings",
    "mcp-refresh-tokens",
)


def _derive_fernet_key(secret: str) -> bytes:
    """Derive a Fernet-compatible key from an operator-managed secret."""
    digest = hashlib.sha256(secret.encode("utf-8")).digest()
    return base64.urlsafe_b64encode(digest)


def _storage_encryption_key(config: ServerConfig) -> bytes | None:
    raw_key = env(_ENV_PREFIX, "OIDC_CLIENT_STORAGE_FERNET_KEY")
    if raw_key:
        return raw_key.encode("utf-8")
    if config.oidc_jwt_signing_key:
        return _derive_fernet_key(config.oidc_jwt_signing_key)
    return None


def _file_kv_store_directory(config: ServerConfig) -> Path | None:
    """Return the local directory for file:// KV stores, if configured."""
    kv_store_url = getattr(config, "kv_store_url", None) or getattr(
        config, "event_store_url", None
    )
    if not kv_store_url:
        return None

    parsed = urlparse(kv_store_url)
    if parsed.scheme != "file":
        return None
    if parsed.netloc not in {"", "localhost"}:
        return None
    if not parsed.path:
        return None
    return Path(unquote(parsed.path))


def _prime_oidc_file_kv_collections(
    config: ServerConfig,
    *,
    namespace: str,
) -> None:
    """Pre-create OAuth collection directories for file-backed KV stores.

    FastMCP lazily initializes per-collection metadata. Under concurrent OAuth
    handshakes we have seen collection info files created without the matching
    directory, which then crashes the first write with FileNotFoundError during
    mkstemp(). Creating the directories up front keeps the filetree backend in a
    consistent state across restarts and concurrent registrations.
    """
    data_directory = _file_kv_store_directory(config)
    if data_directory is None:
        return

    data_directory.mkdir(parents=True, exist_ok=True)
    for collection in _OIDC_PROXY_COLLECTIONS:
        (data_directory / f"{namespace}__{collection}").mkdir(
            parents=True,
            exist_ok=True,
        )


def build_oidc_client_storage(config: ServerConfig) -> Any | None:
    """Build encrypted persistent storage for OAuth proxy clients and tokens."""
    encryption_key = _storage_encryption_key(config)
    if encryption_key is None:
        logger.warning(
            "oidc_client_storage_disabled reason=missing_encryption_key "
            "set %s_OIDC_JWT_SIGNING_KEY or %s_OIDC_CLIENT_STORAGE_FERNET_KEY "
            "to persist OAuth clients",
            _ENV_PREFIX,
            _ENV_PREFIX,
        )
        return None

    _prime_oidc_file_kv_collections(config, namespace="oauth")

    return FernetEncryptionWrapper(
        key_value=build_kv_store(config, namespace="oauth"),
        fernet=Fernet(encryption_key),
    )


def build_oidc_proxy_auth(config: ServerConfig) -> Any | None:
    """Build an OIDCProxy with persistent encrypted client storage."""
    required_public = {
        "BASE_URL": config.base_url,
        "OIDC_CONFIG_URL": config.oidc_config_url,
        "OIDC_CLIENT_ID": config.oidc_client_id,
    }
    has_secret = bool(config.oidc_client_secret)
    if not all(required_public.values()) or not has_secret:
        missing = [k for k, v in required_public.items() if not v]
        if not has_secret:
            missing.append("OIDC_CLIENT_SECRET")
        logger.debug("oidc_proxy_auth_skipped missing=%s", ",".join(missing))
        return None

    required_scopes: list[str] = list(config.oidc_required_scopes) or ["openid"]
    verify_access_token = config.oidc_verify_access_token
    verify_id_token = not verify_access_token

    if verify_id_token and "openid" not in required_scopes:
        logger.warning(
            "oidc_proxy_auth_scope_warning "
            "verify_id_token=True missing_scope=openid - "
            "the id_token may be absent from the token response; "
            "add 'openid' to required_scopes or set oidc_verify_access_token=True"
        )

    if config.oidc_jwt_signing_key is None and sys.platform.startswith("linux"):
        logger.warning(
            "oidc_proxy_auth_ephemeral_signing_key "
            "oidc_jwt_signing_key=<unset> - tokens will be invalidated on "
            "every server restart; configure OIDC_JWT_SIGNING_KEY in production"
        )

    from fastmcp.server.auth.oidc_proxy import OIDCProxy

    client_storage = build_oidc_client_storage(config)
    if client_storage is not None:
        logger.info("oidc_client_storage=enabled backend=kv_store namespace=oauth")

    return OIDCProxy(
        config_url=cast("str", config.oidc_config_url),
        client_id=cast("str", config.oidc_client_id),
        client_secret=cast("str", config.oidc_client_secret),
        base_url=cast("str", config.base_url),
        audience=config.oidc_audience,
        required_scopes=required_scopes,
        jwt_signing_key=config.oidc_jwt_signing_key,
        verify_id_token=verify_id_token,
        require_authorization_consent=False,
        client_storage=client_storage,
    )


def build_auth(config: ServerConfig) -> Any:
    """Build auth, adding persistent storage for OIDC proxy modes."""
    mode = resolve_auth_mode(config)
    if mode not in {"oidc-proxy", "multi"}:
        return _core_build_auth(config)

    try:
        from fastmcp_pvl_core._subject import set_current_auth_mode
    except ImportError:  # pragma: no cover - defensive across pvl-core versions
        set_current_auth_mode = None

    if set_current_auth_mode is not None:
        set_current_auth_mode(mode)

    if mode == "oidc-proxy":
        return build_oidc_proxy_auth(config)

    oidc_auth = build_oidc_proxy_auth(config) or build_remote_auth(config)
    bearer_auth = build_bearer_auth(config)

    if oidc_auth is None or bearer_auth is None:
        logger.warning(
            "multi_auth_degraded oidc=%s bearer=%s - falling back to whichever "
            "auth provider succeeded",
            oidc_auth is not None,
            bearer_auth is not None,
        )
        return oidc_auth or bearer_auth

    from fastmcp.server.auth import MultiAuth

    return MultiAuth(
        server=oidc_auth,
        verifiers=[bearer_auth],
        required_scopes=[],
    )
