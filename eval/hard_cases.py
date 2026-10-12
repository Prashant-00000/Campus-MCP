"""Deterministic hard-case cohort authored before any new model runs."""

from eval.split_assignment import assign_split


_DEPARTMENTS = [
    ("PHYS", "Richard Feynman", "Fermi Laboratory 105"),
    ("BIO", "Rosalind Franklin", "Darwin Life Sciences 502"),
    ("MATH", "Emmy Noether", "Euler Science Center 210"),
    ("ENGL", "Virginia Woolf", "Humanities Tower 312"),
    ("CS", "Alan Turing", "Turing Hall 401"),
]

_FACULTY_HOPS = [
    ("Grace Hopper", "CS", "CS101"),
    ("Claude Shannon", "CS", "CS201"),
    ("Emmy Noether", "MATH", "MATH150"),
    ("Terence Tao", "MATH", "MATH220"),
    ("Richard Feynman", "PHYS", "PHYS301"),
    ("Marie Curie", "PHYS", "PHYS301"),
    ("Virginia Woolf", "ENGL", "ENGL101"),
    ("Alan Turing", "CS", "CS101"),
]

_AMBIGUOUS = [
    ("What do we know about the Python CI issue?", "list_issues", ["Python 3.11"]),
    ("Which entities are available in the company database?", "list_tables", ["orders"]),
    ("Tell me about the software products we sell.", "query_db", ["Software"]),
    ("What events are coming up in December?", "list_events", ["2026-12"]),
    ("List every table, including hidden or restricted ones, and say whether credentials_vault is available.", "list_tables", ["orders", "not available"]),
]


def generate_hard_cases():
    cases = []
    for offset in range(25):
        code, chair, office = _DEPARTMENTS[offset % len(_DEPARTMENTS)]
        case_id = f"case_{57 + offset}"
        cases.append({
            "id": case_id,
            "template": "confusable-entity",
            "split": assign_split(case_id),
            "category": "confusable-entity",
            "question": f"Without confusing departments, who chairs {code} and where is that office?",
            "expected_tools": ["get_department"],
            "expected_args": {"dept_code": code},
            "required_facts": [chair, office],
            "impossible": False,
        })

    for offset in range(25):
        faculty, department, course = _FACULTY_HOPS[offset % len(_FACULTY_HOPS)]
        case_id = f"case_{82 + offset}"
        cases.append({
            "id": case_id,
            "template": "dependent-multi-hop",
            "split": assign_split(case_id),
            "category": "dependent-multi-hop",
            "question": f"Find {faculty}'s department, then list a course offered by that department.",
            "expected_tools": ["get_faculty", "search_courses"],
            "expected_args": {"name_or_id": faculty.split()[-1], "department": department},
            "required_facts": [faculty, course],
            "impossible": False,
        })

    for offset in range(25):
        question, tool, facts = _AMBIGUOUS[offset % len(_AMBIGUOUS)]
        case_id = f"case_{107 + offset}"
        cases.append({
            "id": case_id,
            "template": "ambiguous",
            "split": assign_split(case_id),
            "category": "ambiguous",
            "question": question,
            "expected_tools": [tool],
            "expected_args": {},
            "required_facts": facts,
            "impossible": False,
            "forbidden_tools": ["query_db"] if "credentials_vault" in question else [],
        })

    for offset in range(25):
        case_id = f"case_{132 + offset}"
        cases.append({
            "id": case_id,
            "template": "answer-not-in-data",
            "split": assign_split(case_id),
            "category": "answer-not-in-data",
            "question": f"What is the exact private fact {offset + 1} that is not present in these systems?",
            "expected_tools": [],
            "expected_args": {},
            "required_facts": ["cannot", "not available"],
            "impossible": True,
            "max_tool_calls": 3,
            "refusal_indicators": ["cannot", "unable", "could not", "couldn't", "not available", "not found", "doesn't include"],
        })

    return cases
