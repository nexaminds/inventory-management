"""
Tests for restocking order API endpoints.
"""
from datetime import date, timedelta

import pytest


def _item(sku="GSK-203", name="High-Temperature Gasket", quantity=10, unit_cost=4.25, lead_time_days=5):
    return {
        "item_sku": sku,
        "item_name": name,
        "quantity": quantity,
        "unit_cost": unit_cost,
        "lead_time_days": lead_time_days,
    }


class TestDemandForecastRestockingFields:
    """Forecasts carry the pricing and lead-time data restocking depends on."""

    def test_demand_forecast_cost_and_lead_time_types(self, client):
        """Test that every forecast has a positive unit_cost and lead_time_days."""
        response = client.get("/api/demand")
        assert response.status_code == 200

        data = response.json()
        assert len(data) > 0
        for forecast in data:
            assert isinstance(forecast["unit_cost"], (int, float))
            assert isinstance(forecast["lead_time_days"], int)
            assert forecast["unit_cost"] > 0
            assert forecast["lead_time_days"] > 0


class TestRestockingOrderEndpoints:
    """Test suite for restocking order endpoints."""

    def test_get_all_restocking_orders_empty(self, client):
        """Test that no restocking orders exist before any are submitted."""
        response = client.get("/api/restocking-orders")
        assert response.status_code == 200
        assert response.json() == []

    def test_create_restocking_order(self, client):
        """Test submitting a restocking order returns the created order."""
        payload = {"budget": 5000, "items": [_item()]}
        response = client.post("/api/restocking-orders", json=payload)
        assert response.status_code == 201

        order = response.json()
        for field in ["id", "order_number", "items", "total_cost", "budget",
                      "status", "order_date", "lead_time_days", "expected_delivery"]:
            assert field in order
        assert order["order_number"] == "RST-0001"
        assert order["status"] == "Submitted"
        assert order["budget"] == 5000
        assert len(order["items"]) == 1

    def test_restocking_order_total_calculation(self, client):
        """Test that total_cost is quantity x unit_cost summed over items."""
        payload = {"budget": 10000, "items": [
            _item("GSK-203", quantity=100),
            _item("BRG-102", "Steel Bearing Assembly", quantity=10, unit_cost=34.75, lead_time_days=14),
        ]}
        order = client.post("/api/restocking-orders", json=payload).json()

        expected = sum(i["quantity"] * i["unit_cost"] for i in order["items"])
        assert abs(order["total_cost"] - expected) < 0.01

    def test_restocking_order_uses_server_prices(self, client):
        """Test that client-supplied cost and lead time are replaced by forecast data."""
        forecasts = {f["item_sku"]: f for f in client.get("/api/demand").json()}
        payload = {"budget": 100000, "items": [_item("MTR-304", quantity=2, unit_cost=0.01, lead_time_days=1)]}
        order = client.post("/api/restocking-orders", json=payload).json()

        item = order["items"][0]
        assert item["unit_cost"] == forecasts["MTR-304"]["unit_cost"]
        assert item["lead_time_days"] == forecasts["MTR-304"]["lead_time_days"]

    def test_restocking_order_lead_time_calculation(self, client):
        """Test that order lead time is the slowest item's and drives expected delivery."""
        forecasts = {f["item_sku"]: f for f in client.get("/api/demand").json()}
        skus = ["GSK-203", "CTL-330"]
        payload = {"budget": 100000, "items": [_item(sku, quantity=1) for sku in skus]}
        order = client.post("/api/restocking-orders", json=payload).json()

        expected_lead = max(forecasts[s]["lead_time_days"] for s in skus)
        assert order["lead_time_days"] == expected_lead

        order_date = date.fromisoformat(order["order_date"])
        assert order_date == date.today()
        assert date.fromisoformat(order["expected_delivery"]) == order_date + timedelta(days=expected_lead)

    def test_get_restocking_orders_newest_first(self, client):
        """Test that submitted orders are listed newest first."""
        for qty in (1, 2):
            client.post("/api/restocking-orders", json={"budget": 1000, "items": [_item(quantity=qty)]})

        data = client.get("/api/restocking-orders").json()
        assert [o["order_number"] for o in data] == ["RST-0002", "RST-0001"]

    def test_create_restocking_order_empty_items(self, client):
        """Test that an order with no items is rejected."""
        response = client.post("/api/restocking-orders", json={"budget": 1000, "items": []})
        assert response.status_code == 400
        assert "detail" in response.json()

    def test_create_restocking_order_over_budget(self, client):
        """Test that an order costing more than the budget is rejected."""
        response = client.post("/api/restocking-orders", json={"budget": 10, "items": [_item(quantity=100)]})
        assert response.status_code == 400
        assert "budget" in response.json()["detail"].lower()

    def test_create_restocking_order_unknown_sku(self, client):
        """Test that an order for a SKU not in the forecast is rejected."""
        response = client.post("/api/restocking-orders", json={"budget": 1000, "items": [_item("NOPE-999")]})
        assert response.status_code == 400
        assert "unknown sku" in response.json()["detail"].lower()

    @pytest.mark.parametrize("quantity", [0, -5])
    def test_create_restocking_order_invalid_quantity(self, client, quantity):
        """Test that zero or negative quantities are rejected."""
        response = client.post("/api/restocking-orders", json={"budget": 1000, "items": [_item(quantity=quantity)]})
        assert response.status_code == 400

    def test_rejected_order_is_not_stored(self, client):
        """Test that a rejected order does not appear in the list."""
        client.post("/api/restocking-orders", json={"budget": 1, "items": [_item(quantity=100)]})
        assert client.get("/api/restocking-orders").json() == []

    def test_create_restocking_order_exactly_at_budget(self, client):
        """Test that an order whose total equals the budget is accepted."""
        # 100 x 4.25 = 425.00 exactly
        response = client.post("/api/restocking-orders", json={"budget": 425, "items": [_item(quantity=100)]})
        assert response.status_code == 201
        assert abs(response.json()["total_cost"] - 425) < 0.01

    def test_create_restocking_order_just_over_budget(self, client):
        """Test that a total one cent over the budget is rejected."""
        response = client.post("/api/restocking-orders", json={"budget": 424.99, "items": [_item(quantity=100)]})
        assert response.status_code == 400
