---
description: Summarize a document.
arguments:
  - name: path
    description: Path to the document to summarize.
    required: true
icons: read
---
Call the `read` tool with path='$path'. The result contains a `content` field (the markdown body) and a `frontmatter` field (metadata). Write a concise summary covering the document's main topics and key points. If `read` returns an error, report it and stop.
