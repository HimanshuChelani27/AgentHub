def test_seeded_servers_connect_and_discover_tools(client):
    from tests.test_auth_registry import login

    admin = login(client, "admin", "admin")
    servers = {s["server"]["slug"]: s for s in client.get("/servers", headers=admin).json()}

    kb = servers["company_kb"]
    assert kb["server"]["status"] == "connected", kb["server"]["last_error"]
    assert {t["name"] for t in kb["tools"]} == {
        "search_customers",
        "get_customer",
        "list_open_tickets",
        "get_contract",
    }
    get_customer = next(t for t in kb["tools"] if t["name"] == "get_customer")
    assert "customer_id" in get_customer["input_schema"]["properties"]

    assert {t["name"] for t in servers["utils"]["tools"]} == {"calculator", "current_time", "word_count"}


def test_refresh_reconnects(client):
    from tests.test_auth_registry import login

    admin = login(client, "admin", "admin")
    res = client.post("/servers/utils/refresh", headers=admin)
    assert res.status_code == 200
    assert res.json()["server"]["status"] == "connected"
    assert len(res.json()["tools"]) == 3


def test_unreachable_http_server_is_marked_error(client):
    from tests.test_auth_registry import login

    admin = login(client, "admin", "admin")
    body = {"slug": "offline", "name": "Offline", "transport": "http", "url": "http://127.0.0.1:9/mcp"}
    res = client.post("/servers", json=body, headers=admin)
    assert res.status_code == 201
    assert res.json()["server"]["status"] == "error"
    assert res.json()["tools"] == []
