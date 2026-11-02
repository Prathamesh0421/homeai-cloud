"""Re-export of the denylist repository for clarity."""

from app.services.token_denylist import is_revoked, list_revoked_since, purge_expired, revoke

__all__ = ["is_revoked", "list_revoked_since", "purge_expired", "revoke"]
