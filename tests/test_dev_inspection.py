from datetime import datetime, timezone
import uuid

import pytest
from fastapi.testclient import TestClient

from mike_app.main import app
from mike_app.runtime.episode import CognitiveEpisode


client = TestClient(app)


def unique_tenant(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4()}"


def create_message(tenant_id: str, text: str = "hello") -> dict[str, object]:
    response = client.post(
        "/dev/messages",
        json={"tenant_id": tenant_id, "text": text},
    )
    assert response.status_code == 201
    return response.json()


def test_unknown_tenant_event_and_episode_lists_are_empty() -> None:
    tenant_id = unique_tenant("unknown")

    events_response = client.get(f"/dev/tenants/{tenant_id}/events")
    episodes_response = client.get(
        f"/dev/tenants/{tenant_id}/episodes"
    )

    assert events_response.status_code == 200
    assert events_response.json() == []
    assert episodes_response.status_code == 200
    assert episodes_response.json() == []


def test_events_endpoint_returns_safe_events_in_insertion_order() -> None:
    tenant_id = unique_tenant("events")
    text = "  preserved text  "
    message = create_message(tenant_id, text)

    response = client.get(f"/dev/tenants/{tenant_id}/events")

    assert response.status_code == 200
    events = response.json()
    assert len(events) == 2
    assert [event["event_type"] for event in events] == [
        "message.received",
        "message.accepted",
    ]
    assert events[0]["payload"] == {"text": text}
    assert events[1]["payload"] == {
        "source_event_id": events[0]["event_id"],
    }
    assert events[0]["event_id"] == message["event_id"]
    assert uuid.UUID(events[0]["event_id"])
    assert uuid.UUID(events[1]["event_id"])
    assert datetime.fromisoformat(events[0]["occurred_at"]).tzinfo is not None
    assert datetime.fromisoformat(events[1]["occurred_at"]).tzinfo is not None
    assert all(event["tenant_id"] == tenant_id for event in events)
    assert set(events[0]) == {
        "event_id",
        "tenant_id",
        "event_type",
        "payload",
        "occurred_at",
        "correlation_id",
        "schema_version",
    }


def test_event_reads_preserve_state_and_payload_is_a_safe_copy() -> None:
    tenant_id = unique_tenant("event-read")
    create_message(tenant_id, "original")
    event_count = app.state.event_store.total_count()
    episode_count = app.state.episode_store.total_count()

    first = client.get(f"/dev/tenants/{tenant_id}/events").json()
    first[0]["payload"]["text"] = "changed"
    second = client.get(f"/dev/tenants/{tenant_id}/events").json()

    assert second[0]["payload"] == {"text": "original"}
    assert app.state.event_store.total_count() == event_count
    assert app.state.episode_store.total_count() == episode_count


def test_event_list_preserves_tenant_isolation() -> None:
    first_tenant = unique_tenant("event-one")
    second_tenant = unique_tenant("event-two")
    create_message(first_tenant)
    create_message(second_tenant)

    events = client.get(
        f"/dev/tenants/{first_tenant}/events"
    ).json()

    assert len(events) == 2
    assert all(event["tenant_id"] == first_tenant for event in events)


def test_episode_summaries_preserve_insertion_order_and_state() -> None:
    tenant_id = unique_tenant("summaries")
    first = create_message(tenant_id, "first")
    second = create_message(tenant_id, "second")
    event_count = app.state.event_store.total_count()
    episode_count = app.state.episode_store.total_count()

    first_read = client.get(
        f"/dev/tenants/{tenant_id}/episodes"
    )
    second_read = client.get(
        f"/dev/tenants/{tenant_id}/episodes"
    )

    assert first_read.status_code == 200
    summaries = first_read.json()
    assert summaries == second_read.json()
    assert [summary["episode_id"] for summary in summaries] == [
        first["episode_id"],
        second["episode_id"],
    ]
    assert [summary["event_count"] for summary in summaries] == [2, 2]
    assert all(uuid.UUID(summary["episode_id"]) for summary in summaries)
    assert all(
        datetime.fromisoformat(summary["created_at"]).tzinfo is not None
        for summary in summaries
    )
    assert all(
        datetime.fromisoformat(summary["updated_at"]).tzinfo is not None
        for summary in summaries
    )
    assert app.state.event_store.total_count() == event_count
    assert app.state.episode_store.total_count() == episode_count


def test_episode_summaries_preserve_tenant_isolation() -> None:
    first_tenant = unique_tenant("summary-one")
    second_tenant = unique_tenant("summary-two")
    first = create_message(first_tenant)
    create_message(second_tenant)

    summaries = client.get(
        f"/dev/tenants/{first_tenant}/episodes"
    ).json()

    assert [summary["episode_id"] for summary in summaries] == [
        first["episode_id"],
    ]
    assert summaries[0]["tenant_id"] == first_tenant


def test_episode_detail_preserves_event_ids_and_event_order() -> None:
    tenant_id = unique_tenant("detail")
    message = create_message(tenant_id)

    response = client.get(
        f"/dev/tenants/{tenant_id}/episodes/{message['episode_id']}"
    )

    assert response.status_code == 200
    detail = response.json()
    assert detail["episode_id"] == message["episode_id"]
    assert len(detail["event_ids"]) == 2
    assert len(detail["events"]) == 2
    assert detail["event_ids"] == [
        event["event_id"] for event in detail["events"]
    ]
    assert [event["event_type"] for event in detail["events"]] == [
        "message.received",
        "message.accepted",
    ]
    assert all(
        event["tenant_id"] == tenant_id for event in detail["events"]
    )


def test_episode_detail_reads_do_not_mutate_stores() -> None:
    tenant_id = unique_tenant("detail-read")
    message = create_message(tenant_id)
    event_count = app.state.event_store.total_count()
    episode_count = app.state.episode_store.total_count()
    path = (
        f"/dev/tenants/{tenant_id}/episodes/{message['episode_id']}"
    )

    first = client.get(path)
    second = client.get(path)

    assert first.json() == second.json()
    assert app.state.event_store.total_count() == event_count
    assert app.state.episode_store.total_count() == episode_count


def test_unknown_and_cross_tenant_episode_details_return_same_404() -> None:
    owner_tenant = unique_tenant("owner")
    other_tenant = unique_tenant("other")
    message = create_message(owner_tenant)
    unknown_id = uuid.uuid4()

    unknown = client.get(
        f"/dev/tenants/{other_tenant}/episodes/{unknown_id}"
    )
    cross_tenant = client.get(
        f"/dev/tenants/{other_tenant}/episodes/{message['episode_id']}"
    )

    assert unknown.status_code == 404
    assert cross_tenant.status_code == 404
    assert unknown.json() == cross_tenant.json()
    assert owner_tenant not in str(cross_tenant.json())


def test_malformed_episode_uuid_uses_normal_validation_response() -> None:
    tenant_id = unique_tenant("malformed")

    response = client.get(
        f"/dev/tenants/{tenant_id}/episodes/not-a-uuid"
    )

    assert response.status_code == 422


@pytest.mark.parametrize(
    "path",
    [
        "/dev/tenants/%20%20/events",
        "/dev/tenants/%20%20/episodes",
        f"/dev/tenants/%20%20/episodes/{uuid.uuid4()}",
    ],
)
def test_whitespace_only_tenant_is_rejected(path: str) -> None:
    response = client.get(path)

    assert response.status_code == 422


def test_empty_tenant_path_does_not_match_routes() -> None:
    assert client.get("/dev/tenants//events").status_code == 404
    assert client.get("/dev/tenants//episodes").status_code == 404


def test_missing_referenced_event_raises_internal_consistency_error() -> None:
    tenant_id = unique_tenant("integrity")
    now = datetime.now(timezone.utc)
    episode = CognitiveEpisode(
        episode_id=uuid.uuid4(),
        tenant_id=tenant_id,
        created_at=now,
        updated_at=now,
        event_ids=(uuid.uuid4(),),
        correlation_id=None,
        schema_version=1,
    )
    app.state.episode_store.add(episode)

    with pytest.raises(RuntimeError, match="unavailable"):
        client.get(
            f"/dev/tenants/{tenant_id}/episodes/{episode.episode_id}"
        )


def test_no_inspection_mutation_methods_exist() -> None:
    tenant_id = unique_tenant("methods")
    episode_id = uuid.uuid4()

    assert client.post(
        f"/dev/tenants/{tenant_id}/events"
    ).status_code == 405
    assert client.delete(
        f"/dev/tenants/{tenant_id}/episodes"
    ).status_code == 405
    assert client.put(
        f"/dev/tenants/{tenant_id}/episodes/{episode_id}"
    ).status_code == 405


def test_existing_message_and_health_contracts_remain_unchanged() -> None:
    tenant_id = unique_tenant("contracts")

    message = client.post(
        "/dev/messages",
        json={"tenant_id": tenant_id, "text": "hello"},
    )
    health = client.get("/health")

    assert message.status_code == 201
    assert message.json()["event_type"] == "message.received"
    assert message.json()["tenant_id"] == tenant_id
    assert message.json()["dispatched"] is True
    assert health.status_code == 200
    assert health.json() == {
        "status": "ok",
        "service": "mike",
        "version": "0.1.0",
    }
