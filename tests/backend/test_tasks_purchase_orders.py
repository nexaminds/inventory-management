"""
Tests for task and purchase order API endpoints.
"""
from datetime import date, timedelta

import pytest

# Delivery dates must not be in the past, so derive them from today
FUTURE_DATE = (date.today() + timedelta(days=30)).isoformat()


def _first_backlog_item_without_po(client):
    items = client.get("/api/backlog").json()
    for item in items:
        if not item["has_purchase_order"]:
            return item
    pytest.skip("No backlog item without a purchase order")


def _po_payload(backlog_item_id, **overrides):
    payload = {
        "backlog_item_id": backlog_item_id,
        "supplier_name": "Acme Components",
        "quantity": 50,
        "unit_cost": 12.5,
        "expected_delivery_date": FUTURE_DATE,
        "notes": "Rush order",
    }
    payload.update(overrides)
    return payload


class TestTaskEndpoints:
    """Test suite for task endpoints."""

    def test_get_all_tasks_empty(self, client):
        """Test that the task list starts empty."""
        response = client.get("/api/tasks")
        assert response.status_code == 200
        assert response.json() == []

    def test_create_task(self, client):
        """Test creating a task."""
        response = client.post(
            "/api/tasks",
            json={"title": "  Review stock  ", "priority": "high", "dueDate": "2025-10-08"},
        )
        assert response.status_code == 201

        task = response.json()
        assert task["id"].startswith("task-")
        assert task["title"] == "Review stock"
        assert task["priority"] == "high"
        assert task["dueDate"] == "2025-10-08"
        assert task["status"] == "pending"

    def test_get_tasks_newest_first(self, client):
        """Test that tasks are returned newest first."""
        first = client.post("/api/tasks", json={"title": "A", "dueDate": "2025-10-01"}).json()
        second = client.post("/api/tasks", json={"title": "B", "dueDate": "2025-10-02"}).json()

        data = client.get("/api/tasks").json()
        assert [t["id"] for t in data] == [second["id"], first["id"]]

    def test_create_task_blank_title(self, client):
        """Test that a blank title is rejected."""
        response = client.post("/api/tasks", json={"title": "   ", "dueDate": "2025-10-08"})
        assert response.status_code == 400
        assert "detail" in response.json()

    def test_create_task_invalid_priority(self, client):
        """Test that an unknown priority is rejected."""
        response = client.post(
            "/api/tasks", json={"title": "X", "priority": "urgent", "dueDate": "2025-10-08"}
        )
        assert response.status_code == 400

    def test_create_task_missing_due_date(self, client):
        """Test that dueDate is required."""
        response = client.post("/api/tasks", json={"title": "X"})
        assert response.status_code == 422

    @pytest.mark.parametrize("bad_date", ["banana", "2025-13-01", "2025-02-30", ""])
    def test_create_task_malformed_due_date(self, client, bad_date):
        """Test that a malformed dueDate is rejected and nothing is stored."""
        response = client.post("/api/tasks", json={"title": "X", "dueDate": bad_date})
        assert response.status_code == 422
        assert client.get("/api/tasks").json() == []

    def test_create_task_past_due_date_allowed(self, client):
        """Test that an overdue (past) dueDate is accepted."""
        response = client.post("/api/tasks", json={"title": "X", "dueDate": "2020-01-01"})
        assert response.status_code == 201
        assert response.json()["dueDate"] == "2020-01-01"

    def test_toggle_task(self, client):
        """Test toggling a task between pending and completed."""
        task = client.post("/api/tasks", json={"title": "X", "dueDate": "2025-10-08"}).json()

        response = client.patch(f"/api/tasks/{task['id']}")
        assert response.status_code == 200
        assert response.json()["status"] == "completed"

        response = client.patch(f"/api/tasks/{task['id']}")
        assert response.json()["status"] == "pending"

    def test_delete_task(self, client):
        """Test deleting a task."""
        task = client.post("/api/tasks", json={"title": "X", "dueDate": "2025-10-08"}).json()

        response = client.delete(f"/api/tasks/{task['id']}")
        assert response.status_code == 200
        assert client.get("/api/tasks").json() == []

    def test_task_ids_not_reused_after_delete(self, client):
        """Test that deleting a task does not cause a later task to reuse its ID."""
        first = client.post("/api/tasks", json={"title": "A", "dueDate": "2025-10-01"}).json()
        second = client.post("/api/tasks", json={"title": "B", "dueDate": "2025-10-02"}).json()
        client.delete(f"/api/tasks/{first['id']}")
        third = client.post("/api/tasks", json={"title": "C", "dueDate": "2025-10-03"}).json()

        assert third["id"] not in (first["id"], second["id"])

    def test_toggle_nonexistent_task(self, client):
        """Test toggling a task that doesn't exist."""
        response = client.patch("/api/tasks/nonexistent-999")
        assert response.status_code == 404
        assert "not found" in response.json()["detail"].lower()

    def test_delete_nonexistent_task(self, client):
        """Test deleting a task that doesn't exist."""
        response = client.delete("/api/tasks/nonexistent-999")
        assert response.status_code == 404
        assert "not found" in response.json()["detail"].lower()


class TestPurchaseOrderEndpoints:
    """Test suite for purchase order endpoints."""

    def test_create_purchase_order(self, client):
        """Test creating a purchase order for a backlog item."""
        item = _first_backlog_item_without_po(client)

        response = client.post("/api/purchase-orders", json=_po_payload(item["id"]))
        assert response.status_code == 201

        po = response.json()
        assert po["id"].startswith("po-")
        assert po["backlog_item_id"] == item["id"]
        assert po["supplier_name"] == "Acme Components"
        assert po["quantity"] == 50
        assert abs(po["unit_cost"] - 12.5) < 0.01
        assert po["expected_delivery_date"] == FUTURE_DATE
        assert po["status"] == "Pending"
        assert po["notes"] == "Rush order"
        # created_date is an ISO date (YYYY-MM-DD)
        assert len(po["created_date"]) == 10 and po["created_date"].count("-") == 2

    def test_get_purchase_order_by_backlog_item(self, client):
        """Test fetching the PO created for a backlog item."""
        item = _first_backlog_item_without_po(client)
        created = client.post("/api/purchase-orders", json=_po_payload(item["id"])).json()

        response = client.get(f"/api/purchase-orders/{item['id']}")
        assert response.status_code == 200
        assert response.json() == created

    def test_backlog_flags_item_after_po_created(self, client):
        """Test that /api/backlog reports has_purchase_order once a PO exists."""
        item = _first_backlog_item_without_po(client)
        client.post("/api/purchase-orders", json=_po_payload(item["id"]))

        backlog = client.get("/api/backlog").json()
        updated = next(b for b in backlog if b["id"] == item["id"])
        assert updated["has_purchase_order"] is True

    def test_create_duplicate_purchase_order(self, client):
        """Test that a second PO for the same backlog item is rejected."""
        item = _first_backlog_item_without_po(client)
        client.post("/api/purchase-orders", json=_po_payload(item["id"]))

        response = client.post("/api/purchase-orders", json=_po_payload(item["id"]))
        assert response.status_code == 409
        assert "detail" in response.json()

    def test_create_purchase_order_unknown_backlog_item(self, client):
        """Test creating a PO for a backlog item that doesn't exist."""
        response = client.post("/api/purchase-orders", json=_po_payload("nonexistent-999"))
        assert response.status_code == 404
        assert "not found" in response.json()["detail"].lower()

    @pytest.mark.parametrize(
        "overrides",
        [{"quantity": 0}, {"quantity": -5}, {"unit_cost": 0}, {"supplier_name": "   "}],
    )
    def test_create_purchase_order_invalid_input(self, client, overrides):
        """Test that invalid quantity, cost, or supplier is rejected."""
        item = _first_backlog_item_without_po(client)
        response = client.post("/api/purchase-orders", json=_po_payload(item["id"], **overrides))
        assert response.status_code == 400
        assert "detail" in response.json()

    @pytest.mark.parametrize("bad_date", ["banana", "2025-13-01", "12/01/2026", ""])
    def test_create_purchase_order_malformed_date(self, client, bad_date):
        """Test that a malformed delivery date is rejected and no PO is stored."""
        item = _first_backlog_item_without_po(client)
        response = client.post(
            "/api/purchase-orders", json=_po_payload(item["id"], expected_delivery_date=bad_date)
        )
        assert response.status_code == 422
        assert client.get(f"/api/purchase-orders/{item['id']}").status_code == 404

    def test_create_purchase_order_past_date(self, client):
        """Test that a delivery date before today is rejected."""
        item = _first_backlog_item_without_po(client)
        yesterday = (date.today() - timedelta(days=1)).isoformat()
        response = client.post(
            "/api/purchase-orders", json=_po_payload(item["id"], expected_delivery_date=yesterday)
        )
        assert response.status_code == 400
        assert "past" in response.json()["detail"].lower()

    def test_create_purchase_order_today_allowed(self, client):
        """Test that a delivery date of today is accepted (boundary)."""
        item = _first_backlog_item_without_po(client)
        today = date.today().isoformat()
        response = client.post(
            "/api/purchase-orders", json=_po_payload(item["id"], expected_delivery_date=today)
        )
        assert response.status_code == 201
        assert response.json()["expected_delivery_date"] == today

    def test_duplicate_purchase_order_leaves_original_intact(self, client):
        """Test that a rejected duplicate (409) does not overwrite the existing PO.

        The client relies on this: on 409 it switches to view mode and shows the
        PO that already exists.
        """
        item = _first_backlog_item_without_po(client)
        original = client.post("/api/purchase-orders", json=_po_payload(item["id"])).json()

        response = client.post(
            "/api/purchase-orders",
            json=_po_payload(item["id"], supplier_name="Other Supplier", quantity=1),
        )
        assert response.status_code == 409
        assert client.get(f"/api/purchase-orders/{item['id']}").json() == original

    def test_get_nonexistent_purchase_order(self, client):
        """Test fetching a PO for a backlog item that has none."""
        response = client.get("/api/purchase-orders/nonexistent-999")
        assert response.status_code == 404
        assert "not found" in response.json()["detail"].lower()
