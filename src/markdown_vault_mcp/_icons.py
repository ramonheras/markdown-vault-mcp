"""Tool icons (Lucide SVGs as data URIs) for MCP tool/resource/prompt decorators."""

from mcp.types import Icon

_TOOL_ICONS: dict[str, list[Icon]] = {
    "search": [
        Icon(
            src="data:image/svg+xml;base64,PHN2ZyB4bWxucz0iaHR0cDovL3d3dy53My5vcmcvMjAwMC9zdmciIHdpZHRoPSIyNCIgaGVpZ2h0PSIyNCIgdmlld0JveD0iMCAwIDI0IDI0Ij48ZyBmaWxsPSJub25lIiBzdHJva2U9ImN1cnJlbnRDb2xvciIgc3Ryb2tlLWxpbmVjYXA9InJvdW5kIiBzdHJva2UtbGluZWpvaW49InJvdW5kIiBzdHJva2Utd2lkdGg9IjIiPjxwYXRoIGQ9Im0yMSAyMWwtNC4zNC00LjM0Ii8+PGNpcmNsZSBjeD0iMTEiIGN5PSIxMSIgcj0iOCIvPjwvZz48L3N2Zz4=",
            mimeType="image/svg+xml",
        )
    ],
    "read": [
        Icon(
            src="data:image/svg+xml;base64,PHN2ZyB4bWxucz0iaHR0cDovL3d3dy53My5vcmcvMjAwMC9zdmciIHdpZHRoPSIyNCIgaGVpZ2h0PSIyNCIgdmlld0JveD0iMCAwIDI0IDI0Ij48ZyBmaWxsPSJub25lIiBzdHJva2U9ImN1cnJlbnRDb2xvciIgc3Ryb2tlLWxpbmVjYXA9InJvdW5kIiBzdHJva2UtbGluZWpvaW49InJvdW5kIiBzdHJva2Utd2lkdGg9IjIiPjxwYXRoIGQ9Ik02IDIyYTIgMiAwIDAgMS0yLTJWNGEyIDIgMCAwIDEgMi0yaDhhMi40IDIuNCAwIDAgMSAxLjcwNC43MDZsMy41ODggMy41ODhBMi40IDIuNCAwIDAgMSAyMCA4djEyYTIgMiAwIDAgMS0yIDJ6Ii8+PHBhdGggZD0iTTE0IDJ2NWExIDEgMCAwIDAgMSAxaDVNMTAgOUg4bTggNEg4bTggNEg4Ii8+PC9nPjwvc3ZnPg==",
            mimeType="image/svg+xml",
        )
    ],
    "list_documents": [
        Icon(
            src="data:image/svg+xml;base64,PHN2ZyB4bWxucz0iaHR0cDovL3d3dy53My5vcmcvMjAwMC9zdmciIHdpZHRoPSIyNCIgaGVpZ2h0PSIyNCIgdmlld0JveD0iMCAwIDI0IDI0Ij48cGF0aCBmaWxsPSJub25lIiBzdHJva2U9ImN1cnJlbnRDb2xvciIgc3Ryb2tlLWxpbmVjYXA9InJvdW5kIiBzdHJva2UtbGluZWpvaW49InJvdW5kIiBzdHJva2Utd2lkdGg9IjIiIGQ9Ik0zIDVoLjAxTTMgMTJoLjAxTTMgMTloLjAxTTggNWgxM004IDEyaDEzTTggMTloMTMiLz48L3N2Zz4=",
            mimeType="image/svg+xml",
        )
    ],
    "list_folders": [
        Icon(
            src="data:image/svg+xml;base64,PHN2ZyB4bWxucz0iaHR0cDovL3d3dy53My5vcmcvMjAwMC9zdmciIHdpZHRoPSIyNCIgaGVpZ2h0PSIyNCIgdmlld0JveD0iMCAwIDI0IDI0Ij48cGF0aCBmaWxsPSJub25lIiBzdHJva2U9ImN1cnJlbnRDb2xvciIgc3Ryb2tlLWxpbmVjYXA9InJvdW5kIiBzdHJva2UtbGluZWpvaW49InJvdW5kIiBzdHJva2Utd2lkdGg9IjIiIGQ9Ik0yMCAyMGEyIDIgMCAwIDAgMi0yVjhhMiAyIDAgMCAwLTItMmgtNy45YTIgMiAwIDAgMS0xLjY5LS45TDkuNiAzLjlBMiAyIDAgMCAwIDcuOTMgM0g0YTIgMiAwIDAgMC0yIDJ2MTNhMiAyIDAgMCAwIDIgMloiLz48L3N2Zz4=",
            mimeType="image/svg+xml",
        )
    ],
    "list_tags": [
        Icon(
            src="data:image/svg+xml;base64,PHN2ZyB4bWxucz0iaHR0cDovL3d3dy53My5vcmcvMjAwMC9zdmciIHdpZHRoPSIyNCIgaGVpZ2h0PSIyNCIgdmlld0JveD0iMCAwIDI0IDI0Ij48ZyBmaWxsPSJub25lIiBzdHJva2U9ImN1cnJlbnRDb2xvciIgc3Ryb2tlLWxpbmVjYXA9InJvdW5kIiBzdHJva2UtbGluZWpvaW49InJvdW5kIiBzdHJva2Utd2lkdGg9IjIiPjxwYXRoIGQ9Ik0xMi41ODYgMi41ODZBMiAyIDAgMCAwIDExLjE3MiAySDRhMiAyIDAgMCAwLTIgMnY3LjE3MmEyIDIgMCAwIDAgLjU4NiAxLjQxNGw4LjcwNCA4LjcwNGEyLjQyNiAyLjQyNiAwIDAgMCAzLjQyIDBsNi41OC02LjU4YTIuNDI2IDIuNDI2IDAgMCAwIDAtMy40MnoiLz48Y2lyY2xlIGN4PSI3LjUiIGN5PSI3LjUiIHI9Ii41IiBmaWxsPSJjdXJyZW50Q29sb3IiLz48L2c+PC9zdmc+",
            mimeType="image/svg+xml",
        )
    ],
    "stats": [
        Icon(
            src="data:image/svg+xml;base64,PHN2ZyB4bWxucz0iaHR0cDovL3d3dy53My5vcmcvMjAwMC9zdmciIHdpZHRoPSIyNCIgaGVpZ2h0PSIyNCIgdmlld0JveD0iMCAwIDI0IDI0Ij48ZyBmaWxsPSJub25lIiBzdHJva2U9ImN1cnJlbnRDb2xvciIgc3Ryb2tlLWxpbmVjYXA9InJvdW5kIiBzdHJva2UtbGluZWpvaW49InJvdW5kIiBzdHJva2Utd2lkdGg9IjIiPjxjaXJjbGUgY3g9IjEyIiBjeT0iMTIiIHI9IjEwIi8+PHBhdGggZD0iTTEyIDE2di00bTAtNGguMDEiLz48L2c+PC9zdmc+",
            mimeType="image/svg+xml",
        )
    ],
    "embeddings_status": [
        Icon(
            src="data:image/svg+xml;base64,PHN2ZyB4bWxucz0iaHR0cDovL3d3dy53My5vcmcvMjAwMC9zdmciIHdpZHRoPSIyNCIgaGVpZ2h0PSIyNCIgdmlld0JveD0iMCAwIDI0IDI0Ij48ZyBmaWxsPSJub25lIiBzdHJva2U9ImN1cnJlbnRDb2xvciIgc3Ryb2tlLWxpbmVjYXA9InJvdW5kIiBzdHJva2UtbGluZWpvaW49InJvdW5kIiBzdHJva2Utd2lkdGg9IjIiPjxwYXRoIGQ9Ik0xMiAxOFY1bTMgOGE0LjE3IDQuMTcgMCAwIDEtMy00YTQuMTcgNC4xNyAwIDAgMS0zIDRtOC41OTgtNi41QTMgMyAwIDEgMCAxMiA1YTMgMyAwIDEgMC01LjU5OCAxLjUiLz48cGF0aCBkPSJNMTcuOTk3IDUuMTI1YTQgNCAwIDAgMSAyLjUyNiA1Ljc3Ii8+PHBhdGggZD0iTTE4IDE4YTQgNCAwIDAgMCAyLTcuNDY0Ii8+PHBhdGggZD0iTTE5Ljk2NyAxNy40ODNBNCA0IDAgMSAxIDEyIDE4YTQgNCAwIDEgMS03Ljk2Ny0uNTE3Ii8+PHBhdGggZD0iTTYgMThhNCA0IDAgMCAxLTItNy40NjQiLz48cGF0aCBkPSJNNi4wMDMgNS4xMjVhNCA0IDAgMCAwLTIuNTI2IDUuNzciLz48L2c+PC9zdmc+",
            mimeType="image/svg+xml",
        )
    ],
    "reindex": [
        Icon(
            src="data:image/svg+xml;base64,PHN2ZyB4bWxucz0iaHR0cDovL3d3dy53My5vcmcvMjAwMC9zdmciIHdpZHRoPSIyNCIgaGVpZ2h0PSIyNCIgdmlld0JveD0iMCAwIDI0IDI0Ij48ZyBmaWxsPSJub25lIiBzdHJva2U9ImN1cnJlbnRDb2xvciIgc3Ryb2tlLWxpbmVjYXA9InJvdW5kIiBzdHJva2UtbGluZWpvaW49InJvdW5kIiBzdHJva2Utd2lkdGg9IjIiPjxwYXRoIGQ9Ik0zIDEyYTkgOSAwIDAgMSA5LTlhOS43NSA5Ljc1IDAgMCAxIDYuNzQgMi43NEwyMSA4Ii8+PHBhdGggZD0iTTIxIDN2NWgtNW01IDRhOSA5IDAgMCAxLTkgOWE5Ljc1IDkuNzUgMCAwIDEtNi43NC0yLjc0TDMgMTYiLz48cGF0aCBkPSJNOCAxNkgzdjUiLz48L2c+PC9zdmc+",
            mimeType="image/svg+xml",
        )
    ],
    "build_embeddings": [
        Icon(
            src="data:image/svg+xml;base64,PHN2ZyB4bWxucz0iaHR0cDovL3d3dy53My5vcmcvMjAwMC9zdmciIHdpZHRoPSIyNCIgaGVpZ2h0PSIyNCIgdmlld0JveD0iMCAwIDI0IDI0Ij48ZyBmaWxsPSJub25lIiBzdHJva2U9ImN1cnJlbnRDb2xvciIgc3Ryb2tlLWxpbmVjYXA9InJvdW5kIiBzdHJva2UtbGluZWpvaW49InJvdW5kIiBzdHJva2Utd2lkdGg9IjIiPjxwYXRoIGQ9Im0xMC44NTIgMTQuNzcybC0uMzgzLjkyM20uMzgzLTYuNDY3bC0uMzgzLS45MjNtMi42NzkgNi40NjdsLjM4Mi45MjRtLjAwMS03LjM5MWwtLjM4My45MjNtMS42MjQgMS42MjRsLjkyMy0uMzgzbS0uOTIzIDIuNjc5bC45MjMuMzgzTTE3LjU5OCA2LjVBMyAzIDAgMSAwIDEyIDVhMyAzIDAgMCAwLTUuNjMtMS40NDZhMyAzIDAgMCAwLS4zNjggMS41NzFhNCA0IDAgMCAwLTIuNTI1IDUuNzcxIi8+PHBhdGggZD0iTTE3Ljk5OCA1LjEyNWE0IDQgMCAwIDEgMi41MjUgNS43NzEiLz48cGF0aCBkPSJNMTkuNTA1IDEwLjI5NGE0IDQgMCAwIDEtMS41IDcuNzA2Ii8+PHBhdGggZD0iTTQuMDMyIDE3LjQ4M0E0IDQgMCAwIDAgMTEuNDY0IDIwYy4xOC0uMzExLjg5Mi0uMzExIDEuMDcyIDBhNCA0IDAgMCAwIDcuNDMyLTIuNTE2Ii8+PHBhdGggZD0iTTQuNSAxMC4yOTFBNCA0IDAgMCAwIDYgMThtLjAwMi0xMi44NzVhMyAzIDAgMCAwIC40IDEuMzc1bTIuODI2IDQuMzUybC0uOTIzLS4zODNtLjkyMyAyLjY3OWwtLjkyMy4zODMiLz48Y2lyY2xlIGN4PSIxMiIgY3k9IjEyIiByPSIzIi8+PC9nPjwvc3ZnPg==",
            mimeType="image/svg+xml",
        )
    ],
    "write": [
        Icon(
            src="data:image/svg+xml;base64,PHN2ZyB4bWxucz0iaHR0cDovL3d3dy53My5vcmcvMjAwMC9zdmciIHdpZHRoPSIyNCIgaGVpZ2h0PSIyNCIgdmlld0JveD0iMCAwIDI0IDI0Ij48ZyBmaWxsPSJub25lIiBzdHJva2U9ImN1cnJlbnRDb2xvciIgc3Ryb2tlLWxpbmVjYXA9InJvdW5kIiBzdHJva2UtbGluZWpvaW49InJvdW5kIiBzdHJva2Utd2lkdGg9IjIiPjxwYXRoIGQ9Ik02IDIyYTIgMiAwIDAgMS0yLTJWNGEyIDIgMCAwIDEgMi0yaDhhMi40IDIuNCAwIDAgMSAxLjcwNC43MDZsMy41ODggMy41ODhBMi40IDIuNCAwIDAgMSAyMCA4djEyYTIgMiAwIDAgMS0yIDJ6Ii8+PHBhdGggZD0iTTE0IDJ2NWExIDEgMCAwIDAgMSAxaDVNOSAxNWg2bS0zIDN2LTYiLz48L2c+PC9zdmc+",
            mimeType="image/svg+xml",
        )
    ],
    "edit": [
        Icon(
            src="data:image/svg+xml;base64,PHN2ZyB4bWxucz0iaHR0cDovL3d3dy53My5vcmcvMjAwMC9zdmciIHdpZHRoPSIyNCIgaGVpZ2h0PSIyNCIgdmlld0JveD0iMCAwIDI0IDI0Ij48cGF0aCBmaWxsPSJub25lIiBzdHJva2U9ImN1cnJlbnRDb2xvciIgc3Ryb2tlLWxpbmVjYXA9InJvdW5kIiBzdHJva2UtbGluZWpvaW49InJvdW5kIiBzdHJva2Utd2lkdGg9IjIiIGQ9Ik0yMS4xNzQgNi44MTJhMSAxIDAgMCAwLTMuOTg2LTMuOTg3TDMuODQyIDE2LjE3NGEyIDIgMCAwIDAtLjUuODNsLTEuMzIxIDQuMzUyYS41LjUgMCAwIDAgLjYyMy42MjJsNC4zNTMtMS4zMmEyIDIgMCAwIDAgLjgzLS40OTd6TTE1IDVsNCA0Ii8+PC9zdmc+",
            mimeType="image/svg+xml",
        )
    ],
    "delete": [
        Icon(
            src="data:image/svg+xml;base64,PHN2ZyB4bWxucz0iaHR0cDovL3d3dy53My5vcmcvMjAwMC9zdmciIHdpZHRoPSIyNCIgaGVpZ2h0PSIyNCIgdmlld0JveD0iMCAwIDI0IDI0Ij48cGF0aCBmaWxsPSJub25lIiBzdHJva2U9ImN1cnJlbnRDb2xvciIgc3Ryb2tlLWxpbmVjYXA9InJvdW5kIiBzdHJva2UtbGluZWpvaW49InJvdW5kIiBzdHJva2Utd2lkdGg9IjIiIGQ9Ik0xMCAxMXY2bTQtNnY2bTUtMTF2MTRhMiAyIDAgMCAxLTIgMkg3YTIgMiAwIDAgMS0yLTJWNk0zIDZoMThNOCA2VjRhMiAyIDAgMCAxIDItMmg0YTIgMiAwIDAgMSAyIDJ2MiIvPjwvc3ZnPg==",
            mimeType="image/svg+xml",
        )
    ],
    "rename": [
        Icon(
            src="data:image/svg+xml;base64,PHN2ZyB4bWxucz0iaHR0cDovL3d3dy53My5vcmcvMjAwMC9zdmciIHdpZHRoPSIyNCIgaGVpZ2h0PSIyNCIgdmlld0JveD0iMCAwIDI0IDI0Ij48cGF0aCBmaWxsPSJub25lIiBzdHJva2U9ImN1cnJlbnRDb2xvciIgc3Ryb2tlLWxpbmVjYXA9InJvdW5kIiBzdHJva2UtbGluZWpvaW49InJvdW5kIiBzdHJva2Utd2lkdGg9IjIiIGQ9Ik0xMiAydjIwbTMtM2wtMyAzbC0zLTNNMTkgOWwzIDNsLTMgM00yIDEyaDIwTTUgOWwtMyAzbDMgM005IDVsMy0zbDMgMyIvPjwvc3ZnPg==",
            mimeType="image/svg+xml",
        )
    ],
    "get_backlinks": [
        Icon(
            src="data:image/svg+xml;base64,PHN2ZyB4bWxucz0iaHR0cDovL3d3dy53My5vcmcvMjAwMC9zdmciIHdpZHRoPSIyNCIgaGVpZ2h0PSIyNCIgdmlld0JveD0iMCAwIDI0IDI0Ij48ZyBmaWxsPSJub25lIiBzdHJva2U9ImN1cnJlbnRDb2xvciIgc3Ryb2tlLWxpbmVjYXA9InJvdW5kIiBzdHJva2UtbGluZWpvaW49InJvdW5kIiBzdHJva2Utd2lkdGg9IjIiPjxwYXRoIGQ9Ik0xMCAxM2E1IDUgMCAwIDAgNy41NC41NGwzLTNhNSA1IDAgMCAwLTcuMDctNy4wN2wtMS43MiAxLjcxIi8+PHBhdGggZD0iTTE0IDExYTUgNSAwIDAgMC03LjU0LS41NGwtMyAzYTUgNSAwIDAgMCA3LjA3IDcuMDdsMS43MS0xLjcxIi8+PC9nPjwvc3ZnPg==",
            mimeType="image/svg+xml",
        )
    ],
    "get_outlinks": [
        Icon(
            src="data:image/svg+xml;base64,PHN2ZyB4bWxucz0iaHR0cDovL3d3dy53My5vcmcvMjAwMC9zdmciIHdpZHRoPSIyNCIgaGVpZ2h0PSIyNCIgdmlld0JveD0iMCAwIDI0IDI0Ij48cGF0aCBmaWxsPSJub25lIiBzdHJva2U9ImN1cnJlbnRDb2xvciIgc3Ryb2tlLWxpbmVjYXA9InJvdW5kIiBzdHJva2UtbGluZWpvaW49InJvdW5kIiBzdHJva2Utd2lkdGg9IjIiIGQ9Ik0xNSAzaDZ2Nm0tMTEgNUwyMSAzbS0zIDEwdjZhMiAyIDAgMCAxLTIgMkg1YTIgMiAwIDAgMS0yLTJWOGEyIDIgMCAwIDEgMi0yaDYiLz48L3N2Zz4=",
            mimeType="image/svg+xml",
        )
    ],
    "get_recent": [
        Icon(
            src="data:image/svg+xml;base64,PHN2ZyB4bWxucz0iaHR0cDovL3d3dy53My5vcmcvMjAwMC9zdmciIHdpZHRoPSIyNCIgaGVpZ2h0PSIyNCIgdmlld0JveD0iMCAwIDI0IDI0Ij48ZyBmaWxsPSJub25lIiBzdHJva2U9ImN1cnJlbnRDb2xvciIgc3Ryb2tlLWxpbmVjYXA9InJvdW5kIiBzdHJva2UtbGluZWpvaW49InJvdW5kIiBzdHJva2Utd2lkdGg9IjIiPjxjaXJjbGUgY3g9IjEyIiBjeT0iMTIiIHI9IjEwIi8+PHBhdGggZD0iTTEyIDZ2Nmw0IDIiLz48L2c+PC9zdmc+",
            mimeType="image/svg+xml",
        )
    ],
    "get_similar": [
        Icon(
            src="data:image/svg+xml;base64,PHN2ZyB4bWxucz0iaHR0cDovL3d3dy53My5vcmcvMjAwMC9zdmciIHdpZHRoPSIyNCIgaGVpZ2h0PSIyNCIgdmlld0JveD0iMCAwIDI0IDI0Ij48ZyBmaWxsPSJub25lIiBzdHJva2U9ImN1cnJlbnRDb2xvciIgc3Ryb2tlLWxpbmVjYXA9InJvdW5kIiBzdHJva2UtbGluZWpvaW49InJvdW5kIiBzdHJva2Utd2lkdGg9IjIiPjxjaXJjbGUgY3g9IjUiIGN5PSI2IiByPSIzIi8+PHBhdGggZD0iTTEyIDZoNWEyIDIgMCAwIDEgMiAydjciLz48cGF0aCBkPSJtMTUgOWwtMy0zbDMtMyIvPjxjaXJjbGUgY3g9IjE5IiBjeT0iMTgiIHI9IjMiLz48cGF0aCBkPSJNMTIgMThIN2EyIDIgMCAwIDEtMi0yVjkiLz48cGF0aCBkPSJtOSAxNWwzIDNsLTMgMyIvPjwvZz48L3N2Zz4=",
            mimeType="image/svg+xml",
        )
    ],
    "get_broken_links": [
        Icon(
            src="data:image/svg+xml;base64,PHN2ZyB4bWxucz0iaHR0cDovL3d3dy53My5vcmcvMjAwMC9zdmciIHdpZHRoPSIyNCIgaGVpZ2h0PSIyNCIgdmlld0JveD0iMCAwIDI0IDI0Ij48cGF0aCBmaWxsPSJub25lIiBzdHJva2U9ImN1cnJlbnRDb2xvciIgc3Ryb2tlLWxpbmVjYXA9InJvdW5kIiBzdHJva2UtbGluZWpvaW49InJvdW5kIiBzdHJva2Utd2lkdGg9IjIiIGQ9Im0xOC44NCAxMi4yNWwxLjcyLTEuNzFoLS4wMmE1LjAwNCA1LjAwNCAwIDAgMC0uMTItNy4wN2E1LjAwNiA1LjAwNiAwIDAgMC02Ljk1IDBsLTEuNzIgMS43MW0tNi41OCA2LjU3bC0xLjcxIDEuNzFhNS4wMDQgNS4wMDQgMCAwIDAgLjEyIDcuMDdhNS4wMDYgNS4wMDYgMCAwIDAgNi45NSAwbDEuNzEtMS43MU04IDJ2M00yIDhoM20xMSAxMXYzbTMtNmgzIi8+PC9zdmc+",
            mimeType="image/svg+xml",
        )
    ],
    "get_context": [
        Icon(
            src="data:image/svg+xml;base64,PHN2ZyB4bWxucz0iaHR0cDovL3d3dy53My5vcmcvMjAwMC9zdmciIHdpZHRoPSIyNCIgaGVpZ2h0PSIyNCIgdmlld0JveD0iMCAwIDI0IDI0Ij48ZyBmaWxsPSJub25lIiBzdHJva2U9ImN1cnJlbnRDb2xvciIgc3Ryb2tlLWxpbmVjYXA9InJvdW5kIiBzdHJva2UtbGluZWpvaW49InJvdW5kIiBzdHJva2Utd2lkdGg9IjIiPjxwYXRoIGQ9Ik0zIDdWNWEyIDIgMCAwIDEgMi0yaDJNMTcgM2gyYTIgMiAwIDAgMSAyIDJ2Mk0yMSAxN3YyYTIgMiAwIDAgMS0yIDJoLTJNNyAyMUg1YTIgMiAwIDAgMS0yLTJ2LTIiLz48Y2lyY2xlIGN4PSIxMiIgY3k9IjEyIiByPSIxIi8+PHBhdGggZD0iTTE4Ljk0NCAxMi4zM2ExIDEgMCAwIDAgMC0uNjYgNy41IDcuNSAwIDAgMC0xMS44ODggMGExIDEgMCAwIDAgMCAuNjZhNy41IDcuNSAwIDAgMCAxMS44ODggMCIvPjwvZz48L3N2Zz4=",
            mimeType="image/svg+xml",
        )
    ],
    "get_orphan_notes": [
        Icon(
            src="data:image/svg+xml;base64,PHN2ZyB4bWxucz0iaHR0cDovL3d3dy53My5vcmcvMjAwMC9zdmciIHdpZHRoPSIyNCIgaGVpZ2h0PSIyNCIgdmlld0JveD0iMCAwIDI0IDI0Ij48cGF0aCBmaWxsPSJub25lIiBzdHJva2U9ImN1cnJlbnRDb2xvciIgc3Ryb2tlLWxpbmVjYXA9InJvdW5kIiBzdHJva2UtbGluZWpvaW49InJvdW5kIiBzdHJva2Utd2lkdGg9IjIiIGQ9Ik05IDE3SDdBNSA1IDAgMCAxIDcgN204IDBoMmE1IDUgMCAwIDEgNCA4TTggMTJoNE0yIDJsMjAgMjAiLz48L3N2Zz4=",
            mimeType="image/svg+xml",
        )
    ],
    "get_most_linked": [
        Icon(
            src="data:image/svg+xml;base64,PHN2ZyB4bWxucz0iaHR0cDovL3d3dy53My5vcmcvMjAwMC9zdmciIHdpZHRoPSIyNCIgaGVpZ2h0PSIyNCIgdmlld0JveD0iMCAwIDI0IDI0Ij48ZyBmaWxsPSJub25lIiBzdHJva2U9ImN1cnJlbnRDb2xvciIgc3Ryb2tlLWxpbmVjYXA9InJvdW5kIiBzdHJva2UtbGluZWpvaW49InJvdW5kIiBzdHJva2Utd2lkdGg9IjIiPjxwYXRoIGQ9Im0xNS40NzcgMTIuODlsMS41MTUgOC41MjZhLjUuNSAwIDAgMS0uODEuNDdsLTMuNTgtMi42ODdhMSAxIDAgMCAwLTEuMTk3IDBsLTMuNTg2IDIuNjg2YS41LjUgMCAwIDEtLjgxLS40NjlsMS41MTQtOC41MjYiLz48Y2lyY2xlIGN4PSIxMiIgY3k9IjgiIHI9IjYiLz48L2c+PC9zdmc+",
            mimeType="image/svg+xml",
        )
    ],
    "get_connection_path": [
        Icon(
            src="data:image/svg+xml;base64,PHN2ZyB4bWxucz0iaHR0cDovL3d3dy53My5vcmcvMjAwMC9zdmciIHdpZHRoPSIyNCIgaGVpZ2h0PSIyNCIgdmlld0JveD0iMCAwIDI0IDI0Ij48ZyBmaWxsPSJub25lIiBzdHJva2U9ImN1cnJlbnRDb2xvciIgc3Ryb2tlLWxpbmVjYXA9InJvdW5kIiBzdHJva2UtbGluZWpvaW49InJvdW5kIiBzdHJva2Utd2lkdGg9IjIiPjxjaXJjbGUgY3g9IjYiIGN5PSIxOSIgcj0iMyIvPjxwYXRoIGQ9Ik05IDE5aDhjMSAwIDItMSAyLTJ2LTFhMiAyIDAgMCAwLTItMmgtNWEyIDIgMCAwIDEtMi0yVjZhMiAyIDAgMCAxIDItMmgxIi8+PGNpcmNsZSBjeD0iMTgiIGN5PSIzIiByPSIzIi8+PC9nPjwvc3ZnPg==",
            mimeType="image/svg+xml",
        )
    ],
    "fetch": [
        Icon(
            src="data:image/svg+xml;base64,PHN2ZyB4bWxucz0iaHR0cDovL3d3dy53My5vcmcvMjAwMC9zdmciIHdpZHRoPSIyNCIgaGVpZ2h0PSIyNCIgdmlld0JveD0iMCAwIDI0IDI0Ij48cGF0aCBmaWxsPSJub25lIiBzdHJva2U9ImN1cnJlbnRDb2xvciIgc3Ryb2tlLWxpbmVjYXA9InJvdW5kIiBzdHJva2UtbGluZWpvaW49InJvdW5kIiBzdHJva2Utd2lkdGg9IjIiIGQ9Ik0yMSAxNXY0YTIgMiAwIDAgMS0yIDJINWEyIDIgMCAwIDEtMi0ydi00bTQtNWw1IDVsNS01bS01IDVWMyIvPjwvc3ZnPg==",
            mimeType="image/svg+xml",
        )
    ],
}
