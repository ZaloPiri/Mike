from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from mike_app.runtime.development_adapter import AdapterOutcome, DevelopmentAdapter
from mike_app.runtime.delivery_outbox import DeliveryOutboxEntry
from mike_app.runtime.delivery_receipt import DeliveryReceipt, ReceiptConflictError, snapshot_hash
from mike_app.runtime.episode_journal import EpisodeJournal


@dataclass(frozen=True, slots=True)
class RunOnceResult:
    outcome: str
    tenant_id: str
    outbox_id: uuid.UUID | None = None
    status: str | None = None
    error: str | None = None


class DeliveryProcessor:
    lease_seconds = 60
    max_attempts = 3
    adapter_timeout_seconds = 10

    def __init__(self, journal: EpisodeJournal, adapter: DevelopmentAdapter | None = None, clock=None) -> None:
        self._journal = journal
        self._adapter = adapter or DevelopmentAdapter()
        self._clock = clock or (lambda: datetime.now(timezone.utc))

    def run_once(self, tenant_id: str) -> RunOnceResult:
        now = self._clock().astimezone(timezone.utc)
        claimed = self._journal.claim_one_delivery(tenant_id, now, self.lease_seconds)
        if claimed is None:
            return RunOnceResult("no_work", tenant_id)
        receipt = self._journal.get_delivery_receipt(tenant_id, claimed.idempotency_key)
        if receipt is not None and not receipt.is_compatible(claimed):
            failed = self._journal.fail_delivery(tenant_id, claimed.outbox_id, claimed.claim_token, now, "receipt idempotency conflict", None)
            return RunOnceResult("failed", tenant_id, claimed.outbox_id, failed.status, failed.last_error)
        if receipt is not None:
            completed = self._journal.finalize_delivery(tenant_id, claimed.outbox_id, claimed.claim_token, receipt)
            return RunOnceResult("completed", tenant_id, claimed.outbox_id, completed.status)
        attempt = self._journal.start_adapter_attempt(tenant_id, claimed.outbox_id, claimed.claim_token, now)
        result = self._adapter.process(attempt)
        if result.outcome is AdapterOutcome.SUCCESS:
            receipt = DeliveryReceipt(uuid.uuid4(), tenant_id, attempt.outbox_id, attempt.delivery_request_event_id, attempt.idempotency_key, snapshot_hash(attempt), self._adapter.name, now)
            try:
                self._journal.save_delivery_receipt(receipt, attempt.claim_token)
            except ReceiptConflictError:
                existing = self._journal.get_delivery_receipt(tenant_id, attempt.idempotency_key)
                if existing is None or not existing.is_compatible(attempt):
                    failed = self._journal.fail_delivery(tenant_id, attempt.outbox_id, attempt.claim_token, now, "receipt idempotency conflict", None)
                    return RunOnceResult("failed", tenant_id, attempt.outbox_id, failed.status, failed.last_error)
                receipt = existing
            completed = self._journal.finalize_delivery(tenant_id, attempt.outbox_id, attempt.claim_token, receipt)
            return RunOnceResult("completed", tenant_id, attempt.outbox_id, completed.status)
        if result.outcome is AdapterOutcome.TRANSIENT or result.outcome is AdapterOutcome.UNKNOWN:
            retry_at = now + timedelta(seconds=30 if attempt.adapter_attempt_count == 1 else 120) if attempt.adapter_attempt_count < self.max_attempts else None
            failed = self._journal.fail_delivery(tenant_id, attempt.outbox_id, attempt.claim_token, now, result.error or "adapter failure", retry_at)
            return RunOnceResult("rescheduled" if failed.status == "pending" else "failed", tenant_id, attempt.outbox_id, failed.status, failed.last_error)
        failed = self._journal.fail_delivery(tenant_id, attempt.outbox_id, attempt.claim_token, now, result.error or "permanent adapter failure", None)
        return RunOnceResult("failed", tenant_id, attempt.outbox_id, failed.status, failed.last_error)
