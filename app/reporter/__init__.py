"""Reporter: fetches news, dedupes it, clusters sources into stories.

Node: context/nodes/reporter.md
"""

from app.reporter.cluster import cluster_stories, embed_pending_sources
from app.reporter.ingest import IngestReport, ingest_feeds, insert_new_sources

__all__ = [
    "IngestReport",
    "cluster_stories",
    "embed_pending_sources",
    "ingest_feeds",
    "insert_new_sources",
]
