# Chat templates used by catalog entries

- `qwen3-nothink.jinja`: Qwen3's own template (copied from the tokenizer_config of Qwen/Qwen3-8B on 2026-10-21) with `enable_thinking` defaulting to false, so a server started with `--chat-template` answers without a thinking block. The thinking variant is the vendor default.
