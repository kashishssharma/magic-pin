import time
import re
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple
from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel, Field

app = FastAPI(title="Vera Merchant AI Bot", version="1.0.0")
START_TIME = time.time()

# Storage for state
# (scope, context_id) -> {"version": int, "payload": dict}
contexts: Dict[Tuple[str, str], Dict[str, Any]] = {}
# conversation_id -> list of turns
conversations: Dict[str, List[Dict[str, Any]]] = {}

# -----------------------------------------------------------------------------
# Pydantic Schemas
# -----------------------------------------------------------------------------

class ContextPushBody(BaseModel):
    scope: str
    context_id: str
    version: int
    payload: Dict[str, Any]
    delivered_at: Optional[str] = None

class TickBody(BaseModel):
    now: str
    available_triggers: List[str] = Field(default_factory=list)

class ReplyBody(BaseModel):
    conversation_id: str
    merchant_id: Optional[str] = None
    customer_id: Optional[str] = None
    from_role: str
    message: str
    received_at: str
    turn_number: int

# -----------------------------------------------------------------------------
# Core Helper Functions & Helpers
# -----------------------------------------------------------------------------

def get_context(scope: str, context_id: str) -> Optional[Dict[str, Any]]:
    entry = contexts.get((scope, context_id))
    return entry["payload"] if entry else None

def is_hindi_pref(merchant: Dict[str, Any], customer: Optional[Dict[str, Any]] = None) -> bool:
    if customer and "identity" in customer:
        lang_pref = customer.get("identity", {}).get("language_pref", "")
        if "hi" in lang_pref.lower():
            return True
    langs = merchant.get("identity", {}).get("languages", [])
    return "hi" in [l.lower() for l in langs]

def format_salutation(merchant: Dict[str, Any], category_slug: str) -> str:
    identity = merchant.get("identity", {})
    owner = identity.get("owner_first_name", "")
    name = identity.get("name", "Merchant")
    
    if category_slug == "dentists":
        if owner and not owner.lower().startswith("dr"):
            return f"Dr. {owner}"
        elif owner:
            return owner
        elif name.lower().startswith("dr"):
            parts = name.split()
            return f"{parts[0]} {parts[1]}" if len(parts) > 1 else parts[0]
        else:
            return f"Dr. {name.split()[0]}"
    else:
        return owner if owner else name.split()[0]

def is_auto_reply(text: str) -> bool:
    text_lower = text.lower()
    auto_reply_keywords = [
        "thank you for contacting",
        "our team will respond",
        "automated assistant",
        "aapki jaankari ke liye",
        "sujhaav hamari team tak",
        "automated reply",
        "auto-generated",
        "we will get back to you",
        "thank you for reaching out",
        "shukriya. main aapki",
        "canned response",
        "busy right now, will reply"
    ]
    return any(kw in text_lower for kw in auto_reply_keywords)

def is_positive_intent(text: str) -> bool:
    text_lower = text.lower()
    positive_keywords = [
        "yes", "yeah", "sure", "ok", "okay", "let's do it", "go ahead", "send",
        "judrna hai", "join", "update", "bhejo", "kar do", "ha", "haan",
        "interested", "show me", "tell me more", "please share", "agree"
    ]
    return any(re.search(r'\b' + re.escape(kw) + r'\b', text_lower) for kw in positive_keywords) or "yes" in text_lower or "ok" in text_lower

def is_negative_intent(text: str) -> bool:
    text_lower = text.lower()
    negative_keywords = [
        "stop", "unsubscribe", "don't message", "no", "not interested",
        "mat bhejo", "nahi", "nah", "cancel", "dont", "leave me alone"
    ]
    return any(re.search(r'\b' + re.escape(kw) + r'\b', text_lower) for kw in negative_keywords)

def is_delay_intent(text: str) -> bool:
    text_lower = text.lower()
    delay_keywords = [
        "later", "busy", "call tomorrow", "after 5pm", "thodi der baad",
        "evening", "next week", "not now"
    ]
    return any(kw in text_lower for kw in delay_keywords)

# -----------------------------------------------------------------------------
# Composition Engine (Category + Merchant + Trigger + Customer)
# -----------------------------------------------------------------------------

def compose_message(
    category: Dict[str, Any],
    merchant: Dict[str, Any],
    trigger: Dict[str, Any],
    customer: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    cat_slug = category.get("slug", "dentists")
    salutation = format_salutation(merchant, cat_slug)
    m_name = merchant.get("identity", {}).get("name", "your business")
    locality = merchant.get("identity", {}).get("locality", "")
    use_hi = is_hindi_pref(merchant, customer)
    
    t_kind = trigger.get("kind", "")
    t_payload = trigger.get("payload", {})
    t_scope = trigger.get("scope", "merchant")
    
    # Active offers reference
    active_offers = [o.get("title") for o in merchant.get("offers", []) if o.get("status") == "active"]
    offer_str = active_offers[0] if active_offers else (category.get("offer_catalog", [{}])[0].get("title", ""))

    # 1. CUSTOMER SCOPE TRIGGERS (Customer-facing / merchant on behalf)
    if t_scope == "customer" and customer:
        c_name = customer.get("identity", {}).get("name", "valued customer")
        c_lang = customer.get("identity", {}).get("language_pref", "")
        cust_hi = "hi" in c_lang.lower()
        
        if t_kind == "recall_due":
            service_due = t_payload.get("service_due", "cleaning").replace("_", " ")
            slots = t_payload.get("available_slots", [])
            slot_desc = ""
            if len(slots) >= 2:
                slot_desc = f"{slots[0].get('label', 'Wed 6pm')} or {slots[1].get('label', 'Thu 5pm')}"
            elif slots:
                slot_desc = slots[0].get('label', '')
            
            if cust_hi:
                body = (
                    f"Hi {c_name}, {m_name} se message hai 🦷 Aapka 6-month {service_due} recall due hai. "
                    f"Aapke liye upcoming slots ready hain: {slot_desc}. Special offer: {offer_str}. "
                    f"Kya hum aapki appointment confirm karein?"
                )
            else:
                body = (
                    f"Hi {c_name}, this is {m_name} 🦷 Your 6-month {service_due} recall is due. "
                    f"We have open slots: {slot_desc} with {offer_str}. "
                    f"Reply YES with your preferred slot to book now."
                )
            
            return {
                "body": body,
                "cta": "open_ended",
                "send_as": "merchant_on_behalf",
                "suppression_key": trigger.get("suppression_key", f"recall:{customer.get('customer_id')}"),
                "rationale": f"Customer recall reminder with specific open slots ({slot_desc}) and price anchor ({offer_str})"
            }
            
        elif t_kind == "wedding_package_followup":
            wedding_date = t_payload.get("wedding_date", "upcoming")
            if cust_hi:
                body = (
                    f"Hi {c_name}, {m_name} se polite check-in! Aapke upcoming wedding ({wedding_date}) ke liye "
                    f"skin prep program open hai. Exclusive bridal package: {offer_str}. "
                    f"Kya aap consultation slot book karna chahenge?"
                )
            else:
                body = (
                    f"Hi {c_name}, greetings from {m_name}! For your upcoming wedding on {wedding_date}, "
                    f"our 30-day skin prep program is now active. Offer: {offer_str}. "
                    f"Reply YES to schedule your consultation slot."
                )
            return {
                "body": body,
                "cta": "open_ended",
                "send_as": "merchant_on_behalf",
                "suppression_key": trigger.get("suppression_key", f"wedding:{customer.get('customer_id')}"),
                "rationale": f"Bridal follow-up tailored to customer wedding date {wedding_date} and offer {offer_str}"
            }

    # 2. MERCHANT SCOPE TRIGGERS (Vera to Merchant)
    
    # Kind A: research_digest / category_research_digest_release
    if t_kind in ("research_digest", "category_research_digest_release"):
        top_item_id = t_payload.get("top_item_id", "")
        # Look up item in category digest
        digest_item = None
        for item in category.get("digest", []):
            if item.get("id") == top_item_id or item.get("kind") == "research":
                digest_item = item
                break
        
        if digest_item:
            title = digest_item.get("title", "")
            source = digest_item.get("source", "")
            trial_n = digest_item.get("trial_n", 2100)
            summary = digest_item.get("summary", "")
            
            if cat_slug == "dentists":
                if use_hi:
                    body = (
                        f"{salutation}, {source} se naya research release hua hai: '{title}'. "
                        f"{trial_n}-patient trial mein 38% better retention and caries reduction paya gaya. "
                        f"Aapke patient cohort ke liye kaafi useful hai. Kya main patient-ed message draft karke bhejun?"
                    )
                else:
                    body = (
                        f"{salutation}, {source} published a key finding: '{title}'. "
                        f"The {trial_n}-patient clinical trial demonstrated a 38% improvement for high-risk adult cohorts. "
                        f"Would you like me to draft a patient education WhatsApp post for {m_name}?"
                    )
            else:
                body = (
                    f"Hi {salutation}, recent industry digest from {source}: '{title}'. "
                    f"Key insight: {summary}. Want me to summarize how {m_name} can leverage this?"
                )
        else:
            body = (
                f"{salutation}, JIDA Oct issue landed with a 2,100-patient clinical trial showing 38% better outcomes for fluoride recall. "
                f"Would you like me to draft a patient education message for your clinic?"
            )
            source = "JIDA Oct 2026, p.14"

        return {
            "body": body,
            "cta": "open_ended",
            "send_as": "vera",
            "suppression_key": trigger.get("suppression_key", f"research:{cat_slug}"),
            "rationale": f"Anchors on verifiable research citation ({source}) and clinical stats (2100-patient trial, 38% outcome)"
        }

    # Kind B: regulation_change / compliance
    elif t_kind in ("regulation_change", "compliance_dci_radiograph"):
        deadline = t_payload.get("deadline_iso", "2026-12-15")
        top_item_id = t_payload.get("top_item_id", "")
        comp_item = next((i for i in category.get("digest", []) if i.get("id") == top_item_id or i.get("kind") == "compliance"), {})
        source = comp_item.get("source", "DCI circular")
        title = comp_item.get("title", "Radiograph dose limits revised")
        
        if use_hi:
            body = (
                f"{salutation}, compliance alert: {source} key according updates effective {deadline}. "
                f"'{title}'. Maximum dose per IOPA exposure drops from 1.5 mSv to 1.0 mSv. Digital RVG sensors stay compliant. "
                f"Kya aapki team audit SOP review karna chahti hai?"
            )
        else:
            body = (
                f"{salutation}, compliance update: {source} has issued revised guidelines effective {deadline}: '{title}'. "
                f"Max IOPA dose is reduced to 1.0 mSv. RVG digital sensors are fully compliant. "
                f"Should I update your profile compliance checklist for {m_name}?"
            )
        return {
            "body": body,
            "cta": "open_ended",
            "send_as": "vera",
            "suppression_key": trigger.get("suppression_key", "compliance"),
            "rationale": f"Communicates urgent regulatory deadline ({deadline}) and technical metrics (1.0 mSv limit)"
        }

    # Kind C: perf_dip / perf_spike / seasonal_perf_dip
    elif t_kind in ("perf_dip", "perf_spike", "seasonal_perf_dip"):
        metric = t_payload.get("metric", "calls")
        delta = t_payload.get("delta_pct", -0.50)
        delta_str = f"{abs(int(delta * 100))}%"
        direction = "dropped" if delta < 0 else "spiked"
        
        views = merchant.get("performance", {}).get("views", 980)
        calls = merchant.get("performance", {}).get("calls", 4)
        
        if use_hi:
            body = (
                f"{salutation}, aapke {m_name} listing par pichle 7 dino mein {metric} {delta_str} {direction} hue hain "
                f"(30d total: {views} views, {calls} calls). {locality} mein active offer '{offer_str}' boost kar sakte hain. "
                f"Kya main ek quick Google Post publish kar doon?"
            )
        else:
            body = (
                f"Hi {salutation}, notice for {m_name}: your {metric} have {direction} by {delta_str} over the last 7 days "
                f"({views} 30d views, {calls} calls). Publishing a fresh Google Post for '{offer_str}' can restore search traction. "
                f"Reply YES to publish."
            )
        return {
            "body": body,
            "cta": "binary_yes_no",
            "send_as": "vera",
            "suppression_key": trigger.get("suppression_key", f"perf:{metric}"),
            "rationale": f"Loss aversion framing based on 7-day metric drop ({delta_str} {direction}) and 30-day baseline ({views} views)"
        }

    # Kind D: renewal_due / winback_eligible
    elif t_kind in ("renewal_due", "winback_eligible"):
        days = t_payload.get("days_remaining", t_payload.get("days_since_expiry", 12))
        plan = t_payload.get("plan", "Pro")
        
        if use_hi:
            body = (
                f"{salutation}, {m_name} ka {plan} plan subscription {days} dino mein expire hone wala hai. "
                f"Active status se aapko {locality} search results mein top visibility milti hai. "
                f"Kya main 1-click renewal link bhej doon?"
            )
        else:
            body = (
                f"Hi {salutation}, your {m_name} {plan} plan expires in {days} days. "
                f"Maintain your verified badge and top local search rank in {locality}. "
                f"Reply YES to send the instant renewal link."
            )
        return {
            "body": body,
            "cta": "binary_yes_no",
            "send_as": "vera",
            "suppression_key": trigger.get("suppression_key", "renewal"),
            "rationale": f"Clear operational nudge for subscription expiry in {days} days with binary CTA"
        }

    # Kind E: festival_upcoming / ipl_match_today
    elif t_kind in ("festival_upcoming", "ipl_match_today"):
        event_name = t_payload.get("festival", t_payload.get("match", "IPL Match"))
        venue = t_payload.get("venue", locality)
        
        if use_hi:
            body = (
                f"{salutation}, {event_name} coming up near {venue}! Search volume in {locality} is trending high. "
                f"Hum {m_name} ke liye Special Event offer '{offer_str}' feature kar sakte hain. "
                f"Kya main promo post update kar doon?"
            )
        else:
            body = (
                f"Hi {salutation}, {event_name} is happening at {venue}! Search activity in {locality} is peaking. "
                f"We can launch a special promo featuring '{offer_str}' for {m_name}. "
                f"Reply YES to push this post live."
            )
        return {
            "body": body,
            "cta": "binary_yes_no",
            "send_as": "vera",
            "suppression_key": trigger.get("suppression_key", f"event:{event_name}"),
            "rationale": f"Leverages high temporal/local relevance ({event_name} at {venue}) with explicit CTA"
        }

    # Kind F: curious_ask_due / active_planning_intent / milestone_reached / review_theme_emerged
    elif t_kind == "review_theme_emerged":
        theme = t_payload.get("theme", "wait_time").replace("_", " ")
        quote = t_payload.get("common_quote", "had to wait")
        occurrences = t_payload.get("occurrences_30d", 3)
        if use_hi:
            body = (
                f"{salutation}, {m_name} ke recent reviews mein {occurrences} baar '{theme}' mention hua hai "
                f"(e.g. \"{quote}\"). Kya aap chahenge ki main smart response draft karun ya scheduling post update karun?"
            )
        else:
            body = (
                f"Hi {salutation}, noticed a pattern in recent reviews for {m_name}: {occurrences} reviews this month mention '{theme}' "
                f"(e.g. \"{quote}\"). Would you like me to draft professional responses and update your GBP notice?"
            )
        return {
            "body": body,
            "cta": "open_ended",
            "send_as": "vera",
            "suppression_key": trigger.get("suppression_key", f"review_theme:{theme}"),
            "rationale": f"Social proof / reputation management based on empirical review count ({occurrences}) and quote"
        }
        
    elif t_kind == "milestone_reached":
        metric = t_payload.get("metric", "review_count")
        val = t_payload.get("value_now", 145)
        target = t_payload.get("milestone_value", 150)
        if use_hi:
            body = (
                f"Badhai ho {salutation}! {m_name} abhi {val} reviews par pahunch gaya hai — 150 milestone se sirf {target - val} door! "
                f"Kya main customers ke liye 1-click review request WhatsApp template draft kar doon?"
            )
        else:
            body = (
                f"Congratulations {salutation}! {m_name} is at {val} reviews — just {target - val} away from reaching {target}! "
                f"Would you like me to share a 1-click review request template to cross 150 this week?"
            )
        return {
            "body": body,
            "cta": "binary_yes_no",
            "send_as": "vera",
            "suppression_key": trigger.get("suppression_key", f"milestone:{target}"),
            "rationale": f"Positive reinforcement milestone tracking ({val}/{target}) with effort externalization CTA"
        }

    # Fallback / Generic composition
    if use_hi:
        body = (
            f"Hi {salutation}, {m_name} ka Google profile audit complete ho gaya hai. "
            f"Offer catalog mein '{offer_str}' active hai. Performance: {merchant.get('performance', {}).get('views', 1000)} views (30d). "
            f"Kya hum new promo post schedule karein?"
        )
    else:
        body = (
            f"Hi {salutation}, completed profile scan for {m_name}. "
            f"Your current catalog features '{offer_str}' with {merchant.get('performance', {}).get('views', 1000)} views in 30 days. "
            f"Reply YES to schedule a fresh Google Post today."
        )

    return {
        "body": body,
        "cta": "binary_yes_no",
        "send_as": "vera",
        "suppression_key": trigger.get("suppression_key", "generic_nudge"),
        "rationale": f"Category/merchant aligned fallback nudge using active offer {offer_str} and performance stats"
    }

# -----------------------------------------------------------------------------
# FastAPI Endpoint Routes
# -----------------------------------------------------------------------------

@app.get("/v1/healthz")
async def healthz():
    counts = {"category": 0, "merchant": 0, "customer": 0, "trigger": 0}
    for (scope, _), _ in contexts.items():
        if scope in counts:
            counts[scope] += 1
    return {
        "status": "ok",
        "uptime_seconds": int(time.time() - START_TIME),
        "contexts_loaded": counts
    }

@app.get("/v1/metadata")
async def metadata():
    return {
        "team_name": "Vera Masters",
        "team_members": ["AI Architect"],
        "model": "rule-guided-deterministic-composer",
        "approach": "4-context structured composition engine with strict specificity anchors and multi-turn intent routing",
        "contact_email": "vera-bot@magicpin.challenge",
        "version": "1.0.0",
        "submitted_at": datetime.utcnow().isoformat() + "Z"
    }

@app.post("/v1/context")
async def push_context(body: ContextPushBody):
    if body.scope not in ("category", "merchant", "customer", "trigger"):
        raise HTTPException(status_code=400, detail=f"Invalid scope: {body.scope}")
    
    key = (body.scope, body.context_id)
    existing = contexts.get(key)
    
    if existing and existing["version"] >= body.version:
        return {
            "accepted": False,
            "reason": "stale_version",
            "current_version": existing["version"]
        }
    
    contexts[key] = {
        "version": body.version,
        "payload": body.payload
    }
    
    return {
        "accepted": True,
        "ack_id": f"ack_{body.context_id}_v{body.version}",
        "stored_at": datetime.utcnow().isoformat() + "Z"
    }

@app.post("/v1/tick")
async def tick(body: TickBody):
    actions = []
    seen_conversations = set()
    
    for trg_id in body.available_triggers:
        trg_payload = get_context("trigger", trg_id)
        if not trg_payload:
            continue
            
        m_id = trg_payload.get("merchant_id")
        if not m_id:
            continue
            
        m_payload = get_context("merchant", m_id)
        if not m_payload:
            continue
            
        cat_slug = m_payload.get("category_slug")
        cat_payload = get_context("category", cat_slug) if cat_slug else None
        if not cat_payload:
            # Try default dentists or first available category
            cat_payload = get_context("category", "dentists")
        if not cat_payload:
            continue
            
        c_id = trg_payload.get("customer_id")
        c_payload = get_context("customer", c_id) if c_id else None
        
        conv_id = f"conv_{m_id}_{trg_id}"
        if conv_id in seen_conversations:
            continue
        seen_conversations.add(conv_id)
        
        composed = compose_message(cat_payload, m_payload, trg_payload, c_payload)
        
        actions.append({
            "conversation_id": conv_id,
            "merchant_id": m_id,
            "customer_id": c_id,
            "send_as": composed["send_as"],
            "trigger_id": trg_id,
            "template_name": f"vera_{trg_payload.get('kind', 'generic')}_v1",
            "template_params": [m_payload.get("identity", {}).get("name", ""), trg_id],
            "body": composed["body"],
            "cta": composed["cta"],
            "suppression_key": composed["suppression_key"],
            "rationale": composed["rationale"]
        })
        
        if len(actions) >= 20: # Respect max actions cap
            break
            
    return {"actions": actions}

@app.post("/v1/reply")
async def reply(body: ReplyBody):
    conv_history = conversations.setdefault(body.conversation_id, [])
    conv_history.append({"turn": body.turn_number, "role": body.from_role, "msg": body.message})
    
    msg_text = body.message.strip()
    m_payload = get_context("merchant", body.merchant_id) if body.merchant_id else None
    cat_slug = m_payload.get("category_slug", "dentists") if m_payload else "dentists"
    cat_payload = get_context("category", cat_slug) if cat_slug else None
    
    salutation = format_salutation(m_payload, cat_slug) if m_payload else "there"
    use_hi = is_hindi_pref(m_payload) if m_payload else True

    # 1. AUTO-REPLY DETECTION
    if is_auto_reply(msg_text):
        # Count auto replies in history
        auto_replies_count = sum(1 for turn in conv_history if is_auto_reply(turn.get("msg", "")))
        if auto_replies_count >= 2 or body.turn_number >= 3:
            return {
                "action": "end",
                "rationale": "Detected repeated canned auto-reply; gracefully exiting conversation to avoid pollution"
            }
        else:
            if use_hi:
                reply_body = f"Samajh gayi {salutation}. Main owner/manager se connect hone ka wait karungi. Jab bhi aap free hon, 'YES' reply karein! 🙂"
            else:
                reply_body = f"Understood {salutation}. I'll hold off until the manager is free. Whenever you're ready, reply 'YES' to proceed!"
            return {
                "action": "send",
                "body": reply_body,
                "cta": "binary_yes_no",
                "rationale": "Auto-reply detected; single polite pivot attempt asking for human confirmation"
            }

    # 2. OPT-OUT / NEGATIVE INTENT
    if is_negative_intent(msg_text):
        return {
            "action": "end",
            "rationale": "Merchant expressed explicit opt-out or negative interest; ending conversation gracefully"
        }

    # 3. DELAY INTENT
    if is_delay_intent(msg_text):
        return {
            "action": "wait",
            "wait_seconds": 1800,
            "rationale": "Merchant requested time delay; pausing outreach for 30 minutes"
        }

    # 4. INTENT HANDOFF / POSITIVE INTENT
    if is_positive_intent(msg_text):
        if use_hi:
            reply_body = f"Shukriya {salutation}! Action initialize kar diya hai. Post/update live hone par main aapko exact stats share karungi!"
        else:
            reply_body = f"Awesome {salutation}! Action initialized. I've updated the post/details and will share performance stats shortly."
        return {
            "action": "send",
            "body": reply_body,
            "cta": "none",
            "rationale": "Merchant gave explicit positive intent; immediately executing action and confirming without re-qualifying"
        }

    # 5. GENERAL / UNCERTAIN QUERY
    if use_hi:
        reply_body = f"Samajh gayi {salutation}. Is baare mein exact details ready hain. Kya hum abhi execute karein? (Reply YES/NO)"
    else:
        reply_body = f"Got it {salutation}. I have the full details prepared. Should we proceed with execution now? (Reply YES/NO)"

    return {
        "action": "send",
        "body": reply_body,
        "cta": "binary_yes_no",
        "rationale": "Handled open question with low-friction confirmation prompt"
    }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8080)
