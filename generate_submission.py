import json
from pathlib import Path
import bot

DATASET_DIR = Path("dataset/expanded")

def load_all_contexts():
    # Load categories
    cat_dir = DATASET_DIR / "categories"
    for f in cat_dir.glob("*.json"):
        data = json.load(open(f))
        bot.contexts[("category", data.get("slug", f.stem))] = {"version": 1, "payload": data}
        
    # Load merchants
    merch_dir = DATASET_DIR / "merchants"
    for f in merch_dir.glob("*.json"):
        data = json.load(open(f))
        bot.contexts[("merchant", data["merchant_id"])] = {"version": 1, "payload": data}

    # Load customers
    cust_dir = DATASET_DIR / "customers"
    for f in cust_dir.glob("*.json"):
        data = json.load(open(f))
        bot.contexts[("customer", data["customer_id"])] = {"version": 1, "payload": data}

    # Load triggers
    trig_dir = DATASET_DIR / "triggers"
    for f in trig_dir.glob("*.json"):
        data = json.load(open(f))
        bot.contexts[("trigger", data["id"])] = {"version": 1, "payload": data}

def generate_submission():
    load_all_contexts()
    test_pairs = json.load(open(DATASET_DIR / "test_pairs.json"))["pairs"]
    
    out_file = Path("submission.jsonl")
    lines = []
    
    for pair in test_pairs:
        test_id = pair["test_id"]
        t_id = pair["trigger_id"]
        m_id = pair["merchant_id"]
        c_id = pair.get("customer_id")
        
        trigger = bot.get_context("trigger", t_id)
        merchant = bot.get_context("merchant", m_id)
        customer = bot.get_context("customer", c_id) if c_id else None
        
        cat_slug = merchant.get("category_slug", "dentists") if merchant else "dentists"
        category = bot.get_context("category", cat_slug)
        
        if not (trigger and merchant and category):
            print(f"Warning: missing context for {test_id} ({t_id}, {m_id})")
            continue
            
        msg = bot.compose_message(category, merchant, trigger, customer)
        
        line_item = {
            "test_id": test_id,
            "body": msg["body"],
            "cta": msg["cta"],
            "send_as": msg["send_as"],
            "suppression_key": msg["suppression_key"],
            "rationale": msg["rationale"]
        }
        lines.append(json.dumps(line_item))
        
    out_file.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"Generated submission.jsonl with {len(lines)} test pair entries.")

if __name__ == "__main__":
    generate_submission()
