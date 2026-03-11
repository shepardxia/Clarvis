# ctools — Factoria Command Reference

Run commands via `ctools <command> '<json params>'` in bash.

## Memory

```bash
ctools recall '{"query": "topic", "bank": "agora"}'
ctools remember '{"text": "fact text", "bank": "agora"}'
ctools update_fact '{"fact_id": "...", "content": "new text", "bank": "agora"}'
ctools forget '{"fact_id": "..."}'
ctools list_facts '{"bank": "agora", "limit": 50}'
ctools stats '{"bank": "agora"}'
```

## Mental Models

```bash
ctools list_models '{"bank": "agora"}'
ctools search_models '{"query": "topic", "bank": "agora"}'
ctools create_model '{"name": "model name", "content": "...", "source_query": "...", "bank": "agora"}'
ctools update_model '{"id": "...", "content": "...", "bank": "agora"}'
ctools delete_model '{"id": "...", "bank": "agora"}'
```

## Observations & Consolidation

```bash
ctools list_observations '{"bank": "agora"}'
ctools get_observation '{"id": "...", "bank": "agora"}'
ctools unconsolidated '{"bank": "agora"}'
ctools related_observations '{"fact_ids": ["..."], "bank": "agora"}'
ctools consolidate '{"decisions": [...], "fact_ids_to_mark": [...], "bank": "agora"}'
ctools stale_models '{"bank": "agora"}'
```

## Directives

```bash
ctools list_directives '{"bank": "agora"}'
ctools create_directive '{"name": "...", "content": "...", "bank": "agora"}'
ctools update_directive '{"directive_id": "...", "content": "...", "bank": "agora"}'
ctools delete_directive '{"directive_id": "...", "bank": "agora"}'
```

## Bank Profile

```bash
ctools get_profile '{"bank": "agora"}'
ctools set_mission '{"mission": "...", "bank": "agora"}'
ctools set_disposition '{"bank": "agora", "skepticism": 5}'
```

## Knowledge Graph

```bash
ctools knowledge '{"query": "topic"}'
ctools ingest '{"content_or_path": "text or /path/to/file"}'
ctools entities '{"type_name": "Person"}'
ctools relations '{"entity_id": "..."}'
ctools update_entity '{"entity_id": "...", "fields": {"name": "new"}}'
ctools merge_entities '{"entity_ids": ["id1", "id2"]}'
ctools delete_entity '{"node_id": "..."}'
ctools build_communities '{}'
```

## Spotify & Timers

```bash
ctools spotify '{"command": "play jazz volume 70"}'
ctools timer '{"action": "set", "name": "reminder", "duration": "30m"}'
ctools timer '{"action": "list"}'
ctools timer '{"action": "cancel", "name": "reminder"}'
```

## Channels

```bash
ctools send_message '{"channel": "discord", "chat_id": "...", "content": "hello"}'
ctools get_channels '{}'
```

## Media

When users send attachments (images, files) through Discord, they are downloaded to `~/.clarvis/media/`. Files are named `{attachment_id}_{filename}`. You can read or view these files using their full path when referenced in messages.

## Notes

- Always use `bank="agora"` for memory commands. Factoria has agora access only.
- `fact_type` options: `world`, `experience`, `opinion`.
- Timer `duration` accepts: `30s`, `5m`, `2h`, `1d`.
