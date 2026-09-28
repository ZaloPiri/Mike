from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from concurrent.futures import ThreadPoolExecutor, TimeoutError
from collections.abc import Callable

from mike_app.runtime.delivery_outbox import DeliveryOutboxEntry
from mike_app.runtime.delivery_receipt import DeliveryReceipt


class AdapterOutcome(str, Enum):
    SUCCESS = "success"
    TRANSIENT = "transient"
    PERMANENT = "permanent"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class AdapterResult:
    outcome: AdapterOutcome
    receipt: DeliveryReceipt | None = None
    error: str | None = None


class DevelopmentAdapter:
    name = "development"
    timeout_seconds = 10

    def __init__(
        self,
        outcome: AdapterOutcome = AdapterOutcome.SUCCESS,
        *,
        timeout_seconds: float | None = None,
        operation: Callable[[], AdapterResult] | None = None,
    ) -> None:
        if not isinstance(outcome, AdapterOutcome):
            raise TypeError("outcome must be an AdapterOutcome")
        self._outcome = outcome
        self.timeout_seconds = self.__class__.timeout_seconds if timeout_seconds is None else timeout_seconds
        if self.timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        self._operation = operation

    def process(self, entry: DeliveryOutboxEntry, receipt: DeliveryReceipt | None = None) -> AdapterResult:
        if entry.channel != self.name:
            return AdapterResult(AdapterOutcome.PERMANENT, error="unsupported development channel")
        if receipt is not None:
            return AdapterResult(AdapterOutcome.SUCCESS, receipt=receipt)
        def invoke() -> AdapterResult:
            if self._operation is not None:
                return self._operation()
            if self._outcome is AdapterOutcome.SUCCESS:
                return AdapterResult(AdapterOutcome.SUCCESS)
            return AdapterResult(self._outcome, error=f"development adapter {self._outcome.value}")
        executor = ThreadPoolExecutor(max_workers=1)
        future = executor.submit(invoke)
        try:
            return future.result(timeout=self.timeout_seconds)
        except TimeoutError:
            future.cancel()
            return AdapterResult(AdapterOutcome.UNKNOWN, error="development adapter timeout")
        finally:
            executor.shutdown(wait=False, cancel_futures=True)
