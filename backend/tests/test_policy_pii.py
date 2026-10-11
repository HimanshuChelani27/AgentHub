from app.gateway import pii
from app.gateway.policy import evaluate
from app.models import Policy

RULES = [
    Policy(id=1, priority=10, role="admin", effect="allow", mask_pii=False),
    Policy(id=2, priority=20, role="*", server="company_kb", tool="get_contract", effect="deny"),
    Policy(id=3, priority=30, role="agent", server="company_kb", tool="*", effect="allow"),
    Policy(id=4, priority=40, role="agent", server="utils", tool="calc*", effect="allow", mask_pii=False),
]


def test_first_match_wins():
    assert evaluate(RULES, "admin", "company_kb", "get_contract").allowed  # admin rule comes first
    d = evaluate(RULES, "agent", "company_kb", "get_contract")
    assert not d.allowed and d.rule_id == 2


def test_globs_and_mask_flag():
    d = evaluate(RULES, "agent", "utils", "calculator")
    assert d.allowed and not d.mask_pii and d.rule_id == 4
    assert evaluate(RULES, "agent", "company_kb", "get_customer").mask_pii


def test_default_deny():
    d = evaluate(RULES, "agent", "utils", "word_count")  # no rule matches calc* only
    assert not d.allowed and "default deny" in d.reason
    assert not evaluate([], "viewer", "x", "y").allowed


def test_masks_people_emails_and_phones_in_free_text():
    text = "Priya Sharma (priya.sharma@acme.example.com) escalated. Call Mark Liu on +1 555 0199 230."
    masked, counts = pii.mask(text)
    assert "priya.sharma@" not in masked and "Mark Liu" not in masked and "555 0199" not in masked
    assert counts["EMAIL_ADDRESS"] == 1 and counts["PHONE_NUMBER"] == 1 and counts["PERSON"] >= 2


def test_keeps_business_data_and_uses_field_hints():
    record = {
        "company": "Acme Corp",
        "renewal_date": "2027-01-31",
        "arr_usd": 480000,
        "account_manager": "Daniel Brooks",
        "contact": {"name": "Rahul Mehta", "email": "rahul@initech.example.com", "phone": "+91 98765 43210"},
    }
    masked, counts = pii.mask(record)
    assert masked["company"] == "Acme Corp"
    assert masked["renewal_date"] == "2027-01-31"
    assert masked["arr_usd"] == 480000
    assert masked["account_manager"] == "<PERSON>"
    assert masked["contact"] == {"name": "<PERSON>", "email": "<EMAIL_ADDRESS>", "phone": "<PHONE_NUMBER>"}
    assert sum(counts.values()) == 4


def test_input_masking_keeps_names_but_strips_identifiers():
    masked, _ = pii.mask({"query": "Priya Sharma priya@acme.example.com"}, for_input=True)
    assert "Priya Sharma" in masked["query"] and "<EMAIL_ADDRESS>" in masked["query"]


def test_single_capitalised_words_are_not_people():
    masked, counts = pii.mask("Dashboard takes 12s to load. SSO login loop reported by Mark Liu.")
    assert masked.startswith("Dashboard takes 12s") and "SSO login" in masked
    assert "Mark Liu" not in masked and counts == {"PERSON": 1}
