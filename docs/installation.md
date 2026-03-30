# Installation

## From PyPI

```bash
pip install markdown-vault-mcp
```

With optional dependencies:

=== "MCP server"

    ```bash
    pip install markdown-vault-mcp[mcp]
    ```
    Adds FastMCP for running as an MCP server.

=== "API embeddings"

    ```bash
    pip install markdown-vault-mcp[embeddings-api]
    ```
    Adds httpx + numpy for Ollama/OpenAI embeddings via HTTP.

=== "Local embeddings"

    ```bash
    pip install markdown-vault-mcp[embeddings]
    ```
    Adds FastEmbed + numpy for local embeddings.

=== "All (recommended)"

    ```bash
    pip install markdown-vault-mcp[all]
    ```
    MCP + FastEmbed + API embeddings.

## Using uv

```bash
uv pip install markdown-vault-mcp[all]
```

## From Source

```bash
git clone https://github.com/pvliesdonk/markdown-vault-mcp.git
cd markdown-vault-mcp
pip install -e ".[all,dev]"
```

## Docker

```bash
docker pull ghcr.io/pvliesdonk/markdown-vault-mcp:latest
```

The Docker image uses `[all]` (MCP + FastEmbed + API embeddings). Semantic search is available by default with FastEmbed and can switch to Ollama/OpenAI when configured.

See [Docker deployment](deployment/docker.md) for compose setup and volume configuration.

## Linux Packages (.deb / .rpm)

Download `.deb` or `.rpm` packages from the [GitHub Releases](https://github.com/pvliesdonk/markdown-vault-mcp/releases) page.

=== "Debian / Ubuntu"

    ```bash
    sudo dpkg -i markdown-vault-mcp_*.deb
    sudo apt-get install -f   # resolve dependencies if needed
    ```

=== "Fedora / RHEL"

    ```bash
    sudo rpm -i markdown-vault-mcp-*.rpm
    ```

The packages install:

| Path | Purpose |
|------|---------|
| `/opt/markdown-vault-mcp/venv/` | Python virtualenv (created by post-install) |
| `/etc/markdown-vault-mcp/env` | Configuration file (created from template on first install) |
| `/var/lib/markdown-vault-mcp/` | State directory (index, embeddings, vault data) |
| `/usr/lib/systemd/system/markdown-vault-mcp.service` | Systemd unit file with security hardening |

A `markdown-vault-mcp` system user and group are created automatically.

After installing, edit `/etc/markdown-vault-mcp/env` to set at least `MARKDOWN_VAULT_MCP_SOURCE_DIR`, then:

```bash
sudo systemctl enable --now markdown-vault-mcp
```

See the [systemd deployment guide](deployment/systemd.md) for full configuration and troubleshooting.

## Verify Installation

```bash
# Check the CLI is available
markdown-vault-mcp --help

# Quick test with a local vault
export MARKDOWN_VAULT_MCP_SOURCE_DIR=/path/to/your/markdown/files
markdown-vault-mcp search "hello world"
```
