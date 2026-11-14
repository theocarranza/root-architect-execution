"""Narrow offline service facade.

No proven host identity boundary exists yet.  Therefore every privileged
operation fails closed instead of treating caller supplied fields as identity.
"""

from runtime_store import RuntimeStore


class RuntimeService:
    def __init__(self, state_root):
        self.store = RuntimeStore(state_root)

    @staticmethod
    def _unsupported():
        return {"status": "unsupported_boundary", "capability": "authenticated_controller_identity"}

    def privileged(self, supplied_context=None):
        return self._unsupported()

    def capture(self, supplied_context=None):
        return self._unsupported()
