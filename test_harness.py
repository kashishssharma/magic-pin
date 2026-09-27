import json
import urllib.request
import urllib.error
from pathlib import Path

BASE_URL = "http://localhost:8080"
DATASET_DIR = Path("dataset")

def make_req(method, path, body=None):
    url = f"{BASE_URL}{path}"
    data = json.dumps(body).encode('utf-8') if body else None
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"}, method=method)
    try:
        with urllib.request.urlopen(req) as resp:
            return json.loads(resp.read().decode('utf-8')), resp.status
    except urllib.error.HTTPError as e:
        return json.loads(e.read().decode('utf-8')), e.code

def run_tests():
    print("--- 1. Testing GET /v1/healthz ---")
    data, code = make_req("GET", "/v1/healthz")
    print(f"Healthz: {code} -> {data}")
    assert code == 200 and data.get("status") == "ok"

    print("\n--- 2. Testing GET /v1/metadata ---")
    data, code = make_req("GET", "/v1/metadata")
    print(f"Metadata: {code} -> {data}")
    assert code == 200 and "team_name" in data

    print("\n--- 3. Testing POST /v1/context (Category, Merchant, Trigger, Customer) ---")
    cat_path = DATASET_DIR / "categories" / "dentists.json"
    if cat_path.exists():
        cat_data = json.load(open(cat_path))
        data, code = make_req("POST", "/v1/context", {
            "scope": "category", "context_id": "dentists", "version": 1,
            "payload": cat_data, "delivered_at": "2026-04-26T10:00:00Z"
        })
        print(f"Push category dentists: {code} -> {data}")
        assert data.get("accepted") is True or data.get("reason") == "stale_version"

    merch_path = DATASET_DIR / "merchants_seed.json"
    m_data = json.load(open(merch_path))["merchants"][0]
    data, code = make_req("POST", "/v1/context", {
        "scope": "merchant", "context_id": m_data["merchant_id"], "version": 1,
        "payload": m_data, "delivered_at": "2026-04-26T10:00:00Z"
    })
    print(f"Push merchant {m_data['merchant_id']}: {code} -> {data}")
    assert data.get("accepted") is True or data.get("reason") == "stale_version"

    trig_path = DATASET_DIR / "triggers_seed.json"
    t_data = json.load(open(trig_path))["triggers"][0]
    data, code = make_req("POST", "/v1/context", {
        "scope": "trigger", "context_id": t_data["id"], "version": 1,
        "payload": t_data, "delivered_at": "2026-04-26T10:00:00Z"
    })
    print(f"Push trigger {t_data['id']}: {code} -> {data}")
    assert data.get("accepted") is True or data.get("reason") == "stale_version"

    print("\n--- 4. Testing POST /v1/tick ---")
    data, code = make_req("POST", "/v1/tick", {
        "now": "2026-04-26T10:30:00Z",
        "available_triggers": [t_data["id"]]
    })
    print(f"Tick actions: {code} -> {json.dumps(data, indent=2)}")
    assert code == 200 and len(data.get("actions", [])) > 0

    print("\n--- 5. Testing POST /v1/reply (Auto-reply detection) ---")
    auto_msg = "Thank you for contacting us! Our team will respond shortly."
    for turn in range(1, 4):
        data, code = make_req("POST", "/v1/reply", {
            "conversation_id": "conv_auto_test",
            "merchant_id": m_data["merchant_id"],
            "from_role": "merchant",
            "message": auto_msg,
            "received_at": "2026-04-26T10:35:00Z",
            "turn_number": turn
        })
        print(f"Auto-reply turn {turn}: action={data.get('action')} | rationale={data.get('rationale')}")

    print("\n--- 6. Testing POST /v1/reply (Intent transition) ---")
    data, code = make_req("POST", "/v1/reply", {
        "conversation_id": "conv_intent_test",
        "merchant_id": m_data["merchant_id"],
        "from_role": "merchant",
        "message": "Ok lets do it. Whats next?",
        "received_at": "2026-04-26T10:40:00Z",
        "turn_number": 2
    })
    print(f"Intent transition: action={data.get('action')} | body={data.get('body')}")
    assert data.get("action") == "send"

    print("\n--- 7. Testing POST /v1/reply (Hostile / Opt-out) ---")
    data, code = make_req("POST", "/v1/reply", {
        "conversation_id": "conv_hostile_test",
        "merchant_id": m_data["merchant_id"],
        "from_role": "merchant",
        "message": "Stop messaging me. This is useless spam.",
        "received_at": "2026-04-26T10:45:00Z",
        "turn_number": 2
    })
    print(f"Hostile handling: action={data.get('action')} | rationale={data.get('rationale')}")
    assert data.get("action") == "end"

    print("\n[SUCCESS] ALL TEST HARNESS SUITES PASSED SUCCESSFULLY!")

if __name__ == "__main__":
    run_tests()
