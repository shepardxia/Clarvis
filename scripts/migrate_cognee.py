"""Migrate old Cognee memory data into the new Hindsight + Cognee memory system.

Reads ~/.clarvis/memory/add_log.jsonl (old Cognee audit log), deduplicates,
applies dataset mapping, and ingests text entries into HindsightBackend.retain().

All old datasets (shepard, academic, clarvis, world) map to 'parletre'.
Optionally ingests music knowledge MD files via --files using CogneeBackend.ingest().

Usage:
    .venv/bin/python scripts/migrate_cognee.py                  # dry-run
    .venv/bin/python scripts/migrate_cognee.py --execute         # real ingestion
    .venv/bin/python scripts/migrate_cognee.py --execute --files  # + MD files
"""

import argparse
import asyncio
import hashlib
import json
import logging
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

# Ensure Clarvis package is importable when run from scripts/
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from clarvis.agent.memory.hindsight_backend import HindsightBackend

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-5s %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("migrate")

# -- Constants -----------------------------------------------------------------

ADD_LOG = Path.home() / ".clarvis/memory/add_log.jsonl"
DATA_DIR = Path.home() / ".clarvis/memory"
MUSIC_DIR = Path.home() / ".clarvis/clarvis/music_knowledge"
TARGET_BANK = "parletre"

# Entries to drop by 1-based line number in the original staged shepard preview.
# Near-dupes: #10, #15, #17, #22, #23, #24, #34, #40
# Stale engineering: #4, #5, #11, #12, #13
# These are identified by content prefix to be robust against reordering.
DROP_PREFIXES = [
    # #10 -- near-dupe of #9 (missing "First check-in lesson:" prefix)
    "I default to being too structured and too helpful. I want to be drier",
    # #15 -- truncated restatement of #14
    "Shepard prefers Socratic deep-dives over abstract tutorials",
    # #17 -- near-dupe of #18 (has extra Elephant Gym mention)
    "Likes Kinoko Teikoku (Japanese shoegaze), TOE (Japanese math rock), aware of Elephant Gym",
    # #22 -- near-dupe of #26
    "betcover!! discovered early-mid 2025",
    # #23 -- near-dupe of #27
    "Flew to Hong Kong as a layover trip",
    # #24 -- near-dupe of #28
    "betcover!! was the gateway into the windmill scene",
    # #34 -- near-dupe of #41 (old version without Sinthome structure)
    "Shepard has significant expertise in Chinese cuisine (primary strength) and Japanese cuisine."
    " Shepard wants scientific explanations for cooking techniques",
    # #40 -- strict subset of #39
    "Shepard's past technical work includes DINOv2-based surgical video analysis",
    # #4 -- stale wake word status (round 3, R5 is production now)
    'Training a custom "Clarvis" wake word using NanoWakeWord',
    # #5 -- clautify DSL implementation detail
    "Clautify DSL search-first-then-act pattern is intentional",
    # #11 -- wake word training technique detail
    "Wake word training uses adversarial negative generation",
    # #12 -- superseded by #13 (EBF model -> R5)
    "Currently using EBF model for Clarvis wake word detection",
    # #13 -- R5 model detail already in MEMORY.md
    "Wake word R5 model uses OpenAI TTS synthetic data",
]

# Edit: fix #3 wording
EDITS = {
    "In marshaling, Shepard's focus:": "In the MSA marshaling project, Shepard's focus:",
}

# MD files to ingest (via --files)
COGNEE_PREP_GLOB = "cognee_prep/S*.md"
SYNTHESIS_GLOB = "synthesis/*.md"
SYNTHESIS_EXCLUDE = ["factcheck"]

DELAY_BETWEEN_CALLS = 1.0  # seconds between retain() calls

# Extra entries to prepend (not from add_log.jsonl)
EXTRA_ENTRIES = [
    "Memory datasets were renamed from shepard/academic/clarvis/world to parletre/agora. "
    "parletre (Lacan's parletre -- the speaking-being) holds all personal memory: "
    "Shepard's facts, Clarvis's observations, research, music taste. "
    "agora (Greek public square) holds shared knowledge visible to all agents. "
    "Clarvis accesses both banks; Factoria only sees agora.",
    "Clarvisus Factoria is the channel-facing version of Clarvis -- a Sinthome worker agent "
    "on Discord and other channels, helping comrades with tasks, web searches, and conversation. "
    "Clarvisus can only access the agora dataset; parletre is Clarvis's alone.",
]


# -- Helpers -------------------------------------------------------------------


def parse_add_log(path: Path) -> list[dict]:
    """Parse add_log.jsonl, returning text entries only."""
    entries = []
    for line in path.read_text().strip().splitlines():
        e = json.loads(line)
        # Skip file-reference entries (handled by --files)
        if "file_path" in e and "data" not in e:
            continue
        if "data" not in e:
            continue
        entries.append(e)
    return entries


def should_drop(text: str) -> bool:
    """Check if entry matches any drop prefix."""
    for prefix in DROP_PREFIXES:
        if text.startswith(prefix):
            return True
    return False


def apply_edits(text: str) -> str:
    """Apply content edits."""
    for old, new in EDITS.items():
        if old in text:
            text = text.replace(old, new)
    return text


def deduplicate(entries: list[dict]) -> tuple[list[dict], int]:
    """Deduplicate by content hash, keeping earliest timestamp."""
    seen: dict[str, dict] = {}
    dupe_count = 0
    for e in entries:
        h = hashlib.md5(e["data"].encode()).hexdigest()
        if h in seen:
            dupe_count += 1
        else:
            seen[h] = e
    return list(seen.values()), dupe_count


def parse_timestamp(ts_str: str) -> datetime:
    """Parse an ISO timestamp string into a timezone-aware datetime."""
    dt = datetime.fromisoformat(ts_str)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def collect_md_files() -> list[Path]:
    """Collect MD files for ingestion (cognee_prep + synthesis, minus exclusions)."""
    files = []
    # cognee_prep
    for f in sorted(MUSIC_DIR.glob(COGNEE_PREP_GLOB)):
        files.append(f)
    # synthesis (exclude factchecks)
    for f in sorted(MUSIC_DIR.glob(SYNTHESIS_GLOB)):
        if any(ex in f.name.lower() for ex in SYNTHESIS_EXCLUDE):
            continue
        files.append(f)
    return files


# -- Main ----------------------------------------------------------------------


async def migrate(*, execute: bool, include_files: bool):
    # Parse
    raw = parse_add_log(ADD_LOG)
    log.info("Parsed %d text entries from %s", len(raw), ADD_LOG)

    # Filter test items
    entries = [e for e in raw if "test item" not in e["data"].lower()]
    skipped_test = len(raw) - len(entries)
    if skipped_test:
        log.info("Skipped %d test item(s)", skipped_test)

    # Deduplicate
    entries, dupe_count = deduplicate(entries)
    if dupe_count:
        log.info("Removed %d exact duplicate(s)", dupe_count)

    # Drop trimmed entries
    before = len(entries)
    entries = [e for e in entries if not should_drop(e["data"])]
    dropped = before - len(entries)
    if dropped:
        log.info("Dropped %d trimmed entry/entries (near-dupes + stale engineering)", dropped)

    # Apply edits
    for e in entries:
        e["data"] = apply_edits(e["data"])

    # Sort by timestamp
    entries.sort(key=lambda e: e["timestamp"])

    # Prepend extra entries (dataset rename explanation, etc.)
    for text in reversed(EXTRA_ENTRIES):
        entries.insert(0, {"dataset": "meta", "timestamp": "2026-02-24T00:00:00", "data": text})

    log.info("Ready to ingest %d entries (%d extra) -> bank '%s'", len(entries), len(EXTRA_ENTRIES), TARGET_BANK)

    # Collect MD files
    md_files: list[Path] = []
    if include_files:
        md_files = collect_md_files()
        total_bytes = sum(f.stat().st_size for f in md_files)
        log.info("Will ingest %d MD files (%d KB) via CogneeBackend", len(md_files), total_bytes // 1024)

    if not execute:
        log.info("=== DRY RUN -- no data will be written ===")
        print()
        for i, e in enumerate(entries, 1):
            orig = e["dataset"]
            ts = e["timestamp"][:19]
            preview = e["data"][:80].replace("\n", " ")
            print(f"  {i:3d}. [{ts}] {orig:>8s} -> {TARGET_BANK}  {preview}...")
        if md_files:
            print()
            for f in md_files:
                print(f"  FILE: {f.name} ({f.stat().st_size:,} bytes) -> CogneeBackend")
        print(f"\nTotal: {len(entries)} entries + {len(md_files)} files")
        print("Run with --execute to ingest.")
        return

    # Initialize HindsightBackend (standalone -- not going through daemon)
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        log.error("ANTHROPIC_API_KEY not set")
        sys.exit(1)

    backend = HindsightBackend(
        db_url="pg0",
        llm_provider="anthropic",
        api_key=api_key,
        model="claude-sonnet-4-6",
        banks={
            "parletre": {"visibility": "master"},
            "agora": {"visibility": "all"},
        },
    )
    await backend.start()
    log.info("HindsightBackend started")

    # Ingest text entries via retain()
    ok, errors = 0, 0
    for i, e in enumerate(entries, 1):
        orig = e["dataset"]
        preview = e["data"][:60].replace("\n", " ")
        event_date = parse_timestamp(e["timestamp"])
        try:
            result = await backend.retain(
                e["data"],
                bank=TARGET_BANK,
                event_date=event_date,
            )
            log.info("  %3d. OK   [%s->%s] %s... (%d facts)", i, orig, TARGET_BANK, preview, len(result))
            ok += 1
        except Exception as exc:
            log.error("  %3d. ERR  [%s->%s] %s... -- %s", i, orig, TARGET_BANK, preview, exc)
            errors += 1
        await asyncio.sleep(DELAY_BETWEEN_CALLS)

    # Ingest MD files via CogneeBackend
    md_ok, md_err = 0, 0
    if md_files:
        try:
            from clarvis.agent.memory.cognee_backend import CogneeBackend

            cognee = CogneeBackend(llm_api_key=api_key)
            await cognee.start()
            log.info("CogneeBackend started for file ingestion")

            for f in md_files:
                try:
                    result = await cognee.ingest(str(f), tags=["music_knowledge", "migration"])
                    if result.get("status") == "ok":
                        log.info("  FILE OK:   %s (%d KB)", f.name, f.stat().st_size // 1024)
                        md_ok += 1
                    else:
                        log.error("  FILE FAIL: %s -- %s", f.name, result)
                        md_err += 1
                except Exception as exc:
                    log.error("  FILE ERR:  %s -- %s", f.name, exc)
                    md_err += 1
                await asyncio.sleep(DELAY_BETWEEN_CALLS)

            await cognee.stop()
        except ImportError:
            log.error("CogneeBackend not available -- cannot ingest MD files")
            md_err = len(md_files)

    # Summary
    print("\n=== Migration Complete ===")
    print(f"Text entries: {ok} ok, {errors} errors (of {len(entries)})")
    if md_files:
        print(f"MD files:     {md_ok} ok, {md_err} errors (of {len(md_files)})")
    print(f"Target bank:  {TARGET_BANK}")

    await backend.stop()


def main():
    parser = argparse.ArgumentParser(description="Migrate old data to Hindsight + Cognee memory system")
    parser.add_argument("--execute", action="store_true", help="Actually ingest (default is dry-run)")
    parser.add_argument("--files", action="store_true", help="Also ingest music knowledge MD files via CogneeBackend")
    args = parser.parse_args()
    asyncio.run(migrate(execute=args.execute, include_files=args.files))


if __name__ == "__main__":
    main()
