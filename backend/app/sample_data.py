"""Synthetic demo data. Every person here is fictional; behaviour archetypes are planted so the brain has patterns to find."""
from __future__ import annotations

import random
from datetime import date, datetime, time, timedelta
from typing import Any

FIRST = ["Aarav", "Priya", "Rohit", "Sneha", "Vikram", "Anjali", "Karan", "Pooja", "Arjun", "Neha", "Rahul", "Kavya",
         "Suresh", "Meena", "Imran", "Fatima", "Ravi", "Lakshmi", "Deepak", "Sunita", "Manoj", "Asha", "Nikhil", "Divya",
         "Sanjay", "Rekha", "Amit", "Geeta", "Harsh", "Nisha", "Tarun", "Swati", "Gaurav", "Ritu", "Ajay", "Bhavna"]
LAST = ["Sharma", "Verma", "Patel", "Iyer", "Reddy", "Khan", "Singh", "Das", "Nair", "Joshi", "Gupta", "Mehta",
        "Kulkarni", "Banerjee", "Pillai", "Yadav", "Chauhan", "Rao", "Mishra", "Shaikh"]
CITY_LANG = [("Lucknow", "Hindi"), ("Patna", "Hindi"), ("Jaipur", "Hindi"), ("Pune", "Marathi"), ("Nagpur", "Marathi"),
             ("Chennai", "Tamil"), ("Kolkata", "Bengali"), ("Hyderabad", "Telugu"), ("Bengaluru", "English"),
             ("Mumbai", "Hindi"), ("Indore", "Hindi"), ("Ahmedabad", "Gujarati")]


def _at(d: date, hour: int, rng: random.Random) -> str:
    return datetime.combine(d, time(hour, rng.randint(0, 59))).isoformat(timespec="seconds")


def _customer(i: int, prefix: str, rng: random.Random, **over: Any) -> dict[str, Any]:
    city, lang = rng.choice(CITY_LANG)
    c = {"customer_id": f"{prefix}-{i:04d}", "name": f"{rng.choice(FIRST)} {rng.choice(LAST)}",
         "phone": f"9{rng.randint(100000000, 999999999)}", "preferred_language": lang, "city": city,
         "consent_whatsapp": "yes" if rng.random() < 0.9 else "no", "consent_sms": "yes",
         "consent_voice": "yes" if rng.random() < 0.8 else "no", "dnd": "yes" if rng.random() < 0.1 else "no"}
    c.update(over)
    return c


# archetype -> (weight, {channel: (window_hours, read_p, reply_p)}, on_time_p, keep_p, dpd_range, note)
EMI_ARCH = {
    "reliable_salary": (30, {"whatsapp": ((17, 19), 0.85, 0.35), "sms": ((9, 11), 0.3, 0.02)}, 0.82, 0.9, (5, 15),
                        ["salary late this month, will pay after the 5th", "salary aayi nahi abhi, 5 tarikh ke baad pay kar dunga",
                         "salary credit late hai, will pay after the 7th"]),
    "evening_whatsapp": (20, {"whatsapp": ((17, 19), 0.9, 0.25), "sms": ((8, 10), 0.15, 0.0)}, 0.7, 0.75, (8, 25),
                         ["busy in day, call me after 6pm", "shaam ko baat karo please", "whatsapp pe message karo, call mat karo"]),
    "hard_to_reach": (15, {"voice": ((13, 16), 0.45, 0.0), "whatsapp": ((10, 12), 0.2, 0.03), "sms": ((10, 12), 0.1, 0.0)}, 0.5, 0.4, (25, 60),
                      ["customer not reachable, voice mail full", "phone switched off twice"]),
    "disputer": (7, {"whatsapp": ((12, 15), 0.7, 0.4), "sms": ((10, 12), 0.4, 0.05)}, 0.6, 0.5, (30, 70),
                 ["customer says wrong charge, already paid via UPI", "dispute: bounce charge galat laga hai"]),
    "hardship": (8, {"whatsapp": ((17, 19), 0.6, 0.3), "voice": ((12, 15), 0.5, 0.0)}, 0.55, 0.5, (35, 80),
                 ["job lost last month, will pay next month", "father in hospital, medical expenses, kuch time chahiye"]),
    "chronic": (10, {"sms": ((9, 12), 0.3, 0.0), "voice": ((14, 16), 0.3, 0.0), "whatsapp": ((14, 16), 0.3, 0.02)}, 0.3, 0.15, (60, 120),
                ["promised again, will pay tomorrow", "kal pakka de dunga"]),
    "self_cure": (10, {"whatsapp": ((9, 11), 0.5, 0.05), "sms": ((9, 11), 0.4, 0.0)}, 0.95, 1.0, (1, 4), [""]),
}
REPLIES = {"reliable_salary": ["ok will pay after salary", "haan 5 ke baad kar dunga"],
           "evening_whatsapp": ["ok", "paying tonight", "call me after 6pm"],
           "disputer": ["I already paid this, wrong charge", "ye charge galat hai"],
           "hardship": ["lost my job, please give me time", "abhi paise nahi hai, next month"],
           "hard_to_reach": ["ok"], "chronic": ["kal de dunga"], "self_cure": ["done"]}


def emi_dataset(n: int = 120, seed: int = 42, today: date | None = None) -> dict[str, list[dict[str, Any]]]:
    rng = random.Random(seed)
    today = today or date.today()
    names, weights = zip(*[(k, v[0]) for k, v in EMI_ARCH.items()])
    data: dict[str, list[dict[str, Any]]] = {k: [] for k in ("customers", "loans", "payments", "promises", "communications")}
    pid = cid_ = prid = 0
    for i in range(1, n + 1):
        arch = rng.choices(names, weights)[0]
        _, chans, on_time_p, keep_p, dpd_rng, notes = EMI_ARCH[arch]
        cust = _customer(i, "CUST", rng, consent_voice="yes" if "voice" in chans else rng.choice(["yes", "no"]))
        cust["_archetype"] = arch
        data["customers"].append(cust)
        emi = rng.choice([2100, 3450, 4200, 5600, 7800, 9200])
        dpd = rng.randint(*dpd_rng)
        loan_id = f"LN-{i:04d}"
        note = rng.choice(notes)
        data["loans"].append({"loan_id": loan_id, "customer_id": cust["customer_id"], "emi_amount": emi,
                              "overdue_amount": emi * (1 + dpd // 31), "days_past_due": dpd,
                              "collections_note": note, "note_date": (today - timedelta(days=rng.randint(2, 8))).isoformat() if note else ""})

        # 12 monthly cycles: a reminder goes out; a responsive slot pulls the payment within 1 to 2 days.
        for m in range(12, 0, -1):
            due = today - timedelta(days=30 * m)
            if due > today - timedelta(days=dpd):
                continue
            sends = []
            for ch, ((h0, h1), read_p, reply_p) in chans.items():
                if rng.random() < 0.8:
                    sent_day = due + timedelta(days=rng.randint(0, 3))
                    hour = rng.randint(h0, h1 - 1) if rng.random() < 0.7 else rng.choice([9, 11, 14, 16, 18])
                    good = h0 <= hour < h1
                    read = rng.random() < (read_p if good else read_p * 0.3)
                    status = ("answered" if ch == "voice" else "read") if read else ("delivered" if rng.random() < 0.85 else "failed")
                    cid_ += 1
                    data["communications"].append({"comm_id": f"CM-{cid_:06d}", "customer_id": cust["customer_id"], "channel": ch,
                                                   "sent_at": _at(sent_day, hour, rng), "status": status, "direction": "out", "reply_text": ""})
                    sends.append((sent_day, read and good))
                    if read and rng.random() < reply_p:
                        cid_ += 1
                        data["communications"].append({"comm_id": f"CM-{cid_:06d}", "customer_id": cust["customer_id"], "channel": ch,
                                                       "sent_at": _at(sent_day, min(hour + 1, 21), rng), "status": "received", "direction": "in",
                                                       "reply_text": rng.choice(REPLIES[arch])})
            on_time = rng.random() < on_time_p
            responsive = [d for d, ok in sends if ok]
            paid = (responsive[0] + timedelta(days=rng.randint(0, 2))) if responsive and not on_time else due + timedelta(days=0 if on_time else rng.randint(4, 12))
            if arch == "chronic" and rng.random() < 0.4:
                continue
            pid += 1
            data["payments"].append({"payment_id": f"PY-{pid:06d}", "customer_id": cust["customer_id"], "loan_id": loan_id,
                                     "amount": emi, "paid_at": _at(paid, rng.randint(10, 22), rng),
                                     "method": rng.choice(["UPI", "UPI", "UPI", "NACH", "cash", "netbanking"]), "on_time": "yes" if on_time else "no"})

        for k in range(rng.randint(1, 4)):
            prid += 1
            made = today - timedelta(days=rng.randint(20, 300))
            data["promises"].append({"promise_id": f"PR-{prid:05d}", "customer_id": cust["customer_id"], "loan_id": loan_id,
                                     "promised_amount": emi, "made_on": made.isoformat(), "promised_date": (made + timedelta(days=5)).isoformat(),
                                     "status": "kept" if rng.random() < keep_p else "broken"})
        if arch in {"reliable_salary", "chronic"} and rng.random() < 0.25:
            prid += 1
            data["promises"].append({"promise_id": f"PR-{prid:05d}", "customer_id": cust["customer_id"], "loan_id": loan_id,
                                     "promised_amount": emi, "made_on": (today - timedelta(days=1)).isoformat(),
                                     "promised_date": (today + timedelta(days=rng.randint(2, 6))).isoformat(), "status": "open"})
    return data


SUB_ARCH = {
    "loyal_auto": (25, "yes", (40, 90), 0.0, ["music", "podcasts"], {"push": ((19, 21), 0.6, 0.05), "whatsapp": ((19, 21), 0.7, 0.1)}),
    "binge_drifting": (20, "no", (20, 60), -0.5, ["movies", "web series"], {"whatsapp": ((20, 21), 0.6, 0.15), "push": ((20, 21), 0.4, 0.0)}),
    "price_sensitive": (20, "no", (10, 30), -0.1, ["music"], {"sms": ((10, 12), 0.4, 0.05), "whatsapp": ((12, 15), 0.5, 0.2)}),
    "engaged_manual": (20, "no", (50, 120), 0.3, ["web series", "movies", "music"], {"whatsapp": ((18, 20), 0.85, 0.3), "push": ((18, 20), 0.5, 0.0)}),
    "dormant": (15, "no", (0, 5), -0.8, ["music"], {"sms": ((10, 12), 0.1, 0.0), "push": ((19, 21), 0.05, 0.0)}),
}
SUB_REPLIES = {"price_sensitive": ["bahut mehenga hai", "any discount?"], "engaged_manual": ["will renew tonight", "ok renewing"],
               "binge_drifting": ["not watching much these days"], "loyal_auto": ["thanks"], "dormant": ["stop"]}


def subscription_dataset(n: int = 120, seed: int = 7, today: date | None = None) -> dict[str, list[dict[str, Any]]]:
    rng = random.Random(seed)
    today = today or date.today()
    names, weights = zip(*[(k, v[0]) for k, v in SUB_ARCH.items()])
    data: dict[str, list[dict[str, Any]]] = {k: [] for k in ("customers", "subscriptions", "usage", "communications")}
    uid = cid_ = sid = 0
    for i in range(1, n + 1):
        arch = rng.choices(names, weights)[0]
        _, auto, mins, trend, content, chans = SUB_ARCH[arch]
        cust = _customer(i, "SUBS", rng)
        cust["_archetype"] = arch
        data["customers"].append(cust)
        plan, price = rng.choice([("Gold Monthly", 99), ("Gold Quarterly", 249), ("Platinum Monthly", 299), ("Platinum Annual", 999)])
        tenure = rng.randint(1, 6)
        renew_next = today + timedelta(days=rng.randint(1, 12))
        for k in range(tenure, -1, -1):
            sid += 1
            start = renew_next - timedelta(days=30 * (k + 1))
            good_read = False
            # Two reminders per cycle (day 25 and day 28) on each channel the person uses.
            for ch, ((h0, h1), read_p, reply_p) in chans.items():
                for offset in (25, 28):
                    sent_day = start + timedelta(days=offset)
                    if sent_day >= today or rng.random() > 0.85:
                        continue
                    hour = rng.randint(h0, h1 - 1) if rng.random() < 0.6 else rng.choice([10, 13, 16, 19])
                    in_window = h0 <= hour < h1
                    read = rng.random() < (read_p if in_window else read_p * 0.3)
                    good_read = good_read or (read and in_window)
                    cid_ += 1
                    data["communications"].append({"comm_id": f"SC-{cid_:06d}", "customer_id": cust["customer_id"], "channel": ch,
                                                   "sent_at": _at(sent_day, hour, rng), "status": "read" if read else "delivered", "direction": "out", "reply_text": ""})
                    if read and rng.random() < reply_p:
                        cid_ += 1
                        data["communications"].append({"comm_id": f"SC-{cid_:06d}", "customer_id": cust["customer_id"], "channel": ch,
                                                       "sent_at": _at(sent_day, min(hour + 1, 21), rng), "status": "received", "direction": "in",
                                                       "reply_text": rng.choice(SUB_REPLIES[arch])})
            # Auto-renew always renews on time; everyone else renews on time mostly when a reminder landed in their slot.
            on_time = auto == "yes" or rng.random() < (0.8 if good_read else 0.2)
            renewed = start + timedelta(days=30 - rng.randint(0, 2) if on_time else 30 + rng.randint(5, 15))
            data["subscriptions"].append({"sub_id": f"SB-{sid:05d}", "customer_id": cust["customer_id"], "plan": plan, "price": price,
                                          "renews_on": (start + timedelta(days=30)).isoformat(), "auto_renew": auto,
                                          "status": "active" if k == 0 else "renewed",
                                          "renewed_on": renewed.isoformat() if k > 0 else ""})
        for d in range(60, 0, -1):
            factor = 1 + trend * (1 - d / 60)
            if rng.random() < (0.6 if arch != "dormant" else 0.05) * max(factor, 0.1):
                uid += 1
                data["usage"].append({"usage_id": f"US-{uid:06d}", "customer_id": cust["customer_id"], "date": (today - timedelta(days=d)).isoformat(),
                                      "minutes": max(1, int(rng.randint(*mins) * max(factor, 0.1)) if mins[1] else 1), "content_type": rng.choice(content)})
    return data


# In-app events per archetype: (daily rate, chance a session reaches the CTA, chance a started payment completes,
# CTAs, screens, trend). trend "down" puts most events in the older half of the month.
EVENT_PROFILE = {
    "reliable_salary": (0.4, 0.5, 0.7, ["pay_now"], ["dues", "loan_details"], None),
    "evening_whatsapp": (0.35, 0.45, 0.5, ["pay_now"], ["dues"], None),
    "hard_to_reach": (0.08, 0.3, 0.2, ["pay_now"], ["dues"], "down"),
    "disputer": (0.2, 0.4, 0.1, ["talk_to_agent", "raise_dispute"], ["statement", "dues"], None),
    "hardship": (0.25, 0.5, 0.15, ["view_plan", "talk_to_agent"], ["restructure", "dues"], None),
    "chronic": (0.15, 0.3, 0.1, ["pay_now"], ["dues"], "down"),
    "self_cure": (0.3, 0.6, 0.9, ["pay_now"], ["dues"], None),
    "loyal_auto": (0.6, 0.15, 0.9, ["renew_now"], ["home", "player"], None),
    "binge_drifting": (0.25, 0.2, 0.3, ["renew_now"], ["player", "home"], "down"),
    "price_sensitive": (0.4, 0.5, 0.3, ["view_plans", "apply_offer"], ["plans", "home"], None),
    "engaged_manual": (0.5, 0.4, 0.6, ["renew_now"], ["player", "plans"], None),
    "dormant": (0.03, 0.1, 0.1, ["renew_now"], ["home"], "down"),
}


def add_events(data: dict[str, list[dict[str, Any]]], pack: str, seed: int, today: date | None = None) -> dict[str, list[dict[str, Any]]]:
    rng = random.Random(seed + 101)
    today = today or date.today()
    pay = pack == "emi_collection"
    names = {"paywall": "viewed_payment_page" if pay else "viewed_plans", "start": "started_payment" if pay else "started_checkout",
             "abandon": "abandoned_payment" if pay else "abandoned_checkout", "done": "completed_payment" if pay else "completed_purchase"}
    data["events"], eid = [], 0
    for cust in data["customers"]:
        rate, cta_p, done_p, ctas, screens, trend = EVENT_PROFILE[cust["_archetype"]]
        for d in range(30, 0, -1):
            r = rate * ((1.8 if d > 15 else 0.2) if trend == "down" else 1)
            if rng.random() > r:
                continue
            day, h = today - timedelta(days=d), rng.randint(9, 21)
            seq = [("app_open", "", ""), ("viewed_screen", rng.choice(screens), "")]
            if rng.random() < 0.25:
                seq += [("viewed_login", "login", ""), ("interacted_login", "login", "")]
                if rng.random() < 0.75:
                    seq.append(("completed_login", "login", ""))
            if rng.random() < cta_p:
                cta = rng.choice(ctas)
                seq += [("clicked_cta", "home", cta), (names["paywall"], "payment", cta)]
                if rng.random() < 0.5:
                    seq += [(names["start"], "payment", cta), (names["done"] if rng.random() < done_p else names["abandon"], "payment", cta)]
            for name, screen, cta in seq:
                eid += 1
                data["events"].append({"event_id": f"EV-{eid:06d}", "customer_id": cust["customer_id"], "at": _at(day, h, rng),
                                       "event_name": name, "screen": screen, "cta": cta})
    return data


DATASETS = {
    "emi_collection": lambda n=120, seed=42, today=None: add_events(emi_dataset(n, seed, today), "emi_collection", seed, today),
    "subscription_renewal": lambda n=120, seed=7, today=None: add_events(subscription_dataset(n, seed, today), "subscription_renewal", seed, today),
}
ID_FIELDS = {
    "events": "event_id",
    "customers": "customer_id", "loans": "loan_id", "payments": "payment_id", "promises": "promise_id",
    "communications": "comm_id", "subscriptions": "sub_id", "usage": "usage_id",
}
