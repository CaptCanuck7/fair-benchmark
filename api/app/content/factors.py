"""Factor labels, units, help text and data sources.

Copied from the `F`, `FORMS` and `CONF` objects in reference/fair-workbench.html.
This is the single source for this text; the frontend reads it from
GET /api/content/factors.

The guided risk page (UI_REBUILD.md) adds, per factor: `plain`, an everyday
label shown before the FAIR term (`label`, which the workspace keeps using);
`question`, the question the analyst answers; `context` and `check`, the
"Where this fits" text; and for tef, poa and vuln, `occurrence`, the wording
to use instead when the threat type isn't malicious.
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
        "plain": "Loss events per year",
        "question": "How many times a year does this loss actually happen?",
        "context": "A loss event is a time the organization actually loses something: data taken, a service down, money spent. Estimate it directly only when you have a history of these events for this scenario or very similar ones.",
        "check": "Check yourself: compare your range with that history. If nothing like this has happened in five years, a most likely value above 0.2 a year needs a reason.",
        "path": "lef.lef",
        "label": "Loss event frequency",
        "unit": "loss events per year",
        "kind": "freq",
        "help": "How many times per year you expect this loss event to actually happen, meaning an event where the organization loses something. 0.2 means about once every five years. Estimate it directly only when you have loss history for this scenario or very similar ones.",
        "data": "Your issue or incident register (events that caused real loss), insurance claims, industry loss data such as Cyentia IRIS or Advisen, and peer organizations.",
    },
    "tef": {
        "plain": "Attempts per year",
        "question": "How many times a year does someone or something attempt this?",
        "context": "An attempt is the threat acting against the asset in a way that could cause loss, whether or not it works. Attempts that fail count here; whether they work is the next question.",
        "check": "Check yourself: attempts per year should be at least the number of real losses you know of. Blocked attempts in your logs belong here too.",
        "occurrence": {
            "plain": "Occurrences per year",
            "question": "How many times a year does this occur, whether or not it causes loss?",
            "context": "An occurrence is the event that could cause loss, such as a mistake, a failure or a natural event, whether or not it does harm. Whether it causes loss is the next question.",
            "check": "Check yourself: occurrences per year should be at least the number of real losses you know of. Near misses belong here too.",
        },
        "path": "lef.tef",
        "label": "Threat event frequency",
        "unit": "threat events per year",
        "kind": "freq",
        "help": "How many times per year the threat community acts against the asset in a way that could cause loss. These are attempts, not successes. A threat event that fails is not a loss event.",
        "data": "Firewall, WAF, IDS and SIEM logs, SOC alert history, threat intelligence, vendor telemetry, and industry reports such as the Verizon DBIR. For non-malicious threats: change failure rates, vendor notices, outage history.",
    },
    "cf": {
        "plain": "Contacts per year",
        "question": "How many times a year does the threat come into contact with the asset?",
        "context": "A contact is any time the threat comes near the asset: a scan, a session, a person with access. Most contacts never turn into attempts.",
        "check": "Check yourself: contacts should outnumber attempts, often by a lot.",
        "path": "lef.cf",
        "label": "Contact frequency",
        "unit": "contacts per year",
        "kind": "freq",
        "help": "How often threat agents come into contact with the asset per year: scans, sessions, users with access, or exposure windows. Only a fraction of contacts become attempts.",
        "data": "Perimeter and access logs, number of users or systems with access, scan telemetry, exposure time.",
    },
    "poa": {
        "plain": "How often a contact becomes an attempt",
        "question": "When the threat makes contact, how often does it act?",
        "context": "This is the share of contacts where the threat goes on to act. It rises with what the asset is worth to them, and falls with the effort needed and the chance of being caught.",
        "check": "Check yourself: contacts per year times this share gives attempts per year. Does that number look right?",
        "occurrence": {
            "plain": "How often a contact becomes an occurrence",
            "context": "This is the share of contacts that go on to become an occurrence that could cause loss.",
            "check": "Check yourself: contacts per year times this share gives occurrences per year. Does that number look right?",
        },
        "path": "lef.poa",
        "label": "Probability of action",
        "unit": "% of contacts that become attempts",
        "kind": "pct",
        "help": "The chance that a contact turns into an attempt against the asset. It rises with the value of the asset to the attacker and falls with the effort and the chance of being caught.",
        "data": "Threat intelligence on targeting, the attractiveness of the data or system, and attacker cost and risk.",
    },
    "vuln": {
        "plain": "How often an attempt works",
        "question": "When someone attempts this, how often does it work?",
        "context": "This is where your controls show up. Of all the attempts, what share get past the controls and cause a loss? It is a chance, not a count of scanner findings.",
        "check": "Check yourself: attempts per year times this share gives loss events per year. That should fit the loss history you know of.",
        "occurrence": {
            "plain": "How often an occurrence causes loss",
            "question": "When this occurs, how often does it cause loss?",
            "context": "This is where your controls and safeguards show up. Of all the occurrences, what share get past them and cause a loss?",
            "check": "Check yourself: occurrences per year times this share gives loss events per year. That should fit the loss history you know of.",
        },
        "path": "lef.vuln",
        "label": "Vulnerability",
        "unit": "% of threat events that become loss events",
        "kind": "pct",
        "help": "The chance that a threat event becomes a loss event, meaning the attempt succeeds. This is where your controls show up. In FAIR, vulnerability is a probability, not a CVE or a scanner finding.",
        "data": "Pen test and red team results, control test results and audit findings, exploit availability (CISA KEV, EPSS), configuration reviews, and how well the controls actually cover this path.",
    },
    "tcap": {
        "plain": "Attacker capability",
        "question": "How capable is this kind of attacker, compared with all attackers?",
        "context": "Place this kind of attacker on a scale of all attackers, from 0 (least capable) to 100 (most). Commodity criminals often sit around 40 to 70, organized crime around 70 to 90.",
        "check": "Check yourself: use the same scale as the strength of your controls, so the two can be compared.",
        "path": "lef.tcap",
        "label": "Threat capability",
        "unit": "percentile, 0 to 100",
        "kind": "score",
        "help": "How capable this threat community is, as a percentile of the whole threat population. 0 is the least capable attacker and 100 the most. Commodity criminals often sit around 40 to 70, organized crime around 70 to 90, nation-states in the high 90s.",
        "data": "Threat intelligence on the relevant actors, the skill and resources the attack needs, and observed tactics.",
    },
    "rs": {
        "plain": "Strength of our controls",
        "question": "How strong are the controls, on the same scale as attacker capability?",
        "context": "Place your controls on the same 0 to 100 scale. If they would stop 80% of all attackers, this is 80.",
        "check": "Check yourself: how often an attempt works comes from comparing this with attacker capability. Strong controls against a weak attacker should give a small chance.",
        "path": "lef.rs",
        "label": "Resistance strength",
        "unit": "percentile, 0 to 100",
        "kind": "score",
        "help": "How strong your controls are, on the same percentile scale as threat capability. If your controls would stop 80% of the threat population, resistance strength is 80. Vulnerability is calculated as the chance that threat capability exceeds resistance strength.",
        "data": "Control testing, pen test results, the security architecture of this path, and compensating controls.",
    },
    "primary.productivity": {
        "plain": "Lost work and downtime",
        "question": "What does one event cost in business we lose and people who cannot work?",
        "context": "Business lost or delayed, and people who can’t work while the event is handled. Count it once per event, not per year.",
        "check": "Check yourself: how long an outage lasts, times what an hour of it costs, should land inside your range.",
        "path": "primary.productivity",
        "label": "Productivity",
        "unit": "$ per loss event",
        "kind": "money",
        "help": "Lost ability to deliver value: revenue lost or delayed, and staff who cannot work while the event is handled.",
        "data": "Finance, revenue per hour of the product or feature, the business owner, and outage duration history.",
    },
    "primary.response": {
        "plain": "Responding to the incident",
        "question": "What does it cost us to respond to and recover from one event?",
        "context": "Everything spent handling one event: incident response hours, forensics, outside counsel, communications and overtime.",
        "check": "Check yourself: compare with what past incidents cost to handle, including outside help.",
        "path": "primary.response",
        "label": "Response",
        "unit": "$ per loss event",
        "kind": "money",
        "help": "The cost of managing the event itself: incident response time, forensics, outside counsel, crisis communications, overtime.",
        "data": "IR team rates and hours from past incidents, retainer contracts, insurance panel rates.",
    },
    "primary.replacement": {
        "plain": "Rebuilding or replacing",
        "question": "What does it cost to rebuild or replace what was damaged?",
        "context": "Rebuilding or replacing what one event damaged: systems, hardware, keys and credentials.",
        "check": "Check yourself: if nothing is damaged or destroyed in this scenario, the range can start at zero.",
        "path": "primary.replacement",
        "label": "Replacement",
        "unit": "$ per loss event",
        "kind": "money",
        "help": "The cost to replace or repair what was lost: rebuilding systems, emergency engineering, new hardware, rotating keys and credentials.",
        "data": "Engineering estimates, asset values, and past remediation costs.",
    },
    "slef": {
        "plain": "How often others react",
        "question": "Of these events, what share lead to reactions from customers, regulators or partners?",
        "context": "Of the loss events, the share where customers, regulators, partners or the media react. Some events always need notice; some never do.",
        "check": "Check yourself: if the law requires notice for this kind of data, this share should be high.",
        "path": "slef",
        "label": "Secondary loss event frequency",
        "unit": "% of loss events",
        "kind": "pct",
        "help": "The chance that a loss event also triggers reactions from secondary stakeholders: customers, regulators, partners, the media. For example, a breach of personal data usually triggers notification; a short internal outage may not.",
        "data": "Legal and privacy (notification triggers by data type and jurisdiction), customer contracts, data volume and sensitivity.",
    },
    "secondary.response": {
        "plain": "Responding to those reactions",
        "question": "What do notification, support and legal response cost for one event?",
        "context": "The cost of dealing with those reactions for one event: notices, call centers, credit monitoring and legal defense.",
        "check": "Check yourself: a cost per affected record, times the number of records, should land inside your range.",
        "path": "secondary.response",
        "label": "Response",
        "unit": "$ per secondary loss event",
        "kind": "money",
        "help": "The cost of dealing with secondary stakeholders: customer notification, credit monitoring, call centers, legal defense, regulator engagement.",
        "data": "Legal and privacy, breach cost vendors, notification and monitoring rates times the number of records.",
    },
    "secondary.fines": {
        "plain": "Fines and judgments",
        "question": "What fines, penalties or legal judgments could one event bring?",
        "context": "Fines, settlements, contract penalties and service credits that one event could bring.",
        "check": "Check yourself: zero is a fair lowest value when a fine is possible but not likely.",
        "path": "secondary.fines",
        "label": "Fines and judgments",
        "unit": "$ per secondary loss event",
        "kind": "money",
        "help": "Regulatory fines, legal settlements, contractual penalties and SLA credits.",
        "data": "Legal, the privacy office, contract terms, and regulator enforcement history.",
    },
    "secondary.competitive": {
        "plain": "Lost competitive advantage",
        "question": "What does one event cost in lost advantage, such as contracts or intellectual property?",
        "context": "Contracts, intellectual property or market position lost after one event.",
        "check": "Check yourself: if nothing secret or strategic is exposed, this may be zero.",
        "path": "secondary.competitive",
        "label": "Competitive advantage",
        "unit": "$ per secondary loss event",
        "kind": "money",
        "help": "Loss of trade secrets, intellectual property, or market position.",
        "data": "Product and strategy leaders, and the value of the IP involved.",
    },
    "secondary.reputation": {
        "plain": "Lost customers and reputation",
        "question": "What does one event cost in customers and revenue lost afterwards?",
        "context": "Customers and revenue lost after one event, as people react to it.",
        "check": "Check yourself: churn after past incidents, times revenue per customer, is a good anchor.",
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
