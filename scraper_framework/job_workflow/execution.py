"""Manual previews only. No network clients, accounts, or submission adapters.

A handoff is a repeatable read, not a submission or execution claim. The human
opens the URL and uses the exact material themselves; the UI subsequently calls
Repository.record_manual_submission with evidence. No function here sends.
"""
from __future__ import annotations

from .repository import Repository


def prepare_handoff(repository: Repository, job_id: int) -> dict:
    """Validate live manual_contact approval and return its exact local snapshot."""
    return repository.prepare_handoff(job_id)


def execute(repository: Repository, job_id: int, *, dry_run=False,
            enabled=False, adapter=None) -> dict:
    """External execution is unconditionally disabled, including opt-in flags.

    Only explicit dry_run=True without an adapter/enabled flag is supported.
    Future adapters must not be slipped into this local-only implementation.
    """
    if dry_run is not True or enabled is not False or adapter is not None:
        raise ValueError('External execution disabled; use manual handoff or dry_run=True')
    return prepare_handoff(repository, job_id)
