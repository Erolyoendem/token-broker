"""
Integration test: Crowdfunding end-to-end flow against the live API.
Logs all steps to crowdfunding_test.log.
Run: python -m pytest tests/test_crowdfunding_flow.py -v -s
"""
import logging
import requests
import pytest

BASE_URL = "https://yondem-production.up.railway.app"
HEADERS = {"X-Api-Key": "tkb_test_123", "Content-Type": "application/json"}

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)s  %(message)s",
    handlers=[
        logging.FileHandler("crowdfunding_test.log"),
        logging.StreamHandler(),
    ],
)
log = logging.getLogger("crowdfunding_flow")

_state: dict = {}


def test_01_create_group_buy():
    payload = {
        "name": "AutoTest Bulk DeepSeek",
        "target_tokens": 100,
        "price_per_token": 0.001,
        "provider": "deepseek",
    }
    log.info("STEP 1 – POST /group-buys  payload=%s", payload)
    resp = requests.post(f"{BASE_URL}/group-buys", json=payload, headers=HEADERS, timeout=15)
    log.info("  → %s  %s", resp.status_code, resp.text[:200])
    assert resp.status_code == 200, f"Create failed: {resp.text}"
    data = resp.json()
    assert "id" in data
    assert data["status"] == "pending"
    _state["group_buy_id"] = data["id"]
    log.info("  ✓ group_buy created  id=%s", data["id"])


def test_02_list_group_buys():
    log.info("STEP 2 – GET /group-buys")
    resp = requests.get(f"{BASE_URL}/group-buys", headers=HEADERS, timeout=15)
    log.info("  → %s  %s", resp.status_code, resp.text[:300])
    assert resp.status_code == 200
    ids = [row["id"] for row in resp.json()]
    gid = _state.get("group_buy_id")
    assert gid in ids, f"Created group buy {gid} not found in list: {ids}"
    log.info("  ✓ group_buy_id=%s present in list", gid)


def test_03_join_group_buy():
    gid = _state.get("group_buy_id")
    log.info("STEP 3 – POST /group-buys/%s/join  tokens=100", gid)
    resp = requests.post(
        f"{BASE_URL}/group-buys/{gid}/join",
        json={"tokens": 100},
        headers=HEADERS,
        timeout=15,
    )
    log.info("  → %s  %s", resp.status_code, resp.text[:200])
    assert resp.status_code == 200, f"Join failed: {resp.text}"
    data = resp.json()
    assert data["current_tokens"] >= 100
    _state["status_after_join"] = data["status"]
    log.info("  ✓ joined  current_tokens=%s  status=%s", data["current_tokens"], data["status"])


def test_04_trigger_group_buy():
    gid = _state.get("group_buy_id")
    log.info("STEP 4 – POST /group-buys/%s/trigger", gid)
    resp = requests.post(
        f"{BASE_URL}/group-buys/{gid}/trigger",
        headers=HEADERS,
        timeout=15,
    )
    log.info("  → %s  %s", resp.status_code, resp.text[:200])
    assert resp.status_code == 200, f"Trigger failed: {resp.text}"
    data = resp.json()
    # Either already active from join, or trigger activated it
    assert data["status"] in ("active", "pending"), f"Unexpected status: {data}"
    log.info("  ✓ trigger result  status=%s  triggered=%s", data["status"], data.get("triggered"))


def test_05_get_group_buy_details():
    gid = _state.get("group_buy_id")
    log.info("STEP 5 – GET /group-buys/%s", gid)
    resp = requests.get(f"{BASE_URL}/group-buys/{gid}", headers=HEADERS, timeout=15)
    log.info("  → %s  %s", resp.status_code, resp.text[:300])
    assert resp.status_code == 200, f"Get details failed: {resp.text}"
    data = resp.json()
    assert "participants" in data, "No participants key in response"
    assert isinstance(data["participants"], list)
    log.info(
        "  ✓ details ok  participants=%s  status=%s",
        len(data["participants"]),
        data["status"],
    )
