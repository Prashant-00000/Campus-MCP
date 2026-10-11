"""
College MCP Server.
Provides tools, resources, and prompts for academic courses, departments, faculty, and campus events.
Follows MCP standard JSON-RPC 2.0 over stdio with output capping and stderr logging.
"""

import os
import sqlite3
import json
from typing import Dict, Any, Optional
from servers.mcp_base import MCPServer

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")
DB_PATH = os.path.join(DATA_DIR, "college.db")

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

server = MCPServer(name="college-server", version="1.0.0")

# -------------------------------------------------------------------------
# Tool 1: search_courses
# -------------------------------------------------------------------------
def search_courses_handler(args: Dict[str, Any]) -> str:
    query = args.get("query", "").strip()
    department = args.get("department")
    level_cap = args.get("level_cap")

    sql = "SELECT course_code, title, department, credits, instructor_id, level, description FROM courses WHERE 1=1"
    params = []

    if query:
        sql += " AND (title LIKE ? OR description LIKE ? OR course_code LIKE ?)"
        term = f"%{query}%"
        params.extend([term, term, term])

    if department:
        sql += " AND department = ?"
        params.append(department.upper())

    if level_cap:
        sql += " AND level <= ?"
        params.append(int(level_cap))

    sql += " ORDER BY level, course_code LIMIT 10"

    with get_db() as conn:
        rows = conn.execute(sql, params).fetchall()

    if not rows:
        return "No matching courses found in the catalog."

    results = [dict(row) for row in rows]
    return json.dumps(results, indent=2)

server.register_tool(
    name="search_courses",
    description=(
        "Search academic courses in the university catalog by keyword, department code, or max course level. "
        "WHEN TO USE: Use when the user asks about available classes, course offerings, credit hours, prerequisites, or syllabi. "
        "WHEN NOT TO USE: Do NOT use to look up campus events, department administration emails, or faculty office hours."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "Keyword to match against course title, code, or description (e.g. 'algorithms', 'physics', 'CS101')."
            },
            "department": {
                "type": "string",
                "description": "Optional department code filter (e.g. 'CS', 'MATH', 'PHYS', 'ENGL')."
            },
            "level_cap": {
                "type": "integer",
                "description": "Optional upper bound on course level (e.g. 200 for lower-division only, 400 for all undergraduate)."
            }
        }
    },
    handler=search_courses_handler
)

# -------------------------------------------------------------------------
# Tool 2: get_department
# -------------------------------------------------------------------------
def get_department_handler(args: Dict[str, Any]) -> str:
    dept_code = args.get("dept_code", "").strip().upper()
    if not dept_code:
        return "Error: dept_code is required."

    with get_db() as conn:
        row = conn.execute("SELECT * FROM departments WHERE code = ?", (dept_code,)).fetchone()

    if not row:
        return f"Department with code '{dept_code}' not found."

    return json.dumps(dict(row), indent=2)

server.register_tool(
    name="get_department",
    description=(
        "Retrieve official directory and administrative details for a specific academic department. "
        "WHEN TO USE: Use when the user asks for the department chair, main office location, or administrative contact email. "
        "WHEN NOT TO USE: Do NOT use to list course offerings or look up individual faculty member office hours."
    ),
    input_schema={
        "type": "object",
        "required": ["dept_code"],
        "properties": {
            "dept_code": {
                "type": "string",
                "description": "The uppercase department code (e.g. 'CS', 'MATH', 'PHYS', 'ENGL', 'BIO')."
            }
        }
    },
    handler=get_department_handler
)

# -------------------------------------------------------------------------
# Tool 3: list_events
# -------------------------------------------------------------------------
def list_events_handler(args: Dict[str, Any]) -> str:
    category = args.get("category")

    sql = "SELECT id, title, date, location, category, description FROM events WHERE 1=1"
    params = []

    if category:
        sql += " AND category = ?"
        params.append(category.lower())

    sql += " ORDER BY date ASC LIMIT 10"

    with get_db() as conn:
        rows = conn.execute(sql, params).fetchall()

    if not rows:
        return "No scheduled campus events found matching the criteria."

    return json.dumps([dict(row) for row in rows], indent=2)

server.register_tool(
    name="list_events",
    description=(
        "List scheduled campus events, academic symposiums, career fairs, and workshops. "
        "WHEN TO USE: Use when the user asks about campus calendar, dates of hackathons, career fairs, or guest lectures. "
        "WHEN NOT TO USE: Do NOT use to search for academic course schedules or grade deadlines."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "category": {
                "type": "string",
                "enum": ["academic", "career", "workshop", "sports"],
                "description": "Optional category filter: 'academic', 'career', 'workshop', or 'sports'."
            }
        }
    },
    handler=list_events_handler
)

# -------------------------------------------------------------------------
# Tool 4: get_faculty
# -------------------------------------------------------------------------
def get_faculty_handler(args: Dict[str, Any]) -> str:
    name_or_id = args.get("name_or_id", "").strip()
    if not name_or_id:
        return "Error: name_or_id parameter is required."

    sql = "SELECT id, name, department, title, email, research_area, office_hours FROM faculty WHERE id = ? OR name LIKE ? LIMIT 5"
    with get_db() as conn:
        rows = conn.execute(sql, (name_or_id.upper(), f"%{name_or_id}%")).fetchall()

    if not rows:
        return f"No faculty member found matching '{name_or_id}'."

    return json.dumps([dict(row) for row in rows], indent=2)

server.register_tool(
    name="get_faculty",
    description=(
        "Retrieve faculty profiles, research areas, office locations, and office hours. "
        "WHEN TO USE: Use when the user asks about a professor's contact email, office hours, or research specialization. "
        "WHEN NOT TO USE: Do NOT use to list department-wide graduation requirements or general courses."
    ),
    input_schema={
        "type": "object",
        "required": ["name_or_id"],
        "properties": {
            "name_or_id": {
                "type": "string",
                "description": "The professor's faculty ID (e.g. 'FAC01') or partial/full name (e.g. 'Turing', 'Grace Hopper')."
            }
        }
    },
    handler=get_faculty_handler
)

# -------------------------------------------------------------------------
# Resource 1: college://catalog-summary
# -------------------------------------------------------------------------
def read_catalog_summary() -> str:
    with get_db() as conn:
        dept_count = conn.execute("SELECT COUNT(*) FROM departments").fetchone()[0]
        course_count = conn.execute("SELECT COUNT(*) FROM courses").fetchone()[0]
        faculty_count = conn.execute("SELECT COUNT(*) FROM faculty").fetchone()[0]

    return (
        f"College Catalog Overview:\n"
        f"- Active Departments: {dept_count} (CS, MATH, PHYS, ENGL, BIO)\n"
        f"- Total Listed Courses: {course_count}\n"
        f"- Full-time Faculty: {faculty_count}\n"
        f"- Minimum Graduation Credits: 120 credit hours\n"
        f"- Academic Calendar: Fall Semester (Sep-Dec), Spring Semester (Jan-May)"
    )

server.register_resource(
    uri="college://catalog-summary",
    name="College Catalog Summary",
    description="High-level overview of collegiate structure, active departments, and graduation thresholds.",
    mime_type="text/plain",
    reader=read_catalog_summary
)

# -------------------------------------------------------------------------
# Prompt 1: advisor_prompt
# -------------------------------------------------------------------------
def generate_advisor_prompt(args: Dict[str, Any]) -> list:
    student_major = args.get("student_major", "Undeclared")
    year = args.get("year", "Freshman")
    return [
        {
            "role": "user",
            "content": {
                "type": "text",
                "text": (
                    f"You are the Academic Advising Director. Please outline recommended next-semester coursework "
                    f"and relevant department faculty advisors for a {year} majoring in {student_major}."
                )
            }
        }
    ]

server.register_prompt(
    name="advisor_prompt",
    description="Generates an academic advising prompt tailored to student major and academic standing.",
    arguments=[
        {"name": "student_major", "description": "Student's intended or declared major", "required": True},
        {"name": "year", "description": "Student standing (Freshman, Sophomore, Junior, Senior)", "required": False}
    ],
    generator=generate_advisor_prompt
)

if __name__ == "__main__":
    server.run_stdio()
