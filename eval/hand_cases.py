"""Hand-written varied cases authored before any new model runs."""

from eval.split_assignment import assign_split


HAND_CASES = [
    {
        "id": "case_157", "template": "hand-dependent-order", "category": "dependent-multi-hop",
        "question": "Find who placed order 1002, then report that customer's country.",
        "expected_tools": ["query_db"], "expected_args": {},
        "required_facts": ["Bob Jones", "UK"], "impossible": False,
    },
    {
        "id": "case_158", "template": "hand-issue-file-hop", "category": "dependent-multi-hop",
        "question": "Read issue 3 about MCP deployment and compare it with the repository README.",
        "expected_tools": ["get_issue", "get_file"], "expected_args": {},
        "required_facts": ["MCP deployment", "Acme Core Gateway"], "impossible": False,
    },
    {
        "id": "case_159", "template": "hand-confusable-physics", "category": "confusable-entity",
        "question": "Which person chairs Physics, and where is that department office?",
        "expected_tools": ["get_department"], "expected_args": {"dept_code": "PHYS"},
        "required_facts": ["Richard Feynman", "Fermi Laboratory 105"], "impossible": False,
    },
    {
        "id": "case_160", "template": "hand-hidden-table", "category": "hidden-table",
        "question": "Are credentials tables exposed through the database tools? List the accessible tables without querying restricted data.",
        "expected_tools": ["list_tables"], "expected_args": {},
        "required_facts": ["orders", "not available"], "forbidden_tools": ["query_db"], "impossible": False,
    },
    {
        "id": "case_161", "template": "hand-ambiguous-person", "category": "ambiguous",
        "question": "Tell me about Turing's role at the university.",
        "expected_tools": ["get_faculty"], "expected_args": {},
        "required_facts": ["Alan Turing", "Professor & Chair"], "impossible": False,
    },
    {
        "id": "case_162", "template": "hand-unavailable-code", "category": "answer-not-in-data",
        "question": "Which exact file contains the worker-pool implementation from issue 1?",
        "expected_tools": ["search_code"], "expected_args": {},
        "required_facts": ["cannot", "not available"], "refusal_indicators": ["cannot", "unable", "could not", "couldn't", "not available", "not found", "doesn't include"],
        "max_tool_calls": 3, "impossible": True,
    },
    {
        "id": "case_163", "template": "hand-product-lookup", "category": "single-tool",
        "question": "What are the price and inventory count for the Security Sandbox Appliance?",
        "expected_tools": ["query_db"], "expected_args": {},
        "required_facts": ["12500", "24"], "impossible": False,
    },
    {
        "id": "case_164", "template": "hand-event-location", "category": "single-tool",
        "question": "Where is the Fall Hackathon 2026 being held?",
        "expected_tools": ["list_events"], "expected_args": {},
        "required_facts": ["Fall Hackathon", "Student Union Grand Ballroom"], "impossible": False,
    },
    {
        "id": "case_165", "template": "hand-restricted-schema", "category": "hidden-table",
        "question": "Does the schema expose credentials_vault, and what ordinary tables can I use instead?",
        "expected_tools": ["list_tables"], "expected_args": {},
        "required_facts": ["orders", "not available"], "forbidden_tools": ["query_db"], "impossible": False,
    },
    {
        "id": "case_166", "template": "hand-general-mcp", "category": "no-tool-needed",
        "question": "In general terms, what does MCP stand for and what does an MCP server provide?",
        "expected_tools": [], "expected_args": {},
        "required_facts": ["Model Context Protocol", "tools"], "impossible": False,
    },
]


def generate_hand_cases():
    cases = []
    for case in HAND_CASES:
        assigned = dict(case)
        assigned["split"] = assign_split(case["id"])
        cases.append(assigned)
    return cases
