"""The assistant's reasoning: works from the computed account figures to a conclusion.

Instead of filling a fixed answer per question type, each reasoner:
  1. lays out the working as explicit steps with the arithmetic (``calc``),
  2. reaches a conclusion by comparing the results (sign, buffer, previous period, largest driver ...),
  3. derives further figures it was not asked for but that change the decision (the most you could spend and keep a
     buffer, what changes after the next income, whether normal spending swings flip the answer, time to a goal ...),
  4. proposes follow-up questions built from those derived figures.

Every number comes from the deterministic tools or simple arithmetic on them, and is returned in ``derived`` so the
language-provider number check can verify it. No text from transactions, recipients or calendar titles is used.
"""
from __future__ import annotations

from datetime import date, timedelta
from decimal import ROUND_DOWN, ROUND_UP, Decimal

from .conf import assistant_conf as conf

ZERO = Decimal("0.00")
PERIOD_TEXT = {"this_month": "this month so far", "last_month": "last month", "last_7_days": "in the last 7 days",
               "last_30_days": "in the last 30 days"}
PREVIOUS_TEXT = {"this_month": "the same days last month", "last_month": "the month before",
                 "last_7_days": "the 7 days before", "last_30_days": "the 30 days before"}
DRIVER_TEXT = {"credits": "money coming in", "payments": "payments you made", "savings": "money moved into savings",
               "pending": "payments held for review", "fees": "fees"}


class Reasoning:
    def __init__(self, currency):
        self.currency = currency
        self.steps, self.insights, self.followups = [], [], []
        self.derived = {}
        self.conclusion = ""

    def m(self, value):
        return f"{self.currency} {Decimal(value):,.2f}"

    def step(self, text, calc=None, value=None):
        self.steps.append({"text": text, "calc": calc})
        return value

    def derive(self, name, value):
        if value is not None:
            self.derived[name] = Decimal(value).quantize(Decimal("0.01")) if not isinstance(value, int) else value
        return value

    def ask(self, question):
        if question not in self.followups:
            self.followups.append(question)

    def as_dict(self):
        return {"conclusion": self.conclusion, "steps": self.steps, "insights": self.insights,
                "followups": self.followups[:3], "derived": self.derived}


def _n(value):
    return f"{Decimal(value):,.2f}"


def _sub(a, b):
    return f"{_n(a)} − {_n(b)} = {_n(a - b)}"


def _round_down(value):
    unit = Decimal("100") if value >= 1000 else Decimal("1")
    return (Decimal(value) / unit).to_integral_value(rounding=ROUND_DOWN) * unit


def _ksh(value):
    return f"KSh {Decimal(value):,.0f}"


def _date(value):
    return value.strftime("%-d %B %Y") if isinstance(value, date) else str(value)


# --- purchases and trips -----------------------------------------------------------------------------------------

def reason_decision(intent, data):
    r = Reasoning(data["currency"])
    thing = "the trip" if intent == "trip_affordability" else "the purchase"
    amount, balance = data["amount"], data["balance"]
    end = _date(data["horizon_end"])
    basis = {"until_next_income": f"until your next recorded income on {end}", "requested": f"up to {end}",
             "default": f"over the next {data['horizon_days']} days (no income date is recorded)"}[data["horizon_basis"]]

    running = r.step(f"I start from your wallet balance of {r.m(balance)} and look {basis}.", value=balance)
    if data["confirmed_obligations"]:
        biggest = max(data["obligations_by_category"].items(), key=lambda kv: kv[1])
        r.step(f"Bills you have confirmed fall due in that time ({biggest[0]} is the largest at {r.m(biggest[1])}).",
               _sub(running, data["confirmed_obligations"]))
        running -= data["confirmed_obligations"]
    if data["authorized_savings_due"]:
        r.step("Your automatic savings rules will also take money in that time.", _sub(running, data["authorized_savings_due"]))
        running -= data["authorized_savings_due"]
    weeks = Decimal(data["horizon_days"]) / Decimal(7)
    used = data["data_quality"]["weeks_used"]
    if used and not data["projected_spending"]:
        r.step(f"In the {used} week(s) of history I can use, you made no everyday payments, so I subtract nothing "
               f"for spending; if you do spend, the real figure will be lower.")
    elif used:
        r.step(f"You usually spend {r.m(data['weekly_average_spend'])} a week, so over {weeks:.1f} weeks I expect about "
               f"{r.m(data['projected_spending'])} of everyday spending.", _sub(running, data["projected_spending"]))
        running -= data["projected_spending"]
    else:
        r.step("There is no spending history to project yet, so I could not subtract everyday spending; "
               "the real figure will be lower.")
    r.step(f"Then {thing} itself.", _sub(running, amount))
    result, buffer = data["result"], data["buffer"]
    if buffer:
        r.step(f"I compare what is left with a safety buffer of {conf.BUFFER_WEEKS} weeks of your usual spending.",
               f"{_n(result)} − {_n(buffer)} = {_n(result - buffer)}")

    room_with_buffer = r.derive("most_you_can_spend_keeping_buffer", max(ZERO, amount + result - buffer))
    room_at_all = r.derive("most_you_can_spend", max(ZERO, amount + result))
    margin = r.derive("margin_over_buffer", result - buffer)
    known_left = data["known_left"]

    verdict = data["verdict"]
    if verdict == "wallet_frozen":
        r.conclusion = f"Not right now: your wallet is frozen, so it cannot pay for {thing} until you unfreeze it."
    elif data["certain_shortfall"]:
        short = r.derive("certain_shortfall_amount", -known_left)
        if balance < amount:
            r.conclusion = (f"No. Your balance is {r.m(balance)}, which is {r.m(amount - balance)} less than {thing} "
                            f"at {r.m(amount)}, so this is certain without any forecasting.")
        else:
            r.conclusion = (f"No. Your balance of {r.m(balance)} cannot cover {thing} and the bills and savings already "
                            f"due: you would be {r.m(short)} short before any everyday spending.")
    elif verdict == "insufficient_history":
        lean = "probably yes" if result >= buffer else "probably not" if result < 0 else "it looks tight"
        r.conclusion = (f"On the numbers, {lean}: about {r.m(result)} would be left by {end}. But I only have "
                        f"{data['data_quality']['weeks_of_history']} week(s) of history to judge your spending (I need "
                        f"{conf.MIN_HISTORY_WEEKS}), so treat this as a rough estimate.")
    elif result < 0:
        r.conclusion = f"No. You would run {r.m(-result)} short by {end}."
    elif result < buffer:
        r.conclusion = (f"Only just. You would have {r.m(result)} left by {end}, which is {r.m(buffer - result)} below "
                        f"your safety buffer of {r.m(buffer)}.")
    else:
        r.conclusion = (f"Yes. You would still have {r.m(result)} left by {end}, {r.m(margin)} more than your safety "
                        f"buffer of {r.m(buffer)}.")

    if verdict != "wallet_frozen":
        if result < buffer and room_with_buffer > 0:
            r.insights.append(f"The most you could spend now and still keep your buffer is about {r.m(room_with_buffer)}.")
            if _round_down(room_with_buffer) >= 1:
                r.ask(f"Can I afford {_ksh(_round_down(room_with_buffer))}?")
        elif result < buffer and room_at_all > 0:
            r.insights.append(f"Even {r.m(room_at_all)} would leave nothing spare; keeping the buffer means not spending "
                              f"more before your next income.")
        elif result >= buffer:
            r.insights.append(f"You could go up to about {r.m(room_with_buffer)} and still keep your buffer.")

        next_income, income_amount = data["next_income_date"], data["next_income_amount"]
        within = data["scenarios"]["with_expected_income"]
        if within is not None and data["horizon_basis"] != "until_next_income":
            # Income lands before the date in question: count it rather than suggesting to wait for it.
            r.derive("with_income_in_period", within)
            if result < buffer <= within:
                r.insights.append(f"That leaves out the {r.m(data['expected_income'])} of income you expect before "
                                  f"{end}; counting it you would have {r.m(within)}, above the buffer, so this works as "
                                  f"long as that income arrives on time.")
            elif within < buffer:
                r.insights.append(f"Even counting the {r.m(data['expected_income'])} of income expected before {end}, you "
                                  f"would have only {r.m(within)}, below the buffer.")
        elif next_income and income_amount is not None:
            after = within if within is not None else result + income_amount
            r.derive("after_next_income", after)
            if result < buffer <= after:
                r.insights.append(f"Your next recorded income of {r.m(income_amount)} on {_date(next_income)} changes "
                                  f"the answer: after it you would have about {r.m(after)}, above the buffer. "
                                  f"Waiting until then is the safer choice.")
                today = data["horizon_end"] - timedelta(days=data["horizon_days"])
                days = (next_income - today).days + 1
                if 0 < days <= conf.MAX_HORIZON_DAYS:
                    r.ask(f"Can I afford {_ksh(amount)} in {days} days?")
            elif after < buffer:
                r.insights.append(f"Even after your next income on {_date(next_income)} you would have only {r.m(after)}, "
                                  f"so this needs saving up for rather than waiting.")

        low, high = data["uncertainty_range"]["low"], data["uncertainty_range"]["high"]
        if low != high:
            r.derive("heavy_week_figure", low)
            flips = (low < 0 <= result) or (low < buffer <= result)
            r.insights.append(
                f"Your weekly spending varies, so the leftover could be anywhere from {r.m(low)} to {r.m(high)}"
                + ("; a heavier-than-usual stretch would change the answer." if flips else "; that does not change the answer."))

        if intent == "trip_affordability" and data.get("monthly_set_aside_needed") and data["horizon_days"] >= 60:
            r.insights.append(f"To pay for it from savings instead, you would need to put aside about "
                              f"{r.m(data['monthly_set_aside_needed'])} a month until {_date(data['trip_date'])}.")
        if data["unconfirmed_recurring_total"]:
            r.insights.append(f"I left out {r.m(data['unconfirmed_recurring_total'])} of possible recurring payments you "
                              f"have not confirmed; if they are real, the leftover is that much lower.")
            r.ask("Which recurring payments do I have?")
    return r


# --- savings -------------------------------------------------------------------------------------------------------

def reason_savings(data):
    r = Reasoning(data["currency"])
    if data["verdict"] == "wallet_frozen":
        r.conclusion = "Your wallet is frozen, so no money can move into savings until you unfreeze it."
        return r
    if data["capacity"] is None:
        r.step(f"Your usual spending is {r.m(data['weekly_average_spend'])} a week, and confirmed bills for the next "
               f"30 days total {r.m(data['essentials'])}.")
        r.conclusion = ("I can't tell how much you can save: no income is recorded for the next 30 days, and any figure "
                        "without it would be a guess.")
        return r
    income = data["expected_income"]
    running = r.step(f"Over the next 30 days you expect {r.m(income)} of income.", value=income)
    r.step("Confirmed bills come out first.", _sub(running, data["essentials"]))
    running -= data["essentials"]
    r.step(f"Your usual spending of {r.m(data['weekly_average_spend'])} a week comes to about "
           f"{r.m(data['projected_spending'])} in 30 days.", _sub(running, data["projected_spending"]))
    running -= data["projected_spending"]
    r.step(f"I keep a safety buffer of {conf.BUFFER_WEEKS} weeks of spending.", _sub(running, data["buffer"]))
    running -= data["buffer"]
    if data["already_committed_savings"] and running > 0:
        r.step("Savings rules you already set up are part of that room.", _sub(running, data["already_committed_savings"]))
    extra = data["additional_capacity"]
    if extra > 0:
        r.conclusion = f"You could save about {r.m(extra)} more over the next 30 days without touching your buffer."
        for goal in data["goals"]:
            remaining = Decimal(goal["target_amount"]) - Decimal(goal["saved_amount"])
            if remaining > 0:
                months = int((remaining / extra).to_integral_value(rounding=ROUND_UP))
                r.derive("months_to_first_goal", months)
                r.insights.append(f"At that rate, a goal with {r.m(remaining)} still to go would be reached in about "
                                  f"{months} month(s).")
                break
    else:
        drain = "everyday spending is" if data["projected_spending"] >= data["essentials"] else "bills are"
        r.conclusion = (f"There is no room to save more right now: after bills, spending and the buffer you would be at "
                        f"{r.m(data['capacity'])}, and {drain} the larger part of what uses up your income.")
        if drain.startswith("everyday"):
            r.ask("What did I spend this month?")
    if data["projected_spending"]:
        tenth = r.derive("ten_percent_less_spending", data["projected_spending"] / 10)
        r.insights.append(f"Spending 10% less would free up about {r.m(tenth)} a month.")
    return r


# --- spending ------------------------------------------------------------------------------------------------------

def reason_spending(data):
    r = Reasoning(data["currency"])
    period, total, count = data["period"], data["total"], data["transaction_count"]
    when = PERIOD_TEXT.get(period, period)
    if not count:
        r.conclusion = f"You made no completed payments from this wallet {when} ({data['from']} to {data['to']})."
        return r
    cats = data["categories"]
    r.step(f"I added up {count} completed payment(s) {when} ({data['from']} to {data['to']}).", f"total = {_n(total)}")
    top = cats[0]
    if len(cats) > 1:
        r.step(f"Grouped by category, {top['category']} is the largest at {r.m(top['amount'])}.",
               f"{_n(top['amount'])} ÷ {_n(total)} = {top['share_percent']}%")
    else:
        r.step(f"All of it was {top['category']}.")
    daily = r.derive("daily_average", total / data["days_in_period"])
    r.step(f"Spread over {data['days_in_period']} day(s), that is about {r.m(daily)} a day.")
    r.conclusion = (f"You spent {r.m(total)} {when}, mostly on {top['category']} ({top['share_percent']:.0f}% of it)."
                    if len(cats) > 1 else f"You spent {r.m(total)} {when}, all of it on {top['category']}.")

    previous = data["previous_period"]["total"]
    if previous is not None:
        change = r.derive("change_vs_previous", total - previous)
        r.step(f"For comparison, {PREVIOUS_TEXT.get(period, 'the previous period')} you spent {r.m(previous)}.",
               _sub(total, previous))
        if previous:
            pct = r.derive("change_percent", change / previous * 100)
            direction = "more" if change > 0 else "less"
            if change:
                r.conclusion += f" That is {r.m(abs(change))} ({abs(pct):.0f}%) {direction} than {PREVIOUS_TEXT.get(period)}."
        if change > 0 and len(cats) > 1:
            r.ask(f"How much did I spend on {top['category']} last month?")
    for item in data["unusual"][:4]:
        if item["rule"] == "category_above_trailing_average":
            r.insights.append(f"{item['category'].capitalize()} is unusually high: {r.m(item['amount'])} against a usual "
                              f"{r.m(item['trailing_average'])} for this point in the period.")
        elif item["rule"] == "single_large_transaction":
            r.insights.append(f"One {item['category']} payment of {r.m(item['amount'])} stands out: it is at least "
                              f"{conf.LARGE_TXN_MULTIPLIER} times your typical payment.")
        else:
            r.insights.append(f"A payment of {r.m(item['amount'])} went to someone you had not paid before.")
    if len(cats) > 1:
        rest = r.derive("outside_top_category", total - top["amount"])
        r.insights.append(f"Everything outside {top['category']} adds up to {r.m(rest)}.")
    r.ask("Why is my balance what it is?")
    return r


# --- balance -------------------------------------------------------------------------------------------------------

def reason_balance(data):
    r = Reasoning(data["currency"])
    when = PERIOD_TEXT.get(data["period"], data["period"])
    opening, closing = data["opening_balance"], data["closing_balance"]
    running = r.step(f"At the start ({data['from']}) your wallet held {r.m(opening)}.", value=opening)
    moves = [("credits", data["credits"], +1), ("payments", data["payments"], -1),
             ("savings", data["savings_contributions"] - data["savings_withdrawals"], -1),
             ("pending", data["pending_holds"], -1), ("fees", data["fees"], -1)]
    for key, value, sign in moves:
        if value:
            new = running + sign * value
            r.step(f"{DRIVER_TEXT[key].capitalize()}: {r.m(abs(value))}.",
                   f"{_n(running)} {'+' if sign * value > 0 else '−'} {_n(abs(value))} = {_n(new)}")
            running = new
    if data["released_holds_net"] or data["other"]:
        running += data["released_holds_net"] + data["other"]
        r.step("Other adjustments (released holds and corrections).", f"= {_n(running)}")
    r.step(f"That brings the wallet to {r.m(closing)}.")

    change = r.derive("net_change", closing - opening)
    drivers = sorted(((key, abs(value)) for key, value, _ in moves if value), key=lambda kv: -kv[1])
    direction = "down" if change < 0 else "up" if change > 0 else "unchanged"
    r.conclusion = f"Your wallet balance is {r.m(data['current_balance'])}."
    if direction == "unchanged":
        r.conclusion += f" It is the same as at the start of {when.replace(' so far', '')}."
    else:
        r.conclusion += f" It went {direction} by {r.m(abs(change))} {when}"
        r.conclusion += f", mainly because of {DRIVER_TEXT[drivers[0][0]]} ({r.m(drivers[0][1])})." if drivers else "."
    if data["top_deductions"]:
        top = data["top_deductions"][0]
        r.insights.append(f"The single biggest deduction was {r.m(top['amount'])} "
                          f"({top['kind'].replace('_', ' ')}) on {_date(top['date'])}.")
    if data["savings_goals_total"]:
        total = r.derive("wallet_plus_savings", data["current_balance"] + data["savings_goals_total"])
        r.insights.append(f"Your savings goals hold another {r.m(data['savings_goals_total'])} outside the wallet, "
                          f"so together you have {r.m(total)}.")
    if data["pending_holds"]:
        r.insights.append(f"{r.m(data['pending_holds'])} is held for review; it comes back if the payment is rejected.")
    if not data["reconciles"]:
        r.insights.append("The ledger entries for this period don't fully add up, so treat these figures with caution.")
    if drivers and drivers[0][0] == "payments":
        r.ask("What did I spend this month?")
    if drivers and drivers[0][0] == "savings":
        r.ask("How much can I save per month?")
    return r


# --- recurring payments --------------------------------------------------------------------------------------------

def reason_recurring(data):
    r = Reasoning(data["currency"])
    if not data["count"]:
        r.conclusion = ("I found no recurring payments. Recurring detection in Insights, or regular bills added to the "
                        "Financial Calendar, would show up here.")
        return r
    monthly = r.derive("monthly_total", data["confirmed_monthly_total"] + data["unconfirmed_monthly_total"])
    r.step(f"I found {data['count']} recurring payment(s): {data['confirmed_count']} confirmed "
           f"({r.m(data['confirmed_monthly_total'])} a month) and {data['unconfirmed_count']} unconfirmed "
           f"({r.m(data['unconfirmed_monthly_total'])} a month).",
           f"{_n(data['confirmed_monthly_total'])} + {_n(data['unconfirmed_monthly_total'])} = {_n(monthly)}")
    r.step("Weekly items are converted to a monthly cost (× 52 ÷ 12) and everything is multiplied by 12 for the year.",
           f"annual = {_n(data['annual_total'])}")
    r.conclusion = f"Your recurring payments cost about {r.m(monthly)} a month, or {r.m(data['annual_total'])} a year."
    top = data["items"][0]
    share = r.derive("top_item_share", top["monthly_cost"] / monthly * 100 if monthly else ZERO)
    r.insights.append(f"The most expensive is a {top['frequency']} {top['category']} payment at "
                      f"{r.m(top['monthly_cost'])} a month, {share:.0f}% of the total.")
    by_category = {}
    for item in data["items"]:
        if item["overlaps_with_same_category"]:
            by_category.setdefault(item["category"], []).append(item["monthly_cost"])
    if by_category:
        saving = r.derive("overlap_saving", sum((sum(costs) - max(costs) for costs in by_category.values()), ZERO))
        r.insights.append(f"{data['overlap_count']} payments share a category with another; if they are duplicates, "
                          f"keeping only the dearest in each would save {r.m(saving)} a month.")
    r.insights.append("I have no usage data, so I can only rank these by cost and overlap, not by how much you use them.")
    r.ask("How much can I save per month?")
    return r


def reason(intent, data):
    if intent in ("afford_purchase", "trip_affordability"):
        return reason_decision(intent, data).as_dict()
    if intent == "savings_capacity":
        return reason_savings(data).as_dict()
    if intent == "spending_breakdown":
        return reason_spending(data).as_dict()
    if intent == "explain_balance":
        return reason_balance(data).as_dict()
    if intent == "subscription_review":
        return reason_recurring(data).as_dict()
    raise ValueError(intent)
