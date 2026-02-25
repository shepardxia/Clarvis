# Ingest Skill

You are ingesting a document into the knowledge base.

## Process

1. Call knowledge_ingest with the provided path or content
2. After ingestion, check what was extracted: call knowledge_entities and knowledge_facts
3. Look for obvious issues:
   - Duplicate entities that should be merged (call knowledge_merge)
   - Incorrect entity types (call knowledge_update)
   - Missing relationships that are obvious from context
4. Report what was ingested: new entities, new relationships, any corrections made

## Guidelines

- Tag documents appropriately at ingestion time for later retrieval scoping
- For music-related documents, expect Band, Genre, Person, and Event entities
- For research documents, expect Person, Organization, Project, and Concept entities
- After merging duplicates, verify the survivor entity has the correct properties
- Report a summary:
  ```
  Ingested: docs/music/shoegaze-guide.md
  Entities: 8 new (3 Band, 2 Person, 2 Genre, 1 Event)
  Relationships: 12 new
  Corrections: merged 2 duplicate Band entities ("MBV" + "My Bloody Valentine")
  ```
