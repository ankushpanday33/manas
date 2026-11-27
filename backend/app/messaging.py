"""Delivery planner: for one decision, choose the messaging platform, the fallback, the language and script, and write
the message in the exact shape each channel needs (WhatsApp template, SMS segments, push title/body, in-app card).

Platform registry is config. Override it with MANAS_PROVIDERS_JSON (path to a JSON list with the same fields) and
switch platforms on by setting their credential env vars. Costs are illustrative defaults: set your contract rates.
Nothing is sent from here; `send_preview` builds the request a sender would make.
"""
from __future__ import annotations

import json
import os
import re
from typing import Any

PROVIDERS: list[dict[str, Any]] = [
    {"id": "meta_whatsapp", "name": "WhatsApp Cloud API (Meta)", "channel": "whatsapp", "cost_inr": 0.80,
     "env": ["WHATSAPP_TOKEN", "WHATSAPP_PHONE_NUMBER_ID"], "needs_template": True, "priority": 1},
    {"id": "gupshup_whatsapp", "name": "Gupshup WhatsApp", "channel": "whatsapp", "cost_inr": 0.90,
     "env": ["GUPSHUP_API_KEY", "GUPSHUP_APP_NAME"], "needs_template": True, "priority": 2},
    {"id": "twilio_whatsapp", "name": "Twilio WhatsApp", "channel": "whatsapp", "cost_inr": 1.10,
     "env": ["TWILIO_ACCOUNT_SID", "TWILIO_AUTH_TOKEN", "TWILIO_WHATSAPP_FROM"], "needs_template": True, "priority": 3},
    {"id": "msg91_sms", "name": "MSG91 SMS", "channel": "sms", "cost_inr": 0.20, "env": ["MSG91_AUTH_KEY", "MSG91_SENDER_ID"],
     "needs_template": True, "dlt": True, "priority": 1},
    {"id": "kaleyra_sms", "name": "Kaleyra SMS", "channel": "sms", "cost_inr": 0.22, "env": ["KALEYRA_API_KEY", "KALEYRA_SID"],
     "needs_template": True, "dlt": True, "priority": 2},
    {"id": "twilio_sms", "name": "Twilio SMS", "channel": "sms", "cost_inr": 0.60, "env": ["TWILIO_ACCOUNT_SID", "TWILIO_AUTH_TOKEN"],
     "needs_template": False, "dlt": True, "priority": 3},
    {"id": "fcm_push", "name": "Firebase Cloud Messaging", "channel": "push", "cost_inr": 0.0,
     "env": ["FCM_PROJECT_ID", "GOOGLE_APPLICATION_CREDENTIALS"], "priority": 1},
    {"id": "onesignal_push", "name": "OneSignal", "channel": "push", "cost_inr": 0.01, "env": ["ONESIGNAL_APP_ID", "ONESIGNAL_API_KEY"], "priority": 2},
    {"id": "clevertap_push", "name": "CleverTap", "channel": "push", "cost_inr": 0.02,
     "env": ["CLEVERTAP_ACCOUNT_ID", "CLEVERTAP_PASSCODE"], "priority": 3},
    {"id": "app_inbox", "name": "In-app inbox (your app)", "channel": "in_app", "cost_inr": 0.0, "env": [], "priority": 1},
    {"id": "exotel_voice", "name": "Exotel voice", "channel": "voice", "cost_inr": 1.50, "env": ["EXOTEL_SID", "EXOTEL_TOKEN"], "priority": 1},
    {"id": "sendgrid_email", "name": "SendGrid email", "channel": "email", "cost_inr": 0.05, "env": ["SENDGRID_API_KEY"], "priority": 1},
]
FALLBACK_CHANNEL = {"whatsapp": "sms", "push": "in_app", "in_app": "push", "sms": "whatsapp", "voice": "sms", "email": "in_app"}


def providers() -> list[dict[str, Any]]:
    path = os.environ.get("MANAS_PROVIDERS_JSON")
    items = json.loads(open(path, encoding="utf-8").read()) if path and os.path.exists(path) else PROVIDERS
    out = []
    for p in items:
        configured = all(os.environ.get(k) for k in p.get("env", []))
        out.append({**p, "configured": configured, "enabled": p.get("enabled", True)})
    return out


# ---------- language and script ----------
LANG_ALIASES = {"hindi": "Hindi", "hi": "Hindi", "english": "English", "en": "English", "marathi": "Marathi", "mr": "Marathi",
                "tamil": "Tamil", "ta": "Tamil", "bengali": "Bengali", "bangla": "Bengali", "bn": "Bengali", "telugu": "Telugu",
                "te": "Telugu", "gujarati": "Gujarati", "gu": "Gujarati", "kannada": "Kannada", "malayalam": "Malayalam", "punjabi": "Punjabi"}
LOCALE = {"English": "en-IN", "Hindi": "hi-IN", "Hinglish": "hi-Latn-IN", "Marathi": "mr-IN", "Tamil": "ta-IN", "Bengali": "bn-IN",
          "Telugu": "te-IN", "Gujarati": "gu-IN", "Kannada": "kn-IN", "Malayalam": "ml-IN", "Punjabi": "pa-IN"}
HINGLISH_WORDS = re.compile(r"\b(hai|hain|kya|kab|nahi|mera|meri|kaisa|kaise|karo|kar|hoga|hogi|chahiye|bahut|aaj|kal|paise|tension|pareshan|batao|rishta|shaadi|naukri)\b", re.I)
DEVANAGARI = re.compile(r"[ऀ-ॿ]")
NATIVE_SCRIPT = {"Tamil": r"[஀-௿]", "Bengali": r"[ঀ-৿]", "Telugu": r"[ఀ-౿]", "Gujarati": r"[઀-૿]",
                 "Kannada": r"[ಀ-೿]", "Malayalam": r"[ഀ-ൿ]", "Punjabi": r"[਀-੿]"}


def choose_language(preferred: str | None, texts: list[str], name: str | None = None) -> dict[str, Any]:
    """Language from the profile, script from how the person actually writes to us (and how their name is written)."""
    lang = LANG_ALIASES.get(str(preferred or "").strip().lower(), str(preferred or "English").strip().title() or "English")
    if name and DEVANAGARI.search(name):
        return {"language": lang if lang in {"Hindi", "Marathi"} else "Hindi", "template_language": "Hindi", "script": "Devanagari",
                "locale": "hi-IN", "why": "their name is written in Devanagari, so the whole message is too"}
    joined = " ".join(texts)
    dev = len(DEVANAGARI.findall(joined))
    roman_hindi = len(HINGLISH_WORDS.findall(joined))
    if lang in {"Hindi", "Marathi"} and dev >= 5:
        key, script, why = lang, "Devanagari", f"profile says {lang} and they write in Devanagari"
    elif roman_hindi >= 2 and lang in {"Hindi", "English", "Marathi", "Punjabi"}:
        key, script, why = "Hinglish", "Latin", f"they write Hindi in Roman letters ({roman_hindi} Hinglish words in their chats)"
    elif lang in NATIVE_SCRIPT and re.search(NATIVE_SCRIPT[lang], joined):
        key, script, why = lang, "native", f"profile says {lang} and they write in its script"
    elif lang == "Hindi":
        key, script, why = "Hindi", "Devanagari", "profile says Hindi"
    elif lang == "English":
        key, script, why = "English", "Latin", "profile says English"
    else:
        key, script, why = lang, "native", f"profile says {lang}"
    return {"language": lang, "template_language": key, "script": script, "locale": LOCALE.get(key, "en-IN"), "why": why}


# ---------- localized templates ----------
# {name} {nakshatra} {topic} {planet} {planet_name} {radical} {astrologer} {title} {name_number} {checkout_item} {link}
TEMPLATES: dict[str, dict[str, str]] = {
    "daily_horoscope": {
        "English": "{name}, today's guidance for {nakshatra} Nakshatra is ready. A calm look at your day: {link}",
        "Hindi": "{name}, {nakshatra} नक्षत्र के लिए आज का मार्गदर्शन तैयार है। अपने दिन पर एक शांत नज़र: {link}",
        "Hinglish": "{name}, {nakshatra} Nakshatra ke liye aaj ka guidance ready hai. Apne din par ek shaant nazar: {link}",
    },
    "topic_reading": {
        "English": "{name}, a {topic} reading based on your chart ({planet} as your ruling planet) is ready for you: {link}",
        "Hindi": "{name}, आपकी कुंडली ({planet} आपका स्वामी ग्रह) पर आधारित {topic} रीडिंग तैयार है: {link}",
        "Hinglish": "{name}, aapki kundli ({planet} aapka ruling planet) par based {topic} reading ready hai: {link}",
    },
    "astrologer_consult": {
        "English": "{name}, {astrologer} specialises in {planet} charts like yours. First 5 minutes free: {link}",
        "Hindi": "{name}, {astrologer} आप जैसी {planet} कुंडलियों के विशेषज्ञ हैं। पहले 5 मिनट मुफ़्त: {link}",
        "Hinglish": "{name}, {astrologer} aap jaisi {planet} kundliyon ke expert hain. Pehle 5 minute free: {link}",
    },
    "planet_puja": {
        "English": "{name}, a {planet_name} puja is traditionally associated with your Radical number {radical}. Book with a temple partner: {link}",
        "Hindi": "{name}, आपके मूलांक {radical} से परंपरागत रूप से {planet_name} पूजा जुड़ी है। मंदिर पार्टनर के साथ बुक करें: {link}",
        "Hinglish": "{name}, aapke Mulank {radical} se paramparik roop se {planet_name} puja judi hai. Temple partner ke saath book karein: {link}",
    },
    "personality_report": {
        "English": "{name}, your Birth Panchang personality: {title}. Five dimensions, with the proof: {link}",
        "Hindi": "{name}, आपकी जन्म पंचांग पर्सनैलिटी: {title}। पाँच पहलू, प्रमाण के साथ: {link}",
        "Hinglish": "{name}, aapki Birth Panchang personality: {title}. Paanch pehlu, proof ke saath: {link}",
    },
    "name_correction": {
        "English": "{name}, curious how a spelling changes your Name number ({name_number} today)? Compare spellings side by side: {link}",
        "Hindi": "{name}, जानना चाहेंगे कि स्पेलिंग बदलने से आपका नामांक ({name_number}) कैसे बदलता है? तुलना करें: {link}",
        "Hinglish": "{name}, jaanna chahenge ki spelling badalne se aapka Namank ({name_number}) kaise badalta hai? Compare karein: {link}",
    },
    "resume_checkout": {
        "English": "{name}, you left {checkout_item} halfway. It is saved for you whenever you are ready, no rush: {link}",
        "Hindi": "{name}, आपका {checkout_item} अधूरा रह गया था। जब चाहें पूरा करें, कोई जल्दी नहीं: {link}",
        "Hinglish": "{name}, aapka {checkout_item} adhoora reh gaya tha. Jab chahein poora karein, koi jaldi nahi: {link}",
    },
    # Manas packs
    "gentle": {"English": "Namaste {name}, your EMI of {amount} is pending. Pay securely here: {link}",
               "Hindi": "नमस्ते {name}, आपकी {amount} की EMI बाकी है। यहाँ सुरक्षित भुगतान करें: {link}",
               "Hinglish": "Namaste {name}, aapki {amount} ki EMI baaki hai. Yahan surakshit payment karein: {link}"},
    "firm": {"English": "{name}, your EMI of {amount} is {dpd} days overdue. Please pay today to avoid charges: {link}",
             "Hindi": "{name}, आपकी {amount} की EMI {dpd} दिन से बकाया है। शुल्क से बचने के लिए आज भुगतान करें: {link}",
             "Hinglish": "{name}, aapki {amount} ki EMI {dpd} din se overdue hai. Charges se bachne ke liye aaj payment karein: {link}"},
    "empathetic_plan": {"English": "{name}, we understand delays happen. Pay {amount} after your salary credit, or pick a plan that suits you: {link}",
                        "Hindi": "{name}, हम समझते हैं कि देर हो जाती है। सैलरी आने के बाद {amount} भरें, या अपने हिसाब का प्लान चुनें: {link}",
                        "Hinglish": "{name}, hum samajhte hain der ho jaati hai. Salary aane ke baad {amount} bharein, ya apne hisaab ka plan chunein: {link}"},
    "reminder": {"English": "Hi {name}, your {plan} plan renews on {date}. Keep enjoying without a break: {link}",
                 "Hindi": "नमस्ते {name}, आपका {plan} प्लान {date} को रिन्यू होगा। बिना रुकावट आनंद लेते रहें: {link}",
                 "Hinglish": "Hi {name}, aapka {plan} plan {date} ko renew hoga. Bina break enjoy karte rahein: {link}"},
    "value_recap": {"English": "{name}, you enjoyed {minutes} minutes of {top_content} this month. Renew {plan} to keep it going: {link}",
                    "Hindi": "{name}, इस महीने आपने {minutes} मिनट {top_content} का आनंद लिया। जारी रखने के लिए {plan} रिन्यू करें: {link}",
                    "Hinglish": "{name}, is mahine aapne {minutes} minute {top_content} enjoy kiya. Jaari rakhne ke liye {plan} renew karein: {link}"},
    "offer": {"English": "{name}, renew {plan} today and get an extra month free. Offer ends {date}: {link}",
              "Hindi": "{name}, आज {plan} रिन्यू करें और एक महीना मुफ़्त पाएँ। ऑफ़र {date} तक: {link}",
              "Hinglish": "{name}, aaj {plan} renew karein aur ek mahina free paayein. Offer {date} tak: {link}"},
}
PUSH_TITLES = {"English": "For you today", "Hindi": "आज आपके लिए", "Hinglish": "Aaj aapke liye"}


# English fallbacks in the values, said properly in other languages.
LOCAL_DEFAULTS = {
    "an astrologer": {"Hindi": "हमारे ज्योतिषी", "Hinglish": "Hamare astrologer"},
    "your": {"Hindi": "आपके", "Hinglish": "aapke"},
    "life": {"Hindi": "जीवन", "Hinglish": "life"},
    "your profile": {"Hindi": "आपकी प्रोफ़ाइल", "Hinglish": "aapki profile"},
    "your booking": {"Hindi": "आपकी बुकिंग", "Hinglish": "aapki booking"},
    "your favourites": {"Hindi": "आपकी पसंद", "Hinglish": "aapki pasand"},
}


class _Safe(dict):
    def __missing__(self, key: str) -> str:
        return ""


def _gsm(text: str) -> bool:
    return all(ord(c) < 128 or c in "₹" for c in text) and "₹" not in text


def compose(offer: str, lang_key: str, values: dict[str, Any], channel: str) -> dict[str, Any]:
    tpl = TEMPLATES.get(offer, {})
    # Closest available template: Marathi readers read Devanagari Hindi; Punjabi speakers often read Hinglish.
    nearest = {"Marathi": "Hindi", "Punjabi": "Hinglish"}.get(lang_key, "English")
    used = lang_key if lang_key in tpl else (nearest if nearest in tpl else "English")
    local = {k: LOCAL_DEFAULTS.get(v, {}).get(used, v) if isinstance(v, str) else v for k, v in values.items()}
    body = re.sub(r"\s{2,}", " ", tpl.get(used, "").format_map(_Safe(local))).replace(" ,", ",").replace("()", "").strip()
    body = re.sub(r"\(\s*\)", "", body).replace("  ", " ")
    out: dict[str, Any] = {"template_language": used, "body": body,
                           "translation_needed": used != lang_key,
                           "note": None if used == lang_key else f"No {lang_key} template yet: sent in {used}. Add one, or turn on Claude to translate."}
    if channel == "whatsapp":
        out["whatsapp_template"] = {"name": f"{offer}_{LOCALE.get(used, 'en-IN').replace('-', '_').lower()}",
                                    "language": LOCALE.get(used, "en-IN").split("-")[0], "body_params": [str(values.get("name", ""))]}
    elif channel == "sms":
        unicode_ = not _gsm(body)
        per = 70 if unicode_ else 160
        out["sms"] = {"encoding": "UCS-2 (Unicode)" if unicode_ else "GSM-7", "chars": len(body),
                      "segments": max(1, -(-len(body) // per)), "dlt_template_id": f"DLT-{offer.upper()}-{used[:2].upper()}",
                      "note": "Unicode SMS costs about 2.3x per character: keep regional copy short" if unicode_ else None}
    elif channel == "push":
        out["push"] = {"title": PUSH_TITLES.get(used, "For you today"), "body": body[:178]}
    elif channel == "in_app":
        out["in_app"] = {"title": PUSH_TITLES.get(used, "For you today"), "body": body, "cta": "Open"}
    return out


def delivery_rates(comm_rows: list[dict[str, Any]]) -> dict[str, float]:
    """Per provider delivery rate from history (rows may carry a 'provider' column)."""
    seen: dict[str, list[int]] = {}
    for r in comm_rows:
        if r.get("direction", "out") == "out" and r.get("provider"):
            ok = str(r.get("status", "")).lower() in {"delivered", "read", "answered"}
            seen.setdefault(r["provider"], []).append(int(ok))
    return {k: sum(v) / len(v) for k, v in seen.items() if len(v) >= 5}


def choose_provider(channel: str, rates: dict[str, float], exclude: set[str] | None = None) -> dict[str, Any] | None:
    cands = [p for p in providers() if p["channel"] == channel and p["enabled"] and p["id"] not in (exclude or set())]
    if not cands:
        return None

    def score(p: dict[str, Any]) -> float:
        return (2.0 if p["configured"] else 0) + rates.get(p["id"], 0.9) * 2 - p["cost_inr"] * 0.5 - p.get("priority", 5) * 0.05

    best = max(cands, key=score)
    why = [("credentials configured" if best["configured"] else "not configured yet: set " + ", ".join(best["env"]) if best["env"] else "built in"),
           (f"delivery rate {rates[best['id']]:.0%} in your history" if best["id"] in rates else "no delivery history yet: default rate"),
           f"about ₹{best['cost_inr']:.2f} per message (illustrative)"]
    return {**{k: best[k] for k in ("id", "name", "channel", "cost_inr", "configured")}, "why": "; ".join(why)}


def plan(channel: str, offer: str, preferred_language: str | None, texts: list[str], values: dict[str, Any],
         comm_rows: list[dict[str, Any]], allowed_channels: set[str]) -> dict[str, Any]:
    lang = choose_language(preferred_language, texts, str(values.get("name") or ""))
    rates = delivery_rates(comm_rows)
    primary = choose_provider(channel, rates)
    fb_channel = FALLBACK_CHANNEL.get(channel)
    fallback = choose_provider(channel, rates, exclude={primary["id"]}) if primary else None
    fallback_channel = None
    if fb_channel in allowed_channels:
        fallback_channel = {"channel": fb_channel, "provider": choose_provider(fb_channel, rates),
                            "rule": f"if {channel} is not delivered in 2 hours, try {fb_channel} once; a reply anywhere stops the rest"}
    msg = compose(offer, lang["template_language"], values, channel)
    fb_msg = compose(offer, lang["template_language"], values, fb_channel) if fallback_channel else None
    return {"channel": channel, "provider": primary, "same_channel_backup": fallback, "fallback": fallback_channel,
            "language": lang, "message": msg, "fallback_message": fb_msg, "preview": send_preview(primary, msg, values)}


def send_preview(provider: dict[str, Any] | None, msg: dict[str, Any], values: dict[str, Any]) -> dict[str, Any] | None:
    """The request a sender would make. Secrets are never included."""
    if not provider:
        return None
    pid = provider["id"]
    if pid == "meta_whatsapp":
        t = msg.get("whatsapp_template", {})
        return {"method": "POST", "url": "https://graph.facebook.com/{version}/{WHATSAPP_PHONE_NUMBER_ID}/messages",
                "json": {"messaging_product": "whatsapp", "to": "{user_phone}", "type": "template",
                         "template": {"name": t.get("name"), "language": {"code": t.get("language")},
                                      "components": [{"type": "body", "parameters": [{"type": "text", "text": p} for p in t.get("body_params", [])]}]}}}
    if pid == "fcm_push":
        return {"method": "POST", "url": "https://fcm.googleapis.com/v1/projects/{FCM_PROJECT_ID}/messages:send",
                "json": {"message": {"token": "{device_token}", "notification": msg.get("push", {})}}}
    if pid == "app_inbox":
        return {"method": "POST", "url": "{your_app_api}/inbox", "json": {"user": "{customer_id}", **msg.get("in_app", {})}}
    return {"adapter": pid, "note": "payload shape depends on your account setup; wire this adapter when you enable the platform",
            "body": msg["body"]}
