"""
Integration tests for Event Management System
Run via test-runner container or locally:
  pip install requests pytest
  BASE_URL=http://localhost:8080 pytest test_api.py -v
"""
import requests
import pytest
import os
import time

BASE = os.getenv("BASE_URL", "http://localhost:8080")

# ── Helpers ─────────────────────────────────────────────────────
def url(path): return f"{BASE}/api{path}"
def wait_for_services():
    for _ in range(20):
        try:
            r = requests.get(f"{BASE}/health", timeout=2)
            if r.status_code == 200:
                return True
        except Exception:
            pass
        time.sleep(2)
    return False

# ── Fixtures ─────────────────────────────────────────────────────
@pytest.fixture(scope="session", autouse=True)
def check_services():
    assert wait_for_services(), "Services did not become healthy in time"

@pytest.fixture(scope="session")
def test_user():
    import random, string
    suffix = ''.join(random.choices(string.ascii_lowercase, k=6))
    r = requests.post(url("/users/register"), json={
        "username": f"testuser_{suffix}",
        "email": f"test_{suffix}@example.com",
        "password": "testpass123",
        "full_name": "Test User"
    })
    assert r.status_code == 200
    return r.json()["user"]

@pytest.fixture(scope="session")
def test_event(test_user):
    r = requests.post(url("/events"), json={
        "title": "Test Conference",
        "description": "A test event",
        "event_type": "conference",
        "start_date": "2026-06-01 09:00:00",
        "end_date": "2026-06-01 18:00:00",
        "location": "Cairo",
        "max_capacity": 50,
        "organizer_id": test_user["id"],
        "ticket_price": 0.0
    })
    assert r.status_code == 200
    return r.json()["event"]

# ── User Service Tests ────────────────────────────────────────────
class TestUserService:
    def test_health(self):
        r = requests.get(url("/users/health"))
        assert r.status_code == 200
        assert r.json()["status"] == "healthy"

    def test_register_user(self, test_user):
        assert "id" in test_user
        assert "email" in test_user

    def test_duplicate_user_fails(self, test_user):
        r = requests.post(url("/users/register"), json={
            "username": test_user["username"],
            "email": test_user["email"],
            "password": "pass",
            "full_name": "Dup"
        })
        assert r.status_code == 400

    def test_get_user(self, test_user):
        r = requests.get(url(f"/users/{test_user['id']}"))
        assert r.status_code == 200
        assert r.json()["id"] == test_user["id"]

    def test_list_users(self):
        r = requests.get(url("/users"))
        assert r.status_code == 200
        assert "users" in r.json()

# ── Event Service Tests ───────────────────────────────────────────
class TestEventService:
    def test_health(self):
        r = requests.get(url("/events/health"))
        assert r.status_code == 200

    def test_create_event(self, test_event):
        assert "id" in test_event
        assert test_event["title"] == "Test Conference"

    def test_list_events(self):
        r = requests.get(url("/events"))
        assert r.status_code == 200
        assert isinstance(r.json()["events"], list)

    def test_get_event(self, test_event):
        r = requests.get(url(f"/events/{test_event['id']}"))
        assert r.status_code == 200
        assert r.json()["id"] == test_event["id"]

    def test_get_nonexistent_event(self):
        r = requests.get(url("/events/99999"))
        assert r.status_code == 404

# ── Registration Service Tests ────────────────────────────────────
class TestRegistrationService:
    def test_health(self):
        r = requests.get(url("/registrations/health"))
        assert r.status_code == 200

    def test_register_for_event(self, test_user, test_event):
        r = requests.post(url("/registrations"), json={
            "user_id": test_user["id"],
            "event_id": test_event["id"],
            "payment_method": "free"
        })
        assert r.status_code == 200
        data = r.json()
        assert "ticket_number" in data["registration"]
        return data["registration"]

    def test_duplicate_registration_fails(self, test_user, test_event):
        r = requests.post(url("/registrations"), json={
            "user_id": test_user["id"],
            "event_id": test_event["id"],
            "payment_method": "free"
        })
        assert r.status_code in (400, 409)

    def test_get_user_registrations(self, test_user):
        r = requests.get(url(f"/registrations/user/{test_user['id']}"))
        assert r.status_code == 200
        assert "registrations" in r.json()

# ── Notification Service Tests ────────────────────────────────────
class TestNotificationService:
    def test_health(self):
        r = requests.get(url("/notifications/health"))
        assert r.status_code == 200

    def test_create_notification(self, test_user):
        r = requests.post(url("/notifications"), json={
            "user_id": test_user["id"],
            "title": "Test Reminder",
            "message": "Your event starts tomorrow!",
            "notification_type": "reminder"
        })
        assert r.status_code == 200

    def test_get_notifications(self, test_user):
        r = requests.get(url(f"/notifications/user/{test_user['id']}"))
        assert r.status_code == 200
        assert "notifications" in r.json()
