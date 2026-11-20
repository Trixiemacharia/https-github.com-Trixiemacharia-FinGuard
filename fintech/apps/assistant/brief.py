"""Decision briefs, deterministic answer templates, and the LLM number check.

A brief holds only computed aggregates, dates, codes and text written in this module. It never contains transaction
descriptions, recipient names, phone numbers, calendar titles or goal names, so it is safe to hand to the language
provider.
"""
from __future__ import annotations

import re
from datetime import date
from decimal import Decimal, InvalidOperation

SCOPE_NOTE = "This analysis covers your FinGuard wallet only, not cash or other accounts."

MISSING_INPUT_TEXT = {
    "expected_income": "No expected income is recorded. Add your salary or other income in the Financial Calendar to "
                       "improve this estimate.",
    "housing_cost": "No rent or housing cost is recorded. If you pay rent, add it in the Financial Calendar; until then "
                    "it is not deducted.",
}


def money(currency, value):
    return f"{currency} {Decimal(value):,.2f}"


def _d(value):
    return value.isoformat() if isinstance(value, date) else value


# --- brief construction -----------------------------------------------------------------------------------------

def build_brief(intent, data):
    if intent in ("afford_purchase", "trip_affordability"):
        figures = {k: data[k] for k in ("amount", "balance", "confirmed_obligations", "authorized_savings_due",
                                         "projected_spending", "buffer", "result", "weekly_average_spend")}
        figures.update({"with_expected_income": data["scenarios"]["with_expected_income"],
                        "range_low": data["uncertainty_range"]["low"], "range_high": data["uncertainty_range"]["high"],
                        "horizon_days": data["horizon_days"], "weeks_of_history": data["data_quality"]["weeks_of_history"],
                        "unconfirmed_recurring_total": data["unconfirmed_recurring_total"],
                        "known_left": data["known_left"]})
        if intent == "trip_affordability":
            figures["monthly_set_aside_needed"] = data["monthly_set_aside_needed"]
        dates = {"horizon_end": _d(data["horizon_end"]), "next_income_date": _d(data["next_income_date"])}
        return _brief(intent, data, figures, dates, recommendation=data["recommendation"],
                      details={"horizon_basis": data["horizon_basis"], "formula": data["formula"],
                               "certain_shortfall": data["certain_shortfall"]})
    if intent == "savings_capacity":
        figures = {k: data[k] for k in ("expected_income", "essentials", "projected_spending", "buffer", "capacity",
                                         "already_committed_savings", "additional_capacity", "weekly_average_spend")}
        figures.update({"horizon_days": data["horizon_days"], "weeks_of_history": data["data_quality"]["weeks_of_history"],
                        "active_goals": len(data["goals"])})
        return _brief(intent, data, figures, {}, details={"formula": data["formula"]})
    if intent == "spending_breakdown":
        figures = {"total": data["total"], "transaction_count": data["transaction_count"],
                   "unusual_count": len(data["unusual"]), "weeks_of_history": data["weeks_of_history"]}
        details = {
            "period": data["period"], "category_filter": data["category_filter"],
            "categories": [{"category": c["category"], "amount": c["amount"], "share_percent": c["share_percent"]} for c in data["categories"]],
            "unusual": [{k: v for k, v in item.items() if k != "transaction_id"} for item in data["unusual"]],
            "rules": data["unusual_rules"],
        }
        return _brief(intent, {**data, "verdict": "", "confidence": _breakdown_confidence(data), "assumptions": [
            "Counts completed payments sent from this wallet; categories use your manual corrections where you made them."]},
            figures, {"from": _d(data["from"]), "to": _d(data["to"])}, details=details)
    if intent == "explain_balance":
        keys = ("opening_balance", "credits", "payments", "fees", "savings_contributions", "savings_withdrawals",
                "pending_holds", "released_holds_net", "other", "closing_balance", "current_balance", "savings_goals_total")
        figures = {k: data[k] for k in keys}
        details = {"top_deductions": [{"kind": t["kind"], "amount": t["amount"], "date": _d(t["date"])} for t in data["top_deductions"]],
                   "reconciles": data["reconciles"], "fees_note": data["fees_note"], "period": data["period"]}
        return _brief(intent, {**data, "verdict": "", "confidence": "high" if data["reconciles"] else "low", "assumptions": [
            "Built from the wallet's append-only ledger; savings moves are shown separately."]},
            figures, {"from": _d(data["from"]), "to": _d(data["to"])}, details=details)
    if intent == "subscription_review":
        figures = {k: data[k] for k in ("count", "confirmed_count", "unconfirmed_count", "confirmed_monthly_total",
                                         "unconfirmed_monthly_total", "annual_total", "overlap_count")}
        details = {"items": [{k: i[k] for k in ("rank", "frequency", "monthly_cost", "annual_cost", "confirmed", "category",
                                                 "overlaps_with_same_category")} for i in data["items"][:10]],
                   "usage_data_available": False, "ranking_rule": data["ranking_rule"]}
        return _brief(intent, {**data, "verdict": "", "confidence": "medium" if data["count"] else "low", "assumptions": [
            "Usage data is not available, so items are ranked by cost and category overlap only."]}, figures, {}, details=details)
    raise ValueError(intent)


def _breakdown_confidence(data):
    return "high" if data["weeks_of_history"] >= 8 else "medium" if data["weeks_of_history"] >= 4 else "low"


def _brief(intent, data, figures, dates, recommendation=None, details=None):
    from .reasoning import reason
    return {
        "reasoning": reason(intent, data),
        "intent": intent, "verdict": data.get("verdict", ""), "recommendation": recommendation,
        "currency": data.get("currency", "KES"), "confidence": data.get("confidence", "low"),
        "figures": figures, "dates": dates,
        "missing_inputs": data.get("data_quality", {}).get("missing_inputs", []),
        "assumptions": list(data.get("assumptions", [])), "details": details or {}, "scope": SCOPE_NOTE,
    }


def llm_brief(brief):
    """The exact object sent to the language provider: the brief minus nothing (it is label-free by construction)."""
    return brief


# --- key figures for the UI ---------------------------------------------------------------------------------------

FIGURE_LABELS = {
    "amount": "Amount asked about", "balance": "Wallet balance", "confirmed_obligations": "Confirmed bills due",
    "authorized_savings_due": "Savings rules due", "projected_spending": "Projected spending",
    "buffer": "Safety buffer", "result": "Left after everything (conservative)",
    "with_expected_income": "Left including expected income", "monthly_set_aside_needed": "Set aside per month",
    "expected_income": "Expected income (30 days)", "essentials": "Essential bills (30 days)",
    "capacity": "Savings capacity", "additional_capacity": "Additional room to save",
    "already_committed_savings": "Already committed savings", "total": "Total spent",
    "opening_balance": "Opening balance", "credits": "Money in", "payments": "Payments out", "fees": "Fees",
    "savings_contributions": "Moved to savings", "savings_withdrawals": "Taken from savings",
    "pending_holds": "Held for review", "closing_balance": "Closing balance", "savings_goals_total": "In savings goals",
    "confirmed_monthly_total": "Confirmed recurring per month", "unconfirmed_monthly_total": "Unconfirmed per month",
    "annual_total": "Recurring per year",
}


def key_figures(brief):
    return [{"key": key, "label": label, "amount": brief["figures"][key], "currency": brief["currency"]}
            for key, label in FIGURE_LABELS.items()
            if key in brief["figures"] and brief["figures"][key] is not None]


# --- answer composition -------------------------------------------------------------------------------------------

def render(brief):
    """The answer is the reasoning's conclusion plus what it worked out, then what is missing and how sure it is."""
    reasoning = brief["reasoning"]
    parts = [reasoning["conclusion"], *reasoning["insights"]]
    parts += [MISSING_INPUT_TEXT[m] for m in brief["missing_inputs"] if m in MISSING_INPUT_TEXT]
    if brief.get("confidence"):
        parts.append(f"Confidence: {brief['confidence']}.")
    parts.append(SCOPE_NOTE)
    return " ".join(part for part in parts if part)


# --- number check ---------------------------------------------------------------------------------------------------

NUMBER_RE = re.compile(r"(?<![\w])\d[\d,]*(?:\.\d+)?")


def _normalise(token):
    try:
        return Decimal(token.replace(",", "").rstrip(".")).normalize()
    except InvalidOperation:
        return None


def allowed_numbers(obj, found=None):
    found = set() if found is None else found
    if isinstance(obj, bool) or obj is None:
        return found
    if isinstance(obj, (int, Decimal)):
        found.add(Decimal(obj).normalize())
    elif isinstance(obj, float):
        found.add(Decimal(str(obj)).normalize())
    elif isinstance(obj, str):
        for token in NUMBER_RE.findall(obj):
            value = _normalise(token)
            if value is not None:
                found.add(value)
        for part in re.findall(r"\d+", obj):  # date parts such as 2026-12-01
            found.add(Decimal(part).normalize())
    elif isinstance(obj, date):
        found.update({Decimal(obj.year), Decimal(obj.month), Decimal(obj.day)})
    elif isinstance(obj, dict):
        for value in obj.values():
            allowed_numbers(value, found)
    elif isinstance(obj, (list, tuple)):
        for value in obj:
            allowed_numbers(value, found)
    return found


def unknown_numbers(text, brief):
    allowed = allowed_numbers(brief)
    return [token for token in NUMBER_RE.findall(text or "") if _normalise(token) not in allowed]
