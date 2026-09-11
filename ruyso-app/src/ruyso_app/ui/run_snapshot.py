"""
Detecting which pipeline steps have been changed since the last
successful run, so the Table tab can flag a shown table as stale
("· modified") rather than pretending it still reflects the pipeline.

The logic itself moved to :mod:`ruyso_app.engine.signatures`, where the
scheduler also uses it to decide which nodes it can skip re-running
(:mod:`ruyso_app.engine.run_cache`) -- the two questions turned out to
be the same one asked at different times. This module stays as the UI's
name for it, so the tabs and their tests keep importing from where they
always did.
"""

from __future__ import annotations

from ruyso_app.engine.signatures import modified_since_run, pipeline_signatures

__all__ = ["modified_since_run", "pipeline_signatures"]
