"""Runs one assistant question: understand -> analyse (deterministic tools) -> compose (brief + phrasing).

Read-only by construction: the only rows written are the assistant's own AssistantRun / AIConversation / AIMessage.
"""
from __future__ import annotations

import json
import logging
import time
from decimal import Decimal

from django.core.serializers.json import DjangoJSONEncoder
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from apps.wallets.services import ensure_wallet

from . import brief as briefs
from . import language, memory, tools
from .conf import assistant_conf as conf
from .models import AIMessage, AssistantRun
from .parsing import (INTENTS, deterministic_extract, is_action_request, is_follow_up, parse_amounts, redact_question,
                      validate_extraction)

logger = logging.getLogger(__name__)
audit_logger = logging.getLogger("apps.assistant.audit")

TOOLS_BY_INTENT = {
    "afford_purchase": ["balance_context", "obligations", "income_expectations", "spending_profile", "decision_engine"],
    "trip_affordability": ["balance_context", "obligations", "income_expectations", "spending_profile", "decision_engine"],
    "savings_capacity": ["obligations", "income_expectations", "spending_profile", "savings_capacity"],
    "spending_breakdown": ["spending_breakdown"],
    "explain_balance": ["balance_context", "explain_balance"],
    "subscription_review": ["recurring_review"],
}
ANALYSE_LABELS = {
    "afford_purchase": "Check balance, upcoming bills, savings rules and typical spending",
    "trip_affordability": "Check balance, bills and income up to the trip date",
    "savings_capacity": "Compare expected income with bills and typical spending",
    "spending_breakdown": "Group payments by category and check unusual spending",
    "explain_balance": "Rebuild the balance from ledger entries",
    "subscription_review": "Review recurring payments by cost and overlap",
}
SUPPORTED_SUMMARY = ("I can help with: whether you can afford a purchase or a trip, a spending breakdown, how much you "
                     "can save, why your balance is what it is, and a review of recurring payments.")


# --- run lifecycle ------------------------------------------------------------------------------------------------

def _step(key, label):
    return {"key": key, "label": label, "status": "pending"}


def create_run(user, question, conversation_id=None):
    conversation = memory.conversation_for(user, conversation_id)
    message = memory.add_message(conversation, AIMessage.Role.USER, question)
    run = AssistantRun.objects.create(user=user, conversation=conversation, steps=[
        _step("understand", "Understand the question"),
        _step("analyse", "Run account tools"),
        _step("compose", "Write the decision brief"),
    ])
    return run, message


def _save(run, *fields):
    run.save(update_fields=list(fields) or ["steps", "status"])


def _set(run, key, status, detail=None, label=None):
    for step in run.steps:
        if step["key"] == key:
            step["status"] = status
            if detail:
                step["detail"] = detail
            if label:
                step["label"] = label
    _save(run, "steps")


def execute_run(run_id, question):
    run = AssistantRun.objects.select_related("user", "conversation").get(pk=run_id)
    started = time.monotonic()
    run.status, run.started_at = AssistantRun.Status.RUNNING, timezone.now()
    _save(run, "status", "started_at")
    try:
        response = _execute(run, question)
        run.status = AssistantRun.Status.COMPLETED if response["support_status"] != "tool_failed" else AssistantRun.Status.FAILED
    except Exception:
        logger.exception("Assistant run %s failed", run.pk)
        for step in run.steps:
            if step["status"] in ("pending", "running"):
                step["status"] = "failed"
        response = _base_response(run, question, "tool_failed",
                                  "I could not complete this analysis right now. Nothing was changed. Please try again.")
        run.status = AssistantRun.Status.FAILED
    response["steps"] = run.steps
    response["plan"] = run.steps
    run.response = json.loads(json.dumps(response, cls=DjangoJSONEncoder))
    run.support_status = response["support_status"]
    run.verdict = response.get("verdict") or ""
    run.confidence = response.get("confidence") or ""
    run.finished_at = timezone.now()
    run.duration_ms = int((time.monotonic() - started) * 1000)
    run.save()
    audit_logger.info("assistant_run", extra={
        "run_id": str(run.pk), "user_id": run.user_id, "intent": run.intent, "tools": run.tools,
        "statuses": [s["status"] for s in run.steps], "support_status": run.support_status,
        "extraction_provider": run.extraction_provider, "phrasing_provider": run.phrasing_provider,
        "fallback_reason": run.fallback_reason, "duration_ms": run.duration_ms,
    })
    return run


# --- the pipeline -------------------------------------------------------------------------------------------------

def _execute(run, question):
    user, conversation = run.user, run.conversation
    wallet = ensure_wallet(user)
    today = timezone.localdate()

    _set(run, "understand", "running")
    context = memory.last_decision_context(conversation) if conversation else None
    if is_action_request(question):
        return _finish_simple(run, question, "unsupported_action", (
            "I can't move money or change account settings. Nothing was done. If you want to go ahead, review the "
            "details in Payments, Savings or Wallet and submit there yourself."), requires_approval=True)
    entities, intent = _extract(run, question, context, today)
    run.intent = intent
    _save(run, "intent", "extraction_provider", "fallback_reason")

    if intent == "unsupported":
        return _finish_simple(run, question, "unsupported_question",
                              f"I can't answer that from your wallet data, and I won't guess. {SUPPORTED_SUMMARY}")
    if intent in ("afford_purchase", "trip_affordability") and entities.get("amount") is None:
        what = "trip budget" if intent == "trip_affordability" else "purchase amount"
        answer = (f"What is the {what}? Reply with an amount such as \"KSh 35,000\" or \"35k\" and I'll check it "
                  "against your wallet.")
        response = _finish_simple(run, question, "needs_input", answer, intent=intent)
        response["needs_input"] = ["amount"]
        memory.add_message(conversation, AIMessage.Role.ASSISTANT, answer, intent, {**entities, "needs_input": "amount"})
        return response
    _set(run, "understand", "completed", detail=f"Intent: {intent.replace('_', ' ')}")

    run.tools = TOOLS_BY_INTENT[intent]
    _save(run, "tools")
    _set(run, "analyse", "running", label=ANALYSE_LABELS[intent])
    try:
        data, citations = _run_tools(wallet, intent, entities, today)
    except Exception:
        logger.exception("Assistant tools failed for run %s (intent %s)", run.pk, intent)
        _set(run, "analyse", "failed", detail="An account tool could not complete.")
        _set(run, "compose", "failed")
        return _base_response(run, question, "tool_failed",
                              "I could not retrieve your account information right now. Nothing was changed. Please try again.")
    _set(run, "analyse", "completed")

    _set(run, "compose", "running")
    brief = briefs.build_brief(intent, data)
    answer, run.phrasing_provider = _phrase(run, brief)
    _set(run, "compose", "completed")

    response = _base_response(run, question, "answered", answer)
    response.update({
        "intent": intent, "entities": entities, "verdict": brief["verdict"] or None,
        "recommendation": brief["recommendation"], "confidence": brief["confidence"],
        "key_figures": briefs.key_figures(brief), "assumptions": brief["assumptions"],
        "missing_inputs": brief["missing_inputs"], "data_quality": data.get("data_quality"),
        "brief": brief, "tool_results": [{"tool": run.tools[-1], "status": "completed", "data": data}],
        "citations": citations[:conf.CITATION_CAP], "citation_count": len(citations),
        "reasoning": {k: brief["reasoning"][k] for k in ("conclusion", "steps", "insights")},
        "suggested_followups": brief["reasoning"]["followups"],
        "proposed_actions": _proposed_actions(intent, data, brief),
    })
    memory.add_message(conversation, AIMessage.Role.ASSISTANT, answer, intent, entities)
    return response


def _extract(run, question, context, today):
    det = deterministic_extract(question, today)
    result, run.extraction_provider, run.fallback_reason = dict(det), "deterministic_parser", ""
    if language.provider_available():
        previous = {"intent": context["intent"], **{k: context["entities"].get(k) for k in ("amount", "horizon", "period")}} if context else None
        try:
            llm = validate_extraction(language.extract_intent(redact_question(question), previous))
            if det["intent"] == "unsupported" or llm["intent"] == det["intent"]:
                result["intent"] = llm["intent"]
            stated = parse_amounts(question)
            # Never accept an amount the user did not state.
            result["amount"] = llm["amount"] if llm["amount"] is not None and llm["amount"] in stated else det["amount"]
            for key in ("horizon", "category", "period"):
                if llm[key] is not None:
                    result[key] = llm[key]
            run.extraction_provider = "llm"
        except language.LanguageProviderUnavailable:
            run.fallback_reason = "llm_unavailable"
        except ValidationError:
            logger.warning("Assistant language provider returned an invalid extraction for run %s", run.pk)
            run.fallback_reason = "llm_invalid_extraction"
    intent = result.pop("intent")
    if context and context["intent"] in INTENTS and is_follow_up(question):
        has_new_entity = any(result.get(k) is not None for k in ("amount", "horizon", "period", "category"))
        if intent == "unsupported" and has_new_entity or intent == context["intent"]:
            intent = context["intent"]
            for key in ("amount", "horizon", "period", "category"):
                if result.get(key) is None and context["entities"].get(key) not in (None, ""):
                    value = context["entities"][key]
                    result[key] = Decimal(value) if key == "amount" else value
    if result.get("amount") is not None:
        result["currency"] = "KES"
    return result, intent


def _run_tools(wallet, intent, entities, today):
    if intent == "afford_purchase":
        return tools.decision_engine(wallet, entities["amount"], entities.get("horizon"), today)
    if intent == "trip_affordability":
        return tools.trip_affordability(wallet, entities["amount"], entities.get("horizon"), today)
    if intent == "savings_capacity":
        return tools.savings_capacity(wallet, today)
    if intent == "spending_breakdown":
        return tools.spending_breakdown(wallet, entities.get("period") or "this_month", entities.get("category"), today)
    if intent == "explain_balance":
        return tools.explain_balance(wallet, entities.get("period") or "this_month", today)
    if intent == "subscription_review":
        return tools.recurring_review(wallet)
    raise ValueError(intent)


def _phrase(run, brief):
    template = briefs.render(brief)
    if not language.provider_available():
        return template, "deterministic_template"
    try:
        text = language.phrase_brief(briefs.llm_brief(brief))
    except language.LanguageProviderUnavailable:
        run.fallback_reason = run.fallback_reason or "llm_unavailable"
        _save(run, "fallback_reason")
        return template, "deterministic_template"
    unknown = briefs.unknown_numbers(text, brief)
    if unknown:
        logger.warning("Assistant phrasing for run %s contained %d number(s) not in the brief; using template", run.pk, len(unknown))
        run.fallback_reason = "number_mismatch"
        _save(run, "fallback_reason")
        return template, "deterministic_template"
    if briefs.SCOPE_NOTE not in text:
        text = f"{text} {briefs.SCOPE_NOTE}"
    return text, settings_provider()


def settings_provider():
    return language.provider_name()


# --- responses ----------------------------------------------------------------------------------------------------

def _base_response(run, question, support_status, answer):
    return {
        "run_id": str(run.pk), "conversation_id": str(run.conversation_id) if run.conversation_id else None,
        "question": question, "intent": run.intent or None, "entities": {}, "support_status": support_status,
        "answer": answer, "verdict": None, "recommendation": None, "confidence": None, "key_figures": [],
        "assumptions": [], "missing_inputs": [], "data_quality": None, "tool_results": [], "citations": [],
        "citation_count": 0, "reasoning": None, "suggested_followups": [], "proposed_actions": [], "scope_note": briefs.SCOPE_NOTE,
        "provider": {"intent_extraction": run.extraction_provider or "deterministic_parser",
                     "phrasing": run.phrasing_provider or "deterministic_template",
                     "fallback_reason": run.fallback_reason or None},
        "language_provider": run.phrasing_provider or "deterministic_template",
        "read_only": True, "requires_approval": False, "action_executed": False,
    }


def _finish_simple(run, question, support_status, answer, requires_approval=False, intent=None):
    run.steps = [step for step in run.steps if step["key"] == "understand"]
    for step in run.steps:
        step["status"] = "completed"
        step["detail"] = {"unsupported_action": "Request to move money or change settings: not executed",
                          "unsupported_question": "Outside what the assistant can answer",
                          "needs_input": "An amount is needed"}.get(support_status)
    run.intent = intent or ("unsupported" if support_status != "needs_input" else run.intent)
    run.phrasing_provider = "deterministic_template"
    _save(run, "steps", "intent", "phrasing_provider", "extraction_provider", "fallback_reason")
    response = _base_response(run, question, support_status, answer)
    response["requires_approval"] = requires_approval
    if support_status == "unsupported_action":
        response["proposed_actions"] = [{"type": "open_screen", "label": "Review in Payments, Savings or Wallet",
                                         "screens": ["/payments", "/savings", "/wallet"], "requires_confirmation": True}]
    if support_status != "needs_input":
        memory.add_message(run.conversation, AIMessage.Role.ASSISTANT, answer, run.intent, {})
    return response


def _proposed_actions(intent, data, brief):
    """Suggestions only. The assistant never calls these endpoints; the user confirms through the normal screens."""
    actions = []
    missing = brief["missing_inputs"]
    if "housing_cost" in missing:
        actions.append({"type": "add_calendar_entry", "label": "Add your rent to the Financial Calendar", "method": "POST",
                        "endpoint": "/api/v1/insights/calendar/", "prefill": {"kind": "bill", "category": "housing"},
                        "requires_confirmation": True})
    if "expected_income" in missing:
        actions.append({"type": "add_calendar_entry", "label": "Add your expected income to the Financial Calendar",
                        "method": "POST", "endpoint": "/api/v1/insights/calendar/", "prefill": {"kind": "income"},
                        "requires_confirmation": True})
    if intent == "savings_capacity" and data.get("additional_capacity") and data["additional_capacity"] > 0:
        actions.append({"type": "create_savings_goal", "label": "Create a savings goal", "method": "POST",
                        "endpoint": "/api/v1/savings/goals/", "prefill": {}, "requires_confirmation": True})
        actions.append({"type": "create_savings_schedule", "label": "Set up a monthly savings rule", "method": "POST",
                        "endpoint": "/api/v1/savings/schedules/",
                        "prefill": {"amount": data["additional_capacity"], "cadence": "monthly"}, "requires_confirmation": True})
    if intent == "trip_affordability" and data["verdict"] in ("tight", "not_affordable", "affordable"):
        actions.append({"type": "create_savings_goal", "label": "Create a savings goal for this trip", "method": "POST",
                        "endpoint": "/api/v1/savings/goals/",
                        "prefill": {"target_amount": data["amount"], "target_date": data["trip_date"]},
                        "requires_confirmation": True})
    if intent == "subscription_review":
        for item in data["items"]:
            if item["source"] == "recurring_payment" and not item["confirmed"]:
                actions.append({"type": "review_recurring_payment", "label": "Confirm or dismiss a suggested recurring payment",
                                "method": "PATCH", "endpoint": f"/api/v1/insights/recurring/{item['id']}/",
                                "prefill": {}, "requires_confirmation": True})
    return actions[:6]
