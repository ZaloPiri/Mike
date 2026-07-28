from datetime import datetime, timedelta, timezone
import json
import uuid

from mike_app.runtime.event import Event


def test_event_create_generates_uuid_and_defaults_payload() -> None:
    event = Event.create(tenant_id="tenant-1", event_type="test.event")

    assert isinstance(event.event_id, uuid.UUID)
    assert event.tenant_id == "tenant-1"
    assert event.event_type == "test.event"
    assert event.schema_version == 1


def test_event_id_serializes_to_string_in_to_dict() -> None:
    event = Event.create(tenant_id="tenant-1", event_type="test.event")
    result = event.to_dict()

    assert isinstance(result["event_id"], str)
    assert result["event_id"] == str(event.event_id)


def test_event_occurred_at_is_utc_timezone_aware() -> None:
    event = Event.create(tenant_id="tenant-1", event_type="test.event")

    assert event.occurred_at.tzinfo is not None
    assert event.occurred_at.utcoffset() == timezone.utc.utcoffset(event.occurred_at)


def test_event_rejects_whitespace_only_tenant_id() -> None:
    try:
        Event.create(tenant_id="   ", event_type="test.event")
    except ValueError as exc:
        assert str(exc) == "tenant_id is required and must be non-empty"
    else:
        raise AssertionError("Expected ValueError for whitespace-only tenant_id")


def test_event_rejects_whitespace_only_event_type() -> None:
    try:
        Event.create(tenant_id="tenant-1", event_type="   ")
    except ValueError as exc:
        assert str(exc) == "event_type is required and must be non-empty"
    else:
        raise AssertionError("Expected ValueError for whitespace-only event_type")


def test_event_is_immutable() -> None:
    event = Event.create(tenant_id="tenant-1", event_type="test.event")

    try:
        event.tenant_id = "other"
    except AttributeError:
        pass
    else:
        raise AssertionError("Expected AttributeError for immutable Event")


def test_event_payload_deeply_immutable_top_level() -> None:
    event = Event.create(tenant_id="tenant-1", event_type="test.event", payload={"a": 1})

    try:
        event.payload["b"] = 2
    except TypeError:
        pass
    else:
        raise AssertionError("Expected TypeError for top-level payload mutation")


def test_event_payload_deeply_immutable_nested_dict() -> None:
    event = Event.create(
        tenant_id="tenant-1",
        event_type="test.event",
        payload={"a": {"b": 1}},
    )

    try:
        event.payload["a"]["b"] = 2
    except TypeError:
        pass
    else:
        raise AssertionError("Expected TypeError for nested dict payload mutation")


def test_event_payload_deeply_immutable_nested_list() -> None:
    event = Event.create(
        tenant_id="tenant-1",
        event_type="test.event",
        payload={"a": [1, 2, 3]},
    )

    try:
        event.payload["a"][0] = 9
    except TypeError:
        pass
    else:
        raise AssertionError("Expected TypeError for nested list payload mutation")


def test_mutating_original_payload_does_not_change_event() -> None:
    original = {"a": [1, 2]}
    event = Event.create(tenant_id="tenant-1", event_type="test.event", payload=original)

    original["a"][0] = 9
    assert event.to_dict()["payload"] == {"a": [1, 2]}


def test_mutating_to_dict_result_does_not_change_event() -> None:
    event = Event.create(tenant_id="tenant-1", event_type="test.event", payload={"a": [1, 2]})
    result = event.to_dict()

    result["payload"]["a"][0] = 9
    assert event.to_dict()["payload"] == {"a": [1, 2]}


def test_event_optional_correlation_and_causation_ids() -> None:
    event = Event.create(
        tenant_id="tenant-1",
        event_type="test.event",
        correlation_id="corr-1",
        causation_id="cause-1",
    )

    assert event.correlation_id == "corr-1"
    assert event.causation_id == "cause-1"


def test_event_positive_schema_version_validation() -> None:
    try:
        Event.create(tenant_id="tenant-1", event_type="test.event", schema_version=0)
    except ValueError as exc:
        assert str(exc) == "schema_version must be a positive integer"
    else:
        raise AssertionError("Expected ValueError for invalid schema_version")


def test_event_schema_version_bool_is_rejected() -> None:
    try:
        Event.create(tenant_id="tenant-1", event_type="test.event", schema_version=True)
    except ValueError as exc:
        assert str(exc) == "schema_version must be a positive integer"
    else:
        raise AssertionError("Expected ValueError for bool schema_version")


def test_event_schema_version_non_int_is_rejected() -> None:
    try:
        Event.create(tenant_id="tenant-1", event_type="test.event", schema_version=1.5)
    except ValueError as exc:
        assert str(exc) == "schema_version must be a positive integer"
    else:
        raise AssertionError("Expected ValueError for non-int schema_version")


def test_event_timezone_aware_non_utc_is_normalized_to_utc() -> None:
    source_time = datetime(2026, 7, 28, 12, 0, tzinfo=timezone(timedelta(hours=2)))
    event = Event(
        event_id=uuid.uuid4(),
        tenant_id="tenant-1",
        event_type="test.event",
        occurred_at=source_time,
        payload={"a": 1},
    )

    assert event.occurred_at.tzinfo is not None
    assert event.occurred_at.utcoffset() == timezone.utc.utcoffset(event.occurred_at)
    assert event.occurred_at.isoformat().endswith("+00:00")


def test_event_rejects_naive_datetime() -> None:
    try:
        Event(
            event_id=uuid.uuid4(),
            tenant_id="tenant-1",
            event_type="test.event",
            occurred_at=datetime(2026, 7, 28, 12, 0),
            payload={"a": 1},
        )
    except ValueError as exc:
        assert str(exc) == "occurred_at must be timezone-aware"
    else:
        raise AssertionError("Expected ValueError for naive datetime")


def test_event_rejects_non_json_compatible_payload() -> None:
    try:
        Event.create(tenant_id="tenant-1", event_type="test.event", payload=object())
    except ValueError as exc:
        assert str(exc) == "payload must be JSON-compatible"
    else:
        raise AssertionError("Expected ValueError for non-JSON-compatible payload")


def test_event_to_dict_output_is_json_serializable() -> None:
    event = Event.create(tenant_id="tenant-1", event_type="test.event", payload={"a": [1, 2]})
    result = event.to_dict()

    json.dumps(result)
