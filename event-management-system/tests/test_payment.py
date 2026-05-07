import os
import time
import random
import string
import requests
import pytest

BASE = os.getenv("BASE_URL", "http://localhost:8080")


def url(path: str) -> str:
    return f"{BASE}/api{path}"


def wait_for_services() -> bool:
    for _ in range(20):
        try:
            r = requests.get(f"{BASE}/health", timeout=2)
            if r.status_code == 200:
                return True
        except Exception:
            pass
        time.sleep(2)
    return False


@pytest.fixture(scope="session", autouse=True)
def check_services():
    assert wait_for_services(), "Services did not become healthy in time"


@pytest.fixture(scope="session")
def payment_user():
    suffix = "".join(random.choices(string.ascii_lowercase, k=6))
    r = requests.post(
        url("/users/register"),
        json={
            "username": f"payuser_{suffix}",
            "email": f"pay_{suffix}@example.com",
            "password": "testpass123",
            "full_name": "Payment User",
        },
    )
    assert r.status_code == 200
    return r.json()["user"]


@pytest.fixture(scope="session")
def paid_event(payment_user):
    r = requests.post(
        url("/events"),
        json={
            "title": "Paid Workshop",
            "description": "Event for payment tests",
            "event_type": "workshop",
            "start_date": "2026-07-01 09:00:00",
            "end_date": "2026-07-01 17:00:00",
            "location": "Alexandria",
            "max_capacity": 30,
            "organizer_id": payment_user["id"],
            "ticket_price": 25.0,
        },
    )
    assert r.status_code == 200
    return r.json()["event"]


class TestPaymentFlow:
    def test_paid_registration_sets_payment_fields(self, payment_user, paid_event):
        r = requests.post(
            url("/registrations"),
            json={
                "user_id": payment_user["id"],
                "event_id": paid_event["id"],
                "payment_method": "card",
            },
        )
        assert r.status_code == 200
        registration = r.json()["registration"]
        assert registration["payment_status"] == "paid"
        assert registration["payment_gateway"].startswith("simulated-")
        assert registration["payment_reference"]

    def test_process_payment_force_decline(self, payment_user, paid_event):
        # Create a second user and free registration, then force a payment decline.
        suffix = "".join(random.choices(string.ascii_lowercase, k=6))
        user_resp = requests.post(
            url("/users/register"),
            json={
                "username": f"payuser2_{suffix}",
                "email": f"pay2_{suffix}@example.com",
                "password": "testpass123",
                "full_name": "Payment User 2",
            },
        )
        assert user_resp.status_code == 200
        user2 = user_resp.json()["user"]

        reg_resp = requests.post(
            url("/registrations"),
            json={
                "user_id": user2["id"],
                "event_id": paid_event["id"],
                "payment_method": "free",
            },
        )
        assert reg_resp.status_code == 200
        reg_id = reg_resp.json()["registration"]["id"]

        payment_resp = requests.post(
            url(f"/registrations/{reg_id}/process-payment"),
            json={
                "payment_method": "card",
                "amount": 25.0,
                "force_decline": True,
            },
        )
        assert payment_resp.status_code == 200
        payment = payment_resp.json()["payment"]
        assert payment["payment_status"] == "failed"
        assert payment["payment_reference"].startswith("DECLINED-")
