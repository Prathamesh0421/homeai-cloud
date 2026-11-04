"""ORM table definitions for schema ``c3``.

Tables (ml_models, model_evaluations, integrity_reports, data_dictionary_versions)
land in C3-02 (Phase 3). This module exists now so ``app.models`` can import it and
Alembic has a stable target; it currently registers no tables on ``Base.metadata``.
"""

from __future__ import annotations

from app.models import Base  # noqa: F401  (import kept for when tables are added)
