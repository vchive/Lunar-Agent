# Data model: one-shot artifact envelope

```json
{
  "text": "Routes generated and checked.",
  "artifacts": [
    {"path": "output/routes.csv", "content": "order_id,route_id\n1,r1\n"}
  ],
  "metadata": {"mode": "batch"}
}
```

`text` is the normal conversational result. Each artifact `path` is relative to the private
attempt workspace and each `content` value is UTF-8 text. The envelope accepts at most 32 entries
and 256 KiB of aggregate content. Metadata is optional, bounded string-to-string information and
does not replace the ledger's SHA-256 records.
