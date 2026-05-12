"""
Integration tests for Event Management System (Phase 5)
Run: pip install requests pytest && BASE_URL=http://localhost:8080 pytest test_api.py -v
"""

import requests
import pytest
import os
import time
import random
import string

BASE = os.getenv("BASE_URL", "http://localhost:8080")


def url(path):
    return f"{BASE}/api{path}"


def wait_for_services():
    for _ in range(30):
        try:
            r = requests.get(f"{BASE}/health", timeout=2)
            if r.status_code == 200:
                return True
        except Exception:
            pass
        time.sleep(2)
    return False


def register_user(role="attendee"):
    suffix = "".join(random.choices(string.ascii_lowercase, k=6))
    r = requests.post(
        url("/users/register"),
        json={
            "username": f"{role}_{suffix}",
            "email": f"{role}_{suffix}@test.com",
            "password": "Password123",
            "full_name": f"Test {role.title()}",
            "role": role,
        },
    )
    assert r.status_code == 200, f"Register failed: {r.text}"
    user = r.json()["user"]
    login = requests.post(
        url("/users/login"),
        json={"email": f"{role}_{suffix}@test.com", "password": "Password123"},
    )
    assert login.status_code == 200
    token = login.json()["token"]
    return user, token


@pytest.fixture(scope="session", autouse=True)
def check_services():
    assert wait_for_services(), "Services did not become healthy"


@pytest.fixture(scope="session")
def admin():
    return register_user("super_admin")


@pytest.fixture(scope="session")
def organizer():
    return register_user("organizer")


@pytest.fixture(scope="session")
def attendee():
    return register_user("attendee")


@pytest.fixture(scope="session")
def event(organizer):
    _, token = organizer
    r = requests.post(
        url("/events"),
        json={
            "title": "Test Conference",
            "description": "Integration test event",
            "event_type": "conference",
            "start_date": "2026-08-01T09:00:00",
            "end_date": "2026-08-01T18:00:00",
            "location": "Test Hall",
            "max_capacity": 50,
            "ticket_price": 10.0,
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 200, f"Create event failed: {r.text}"
    return r.json()["event"]


class TestHealthChecks:
    def test_gateway_health(self):
        r = requests.get(f"{BASE}/health")
        assert r.status_code == 200

    def test_user_service_health(self):
        r = requests.get(url("/users/health"))
        assert r.status_code == 200
        assert r.json()["status"] == "healthy"

    def test_event_service_health(self):
        r = requests.get(url("/events/health"))
        assert r.status_code == 200

    def test_registration_service_health(self):
        r = requests.get(url("/registrations/health"))
        assert r.status_code == 200
        data = r.json()
        assert "circuit_breaker" in data
        assert data["circuit_breaker"]["state"] == "closed"

    def test_notification_service_health(self):
        r = requests.get(url("/notifications/health"))
        assert r.status_code == 200


class TestUserAuth:
    def test_register_success(self, attendee):
        user, _ = attendee
        assert "id" in user
        assert user["role"] == "attendee"

    def test_register_duplicate_fails(self, attendee):
        user, _ = attendee
        r = requests.post(
            url("/users/register"),
            json={
                "username": user["username"],
                "email": user["email"],
                "password": "Password123",
                "full_name": "Dup",
            },
        )
        assert r.status_code == 400

    def test_login_success(self, attendee):
        _, token = attendee
        assert token

    def test_login_wrong_password(self, attendee):
        user, _ = attendee
        r = requests.post(
            url("/users/login"),
            json={"email": user["email"], "password": "wrong"},
        )
        assert r.status_code == 401

    def test_get_me(self, attendee):
        user, token = attendee
        r = requests.get(url("/users/me"), headers={"Authorization": f"Bearer {token}"})
        assert r.status_code == 200
        assert r.json()["id"] == user["id"]

    def test_invalid_token_rejected(self):
        r = requests.get(
            url("/users/me"), headers={"Authorization": "Bearer invalid.token.here"}
        )
        assert r.status_code == 401

    def test_no_token_rejected(self):
        r = requests.get(url("/users/me"))
        assert r.status_code in (401, 403)


class TestRBAC:
    def test_attendant_cannot_create_event(self, attendee):
        _, token = attendee
        r = requests.post(
            url("/events"),
            json={
                "title": "Unauthorized",
                "description": "Should fail",
                "event_type": "conference",
                "start_date": "2026-08-01T09:00:00",
                "end_date": "2026-08-01T18:00:00",
                "location": "Nowhere",
                "max_capacity": 10,
            },
            headers={"Authorization": f"Bearer {token}"},
        )
        assert r.status_code == 403

    def test_organizer_can_create_event(self, organizer):
        user, token = organizer
        r = requests.post(
            url("/events"),
            json={
                "title": "Organizer Event",
                "description": "Created by organizer",
                "event_type": "workshop",
                "start_date": "2026-09-01T09:00:00",
                "end_date": "2026-09-01T18:00:00",
                "location": "Workshop Room",
                "max_capacity": 20,
            },
            headers={"Authorization": f"Bearer {token}"},
        )
        assert r.status_code == 200

    def test_admin_can_update_role(self, admin, attendee):
        _, admin_token = admin
        user, _ = attendee
        r = requests.put(
            url(f"/users/{user['id']}/role"),
            json={"role": "organizer"},
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert r.status_code == 200

    def test_attendant_cannot_update_role(self, attendee, organizer):
        _, token = attendee
        user, _ = organizer
        r = requests.put(
            url(f"/users/{user['id']}/role"),
            json={"role": "super_admin"},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert r.status_code == 403


class TestInputValidation:
    def test_short_password_rejected(self):
        r = requests.post(
            url("/users/register"),
            json={
                "username": "shortpw",
                "email": "short@test.com",
                "password": "short",
                "full_name": "Test",
            },
        )
        assert r.status_code == 422

    def test_invalid_email_rejected(self):
        r = requests.post(
            url("/users/register"),
            json={
                "username": "bademail",
                "email": "not-an-email",
                "password": "Password123",
                "full_name": "Test",
            },
        )
        assert r.status_code == 422

    def test_invalid_role_rejected(self):
        r = requests.post(
            url("/users/register"),
            json={
                "username": "badrole",
                "email": "badrole@test.com",
                "password": "Password123",
                "full_name": "Test",
                "role": "admin",
            },
        )
        assert r.status_code == 422

    def test_invalid_payment_method_rejected(self, attendee, event):
        _, token = attendee
        r = requests.post(
            url("/registrations"),
            json={"event_id": event["id"], "payment_method": "bitcoin"},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert r.status_code == 422


class TestEventCRUD:
    def test_create_event(self, event):
        assert "id" in event
        assert event["version"] == 1

    def test_list_events_paginated(self, attendee):
        _, token = attendee
        r = requests.get(
            url("/events?page=1&page_size=2"),
            headers={"Authorization": f"Bearer {token}"},
        )
        assert r.status_code == 200
        data = r.json()
        assert "events" in data
        assert "total" in data
        assert "page" in data
        assert "total_pages" in data
        assert len(data["events"]) <= 2

    def test_get_event(self, event, attendee):
        _, token = attendee
        r = requests.get(
            url(f"/events/{event['id']}"),
            headers={"Authorization": f"Bearer {token}"},
        )
        assert r.status_code == 200
        assert r.json()["id"] == event["id"]

    def test_get_nonexistent_event(self, attendee):
        _, token = attendee
        r = requests.get(
            url("/events/99999"),
            headers={"Authorization": f"Bearer {token}"},
        )
        assert r.status_code == 404


class TestOptimisticConcurrency:
    def test_update_with_correct_version(self, event, organizer):
        _, token = organizer
        r = requests.put(
            url(f"/events/{event['id']}"),
            json={"title": "Updated Title", "version": event["version"]},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert r.status_code == 200
        assert r.json()["event"]["version"] == event["version"] + 1

    def test_update_with_stale_version_returns_409(self, event, organizer):
        _, token = organizer
        r = requests.put(
            url(f"/events/{event['id']}"),
            json={"title": "Stale Update", "version": event["version"]},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert r.status_code == 409

    def test_delete_with_stale_version_returns_409(self, event, organizer):
        _, token = organizer
        r = requests.delete(
            url(f"/events/{event['id']}?version=1"),
            headers={"Authorization": f"Bearer {token}"},
        )
        assert r.status_code == 409


class TestRegistration:
    def test_register_for_event(self, attendee, event):
        _, token = attendee
        r = requests.post(
            url("/registrations"),
            json={"event_id": event["id"], "payment_method": "card"},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert r.status_code == 200
        data = r.json()
        assert "ticket_number" in data["registration"]
        assert data["registration"]["payment_status"] == "paid"

    def test_duplicate_registration_returns_409(self, attendee, event):
        _, token = attendee
        r = requests.post(
            url("/registrations"),
            json={"event_id": event["id"], "payment_method": "free"},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert r.status_code == 409

    def test_list_registrations_paginated(self, admin):
        _, token = admin
        r = requests.get(
            url("/registrations?page=1&page_size=5"),
            headers={"Authorization": f"Bearer {token}"},
        )
        assert r.status_code == 200
        data = r.json()
        assert "registrations" in data
        assert "total_pages" in data

    def test_registration_for_nonexistent_event(self, attendee):
        _, token = attendee
        r = requests.post(
            url("/registrations"),
            json={"event_id": 99999, "payment_method": "free"},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert r.status_code in (404, 503)


class TestCorrelationID:
    def test_correlation_id_returned(self, attendee):
        _, token = attendee
        r = requests.get(
            url("/users/me"),
            headers={
                "Authorization": f"Bearer {token}",
                "X-Correlation-ID": "test-corr-12345",
            },
        )
        assert r.status_code == 200
        assert r.headers.get("x-correlation-id") == "test-corr-12345"

    def test_correlation_id_generated_if_missing(self, attendee):
        _, token = attendee
        r = requests.get(
            url("/users/me"),
            headers={"Authorization": f"Bearer {token}"},
        )
        assert r.status_code == 200
        assert "x-correlation-id" in r.headers


class TestNotifications:
    def test_create_notification(self, admin):
        user, token = admin
        r = requests.post(
            url("/notifications"),
            json={
                "user_id": user["id"],
                "title": "Test Notification",
                "message": "Hello from integration test",
                "notification_type": "info",
            },
            headers={"Authorization": f"Bearer {token}"},
        )
        assert r.status_code == 200

    def test_get_user_notifications(self, admin):
        user, token = admin
        r = requests.get(
            url(f"/notifications/user/{user['id']}"),
            headers={"Authorization": f"Bearer {token}"},
        )
        assert r.status_code == 200
        assert "notifications" in r.json()

    def test_dlq_stats(self, admin):
        _, token = admin
        r = requests.get(
            url("/notifications/dlq/stats"),
            headers={"Authorization": f"Bearer {token}"},
        )
        assert r.status_code == 200
        data = r.json()
        assert "dead_letter_queue" in data
        assert "main_queue" in data
        assert data["dlq_max_retries"] >= 1


class TestOwnership:
    def test_user_cannot_access_others_registrations(self, attendee, admin):
        _, attendee_token = attendee
        admin_user, _ = admin
        r = requests.get(
            url(f"/registrations/user/{admin_user['id']}"),
            headers={"Authorization": f"Bearer {attendee_token}"},
        )
        assert r.status_code == 403

    def test_user_cannot_read_others_notifications(self, attendee, admin):
        _, attendee_token = attendee
        admin_user, _ = admin
        r = requests.get(
            url(f"/notifications/user/{admin_user['id']}"),
            headers={"Authorization": f"Bearer {attendee_token}"},
        )
        assert r.status_code == 403
