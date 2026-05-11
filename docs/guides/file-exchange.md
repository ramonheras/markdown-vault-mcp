# MCP File Exchange

`fastmcp-pvl-core` 2.1.0+ ships two helpers for spec-compliant out-of-band
file transfer between co-deployed MCP servers (and HTTP fallback for
remote clients):

- `register_file_exchange(...)` — download direction. Mints a
  spec-compliant `create_download_link(origin_id, ttl_seconds)` tool
  and a one-time `GET /uploads/{token}` route.
- `register_file_exchange_upload(...)` — upload direction. Mints a
  spec-compliant `create_upload_link(target_id, ttl_seconds)` tool and
  a one-time `POST /uploads/{token}` route.

Both helpers' wiring lives inside the
`DOMAIN-FILE-EXCHANGE-START` / `DOMAIN-FILE-EXCHANGE-END` sentinel
block in `src/markdown_vault_mcp/server.py`. The block is preserved
across `copier update`.

## Status in markdown-vault-mcp

!!! warning "Not wired today"
    **Neither direction is currently wired in this server.** The
    download-direction `register_file_exchange(...)` call is deferred
    to [#431](https://github.com/pvliesdonk/markdown-vault-mcp/issues/431)
    because the spec-compliant `create_download_link(origin_id,
    ttl_seconds)` tool name collides with MV's existing
    `create_download_link(path, ttl_seconds)` tool (registered via
    `ArtifactStore` in the `DOMAIN-WIRING` block). Wiring both would
    silently shadow one or the other depending on registration order.
    The upload-direction `register_file_exchange_upload(...)` ships
    fully commented-out in `server.py` and is intended to be
    uncommented alongside the #431 migration.

## Today

For inbound file transfers, the existing tools are:

- **`fetch(url, path)`** — server-side download from an HTTP/HTTPS URL
  into the vault. Useful when the file is publicly accessible by URL.
- **`write(path, content_base64)`** — round-trip binary content
  through the LLM context. Bounded by
  `MARKDOWN_VAULT_MCP_MAX_ATTACHMENT_SIZE_MB` (default 1 MB); not
  recommended for files larger than ~100 KB because of base64
  inflation. Once #431 lands and `register_file_exchange_upload(...)`
  is uncommented, `create_upload_link(target_id)` will be the right
  alternative.

For outbound file transfers, the existing tool is:

- **`create_download_link(path, ttl_seconds)`** — mints a one-time
  `GET /artifacts/{token}` URL backed by `ArtifactStore`. This is the
  tool that conflicts with the spec-compliant version's name.

## Configuration

The pvl-core helpers' env-var contract is documented in
[Configuration > MCP File Exchange](../configuration.md#mcp-file-exchange).
Setting any of those vars currently has no effect because neither
helper is called.

## When #431 lands

The migration in #431 will:

1. Drop MV's bespoke `create_download_link` tool registration.
2. Drop the `ArtifactStore` HTTP route in the `DOMAIN-WIRING` block.
3. Uncomment the `register_file_exchange(...)` call in the
   `DOMAIN-FILE-EXCHANGE` sentinel block.
4. Optionally uncomment `register_file_exchange_upload(...)` and
   flesh out `_upload_receiver` / `_validate_upload_target` for the
   inbound direction.
5. Update this guide to remove the warning admonition above and
   document the wired patterns.

See [#431](https://github.com/pvliesdonk/markdown-vault-mcp/issues/431)
for status.
