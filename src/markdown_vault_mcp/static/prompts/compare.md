---
description: Compare two documents.
arguments:
  - name: path1
    description: Path to the first document.
    required: true
  - name: path2
    description: Path to the second document.
    required: true
icons: read
---
Call `read` for both '$path1' and '$path2'. Use the `content` field from each result for comparison. Present your comparison covering:
- What both documents agree on
- Where they differ or contradict
- Information present in one but absent from the other
If either `read` call fails, report which path was not found and stop.
