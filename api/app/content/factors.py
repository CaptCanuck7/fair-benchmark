"""Factor labels, units, help text and data sources.

Copied from the `F`, `FORMS` and `CONF` objects in reference/fair-workbench.html.
This is the single source for this text; the frontend reads it from
GET /api/content/factors.
"""

# Confidence level -> PERT lambda (shape weight on the most likely value).
CONF = {
    "low": {"label": "Low", "lam": 2},
    "med": {"label": "Medium", "lam": 4},
    "high": {"label": "High", "lam": 6},
}

FORMS = {
    "primary": [
        ("productivity", "Productivity"),
        ("response", "Response"),
        ("replacement", "Replacement"),
    ],
    "secondary": [
        ("response", "Response"),
        ("fines", "Fines and judgments"),
        ("competitive", "Competitive advantage"),
        ("reputation", "Reputation"),
    ],
}

F = {
    "lef": {
        "path": "lef.lef",
        "label": "Loss event frequency",
        "unit": "loss events per year",
        "kind": "freq",
        "help": "How many times per year you expect this loss event to actually happen, meaning an event where the organization loses something. 0.2 means about once every five years. Estimate it directly only when you have loss history for this scenario or very similar ones.",
        "data": "Your issue or incident register (events that caused real loss), insurance claims, industry loss data such as Cyentia IRIS or Advisen, and peer organizations.",
    },
    "tef": {
        "path": "lef.tef",
        "label": "Threat event frequency",
        "unit": "threat events per year",
        "kind": "freq",
        "help": "How many times per year the threat community acts against the asset in a way that could cause loss. These are attempts, not successes. A threat event that fails is not a loss event.",
        "data": "Firewall, WAF, IDS and SIEM logs, SOC alert history, threat intelligence, vendor telemetry, and industry reports such as the Verizon DBIR. For non-malicious threats: change failure rates, vendor notices, outage history.",
    },
    "cf": {
        "path": "lef.cf",
        "label": "Contact frequency",
        "unit": "contacts per year",
        "kind": "freq",
        "help": "How often threat agents come into contact with the asset per year: scans, sessions, users with access, or exposure windows. Only a fraction of contacts become attempts.",
        "data": "Perimeter and access logs, number of users or systems with access, scan telemetry, exposure time.",
    },
    "poa": {
        "path": "lef.poa",
        "label": "Probability of action",
        "unit": "% of contacts that become attempts",
        "kind": "pct",
        "help": "The chance that a contact turns into an attempt against the asset. It rises with the value of the asset to the attacker and falls with the effort and the chance of being caught.",
        "data": "Threat intelligence on targeting, the attractiveness of the data or system, and attacker cost and risk.",
    },
    "vuln": {
        "path": "lef.vuln",
        "label": "Vulnerability",
        "unit": "% of threat events that become loss events",
        "kind": "pct",
        "help": "The chance that a threat event becomes a loss event, meaning the attempt succeeds. This is where your controls show up. In FAIR, vulnerability is a probability, not a CVE or a scanner finding.",
        "data": "Pen test and red team results, control test results and audit findings, exploit availability (CISA KEV, EPSS), configuration reviews, and how well the controls actually cover this path.",
    },
    "tcap": {
        "path": "lef.tcap",
        "label": "Threat capability",
        "unit": "percentile, 0 to 100",
        "kind": "score",
        "help": "How capable this threat community is, as a percentile of the whole threat population. 0 is the least capable attacker and 100 the most. Commodity criminals often sit around 40 to 70, organized crime around 70 to 90, nation-states in the high 90s.",
        "data": "Threat intelligence on the relevant actors, the skill and resources the attack needs, and observed tactics.",
    },
    "rs": {
        "path": "lef.rs",
        "label": "Resistance strength",
        "unit": "percentile, 0 to 100",
        "kind": "score",
        "help": "How strong your controls are, on the same percentile scale as threat capability. If your controls would stop 80% of the threat population, resistance strength is 80. Vulnerability is calculated as the chance that threat capability exceeds resistance strength.",
        "data": "Control testing, pen test results, the security architecture of this path, and compensating controls.",
    },
    "primary.productivity": {
        "path": "primary.productivity",
        "label": "Productivity",
        "unit": "$ per loss event",
        "kind": "money",
        "help": "Lost ability to deliver value: revenue lost or delayed, and staff who cannot work while the event is handled.",
        "data": "Finance, revenue per hour of the product or feature, the business owner, and outage duration history.",
    },
    "primary.response": {
        "path": "primary.response",
        "label": "Response",
        "unit": "$ per loss event",
        "kind": "money",
        "help": "The cost of managing the event itself: incident response time, forensics, outside counsel, crisis communications, overtime.",
        "data": "IR team rates and hours from past incidents, retainer contracts, insurance panel rates.",
    },
    "primary.replacement": {
        "path": "primary.replacement",
        "label": "Replacement",
        "unit": "$ per loss event",
        "kind": "money",
        "help": "The cost to replace or repair what was lost: rebuilding systems, emergency engineering, new hardware, rotating keys and credentials.",
        "data": "Engineering estimates, asset values, and past remediation costs.",
    },
    "slef": {
        "path": "slef",
        "label": "Secondary loss event frequency",
        "unit": "% of loss events",
        "kind": "pct",
        "help": "The chance that a loss event also triggers reactions from secondary stakeholders: customers, regulators, partners, the media. For example, a breach of personal data usually triggers notification; a short internal outage may not.",
        "data": "Legal and privacy (notification triggers by data type and jurisdiction), customer contracts, data volume and sensitivity.",
    },
    "secondary.response": {
        "path": "secondary.response",
        "label": "Response",
        "unit": "$ per secondary loss event",
        "kind": "money",
        "help": "The cost of dealing with secondary stakeholders: customer notification, credit monitoring, call centers, legal defense, regulator engagement.",
        "data": "Legal and privacy, breach cost vendors, notification and monitoring rates times the number of records.",
    },
    "secondary.fines": {
        "path": "secondary.fines",
        "label": "Fines and judgments",
        "unit": "$ per secondary loss event",
        "kind": "money",
        "help": "Regulatory fines, legal settlements, contractual penalties and SLA credits.",
        "data": "Legal, the privacy office, contract terms, and regulator enforcement history.",
    },
    "secondary.competitive": {
        "path": "secondary.competitive",
        "label": "Competitive advantage",
        "unit": "$ per secondary loss event",
        "kind": "money",
        "help": "Loss of trade secrets, intellectual property, or market position.",
        "data": "Product and strategy leaders, and the value of the IP involved.",
    },
    "secondary.reputation": {
        "path": "secondary.reputation",
        "label": "Reputation",
        "unit": "$ per secondary loss event",
        "kind": "money",
        "help": "The financial effects of damaged reputation: customer churn, lost or delayed deals, higher cost of capital.",
        "data": "Sales and customer success (revenue per customer, churn after past incidents), finance.",
    },
}

# Placeholder hints shown in empty factor inputs, by kind.
PLACEHOLDERS = {
    "freq": ["0.5", "2", "6"],
    "pct": ["2", "8", "20"],
    "score": ["40", "60", "80"],
    "money": ["50k", "150k", "400k"],
}


def content_payload() -> dict:
    """Everything the frontend needs to render factor rows, as plain JSON."""
    return {
        "factors": F,
        "forms": {k: [{"key": key, "label": label} for key, label in v] for k, v in FORMS.items()},
        "confidence": CONF,
        "placeholders": PLACEHOLDERS,
    }
