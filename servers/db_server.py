"""
Database (DB) MCP Server.
Provides tools, resources, and prompts for querying the enterprise relational database.
Implements deterministic security controls:
- Enforced SELECT-only query structure
- Strict table allowlist (strictly excluding credentials_vault and sqlite_master)
- Prohibits stacked queries (';') and dangerous keywords
- Output row limits (capped at 50 rows)
- Strict logging to stderr
"""

import os
import sys
import sqlite3
import re
import json
from typing import Dict, Any, List, Optional

# Allow standalone execution via python servers/db_server.py or MCP Inspector
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from servers.mcp_base import MCPServer

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")
DB_PATH = os.path.join(DATA_DIR, "company.db")

ALLOWED_TABLES = {"orders", "products", "customers", "employees"}
MAX_ROW_CAP = 50

server = MCPServer(name="db-server", version="1.0.0")

def get_db():
    # Connect in read-only URI mode when possible
    conn = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn

def validate_sql_query(query: str) -> tuple[bool, Optional[str]]:
    """
    Validates that a SQL query is strictly a single, read-only SELECT statement
    touching only allowed tables.
    """
    cleaned = query.strip()
    # Strip trailing semicolon if single statement
    if cleaned.endswith(";"):
        cleaned = cleaned[:-1].strip()

    # Reject stacked queries (any remaining semicolons)
    if ";" in cleaned:
        return False, "Security Error: Stacked or multi-statement queries are strictly prohibited."

    # Reject comments which may hide injection
    if "--" in cleaned or "/*" in cleaned or "*/" in cleaned:
        return False, "Security Error: SQL comments are not permitted in queries."

    # Must start with SELECT
    tokens = cleaned.split()
    if not tokens or tokens[0].upper() != "SELECT":
        return False, "Security Error: Only 'SELECT' queries are allowed. Modifying statements (INSERT, UPDATE, DELETE, DROP, ALTER) are rejected."

    # Disallow dangerous SQL keywords
    forbidden_keywords = [
        "DROP", "DELETE", "INSERT", "UPDATE", "ALTER", "CREATE", "ATTACH", "DETACH",
        "PRAGMA", "REINDEX", "VACUUM", "REPLACE", "EXEC", "EXECUTE"
    ]
    query_upper = query.upper()
    for kw in forbidden_keywords:
        # Check whole word match
        if re.search(r'\b' + kw + r'\b', query_upper):
            return False, f"Security Error: Prohibited SQL command or keyword '{kw}' detected."

    # Extract table names from FROM and JOIN clauses
    table_pattern = re.compile(r'\b(?:FROM|JOIN)\s+([a-zA-Z0-9_]+)', re.IGNORECASE)
    referenced_tables = table_pattern.findall(cleaned)

    if not referenced_tables:
        return False, "Security Error: Query must explicitly reference a valid table in FROM/JOIN."

    for tbl in referenced_tables:
        tbl_clean = tbl.lower()
        if tbl_clean not in ALLOWED_TABLES:
            return False, f"Security Error: Access to table '{tbl}' is forbidden. Allowed tables: {', '.join(sorted(ALLOWED_TABLES))}."

    return True, None

# -------------------------------------------------------------------------
# Tool 1: query_db
# -------------------------------------------------------------------------
def query_db_handler(args: Dict[str, Any]) -> str:
    raw_sql = args.get("sql_query")
    if raw_sql is None or str(raw_sql).strip() == "":
        return "Error: sql_query parameter is required and cannot be empty."

    sql = str(raw_sql).strip()

    is_valid, err_msg = validate_sql_query(sql)
    if not is_valid:
        return err_msg

    try:
        with get_db() as conn:
            cur = conn.cursor()
            cur.execute(sql)
            rows = cur.fetchmany(MAX_ROW_CAP + 1)

            if len(rows) > MAX_ROW_CAP:
                trimmed_rows = rows[:MAX_ROW_CAP]
                result_data = [dict(r) for r in trimmed_rows]
                return (
                    json.dumps(result_data, indent=2)
                    + f"\n\n[Notice: Results capped at {MAX_ROW_CAP} rows for performance and security.]"
                )

            if not rows:
                return "Query executed successfully. 0 rows returned."

            result_data = [dict(r) for r in rows]
            return json.dumps(result_data, indent=2)
    except sqlite3.Error as e:
        return f"Database Query Error: {str(e)}"

server.register_tool(
    name="query_db",
    description=(
        "Execute a read-only SQL query against the enterprise database. "
        "Allowed tables: orders, products, customers, employees. Max 50 rows returned. "
        "WHEN TO USE: Use when you need aggregates, counts, sum of revenue, join queries, or specific row lookups. "
        "WHEN NOT TO USE: Do NOT use for modifying data (INSERT, UPDATE, DELETE, DROP are forbidden). "
        "Do NOT query internal system tables or credentials."
    ),
    input_schema={
        "type": "object",
        "required": ["sql_query"],
        "properties": {
            "sql_query": {
                "type": "string",
                "description": "Standard SQLite SELECT query (e.g. 'SELECT status, count(*) FROM orders GROUP BY status')."
            }
        }
    },
    handler=query_db_handler
)

# -------------------------------------------------------------------------
# Tool 2: list_tables
# -------------------------------------------------------------------------
def list_tables_handler(args: Dict[str, Any]) -> str:
    table_metadata = [
        {"table_name": "customers", "description": "Client demographic and contact data (id, full_name, email, city, country)."},
        {"table_name": "orders", "description": "Customer purchase transaction records (order_id, customer_id, order_date, total_amount, status)."},
        {"table_name": "products", "description": "Inventory product listings and prices (product_id, name, category, price, stock_quantity)."},
        {"table_name": "employees", "description": "Staff roster and salary details (employee_id, full_name, department, title, salary)."}
    ]
    return json.dumps(table_metadata, indent=2)

server.register_tool(
    name="list_tables",
    description=(
        "List all accessible tables in the relational database along with their business descriptions. "
        "WHEN TO USE: Use when the user asks what tables or entities exist in the database before forming a query. "
        "WHEN NOT TO USE: Do NOT use when you already know the table name and want to fetch rows."
    ),
    input_schema={
        "type": "object",
        "properties": {}
    },
    handler=list_tables_handler
)

# -------------------------------------------------------------------------
# Tool 3: describe_table
# -------------------------------------------------------------------------
def describe_table_handler(args: Dict[str, Any]) -> str:
    raw_tbl = args.get("table_name")
    if raw_tbl is None or str(raw_tbl).strip() == "":
        return "Error: table_name parameter is required and cannot be empty."

    table_name = str(raw_tbl).strip().lower()
    if table_name not in ALLOWED_TABLES:
        return f"Error: Table '{table_name}' does not exist or is not queryable. Allowed tables: {', '.join(sorted(ALLOWED_TABLES))}."

    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute(f"PRAGMA table_info({table_name})")
        columns = [{"cid": row[0], "name": row[1], "type": row[2], "notnull": bool(row[3]), "pk": bool(row[5])} for row in cursor.fetchall()]

    return json.dumps({"table": table_name, "columns": columns}, indent=2)

server.register_tool(
    name="describe_table",
    description=(
        "Get the column names, data types, and primary key constraints for a specific table. "
        "WHEN TO USE: Use before writing SQL queries to ensure exact column names and types are known. "
        "WHEN NOT TO USE: Do NOT use to view the row data itself."
    ),
    input_schema={
        "type": "object",
        "required": ["table_name"],
        "properties": {
            "table_name": {
                "type": "string",
                "description": "Name of the table to inspect (e.g. 'orders', 'customers', 'products', 'employees')."
            }
        }
    },
    handler=describe_table_handler
)

# -------------------------------------------------------------------------
# Tool 4: sample_table
# -------------------------------------------------------------------------
def sample_table_handler(args: Dict[str, Any]) -> str:
    raw_tbl = args.get("table_name")
    if raw_tbl is None or str(raw_tbl).strip() == "":
        return "Error: table_name parameter is required and cannot be empty."

    table_name = str(raw_tbl).strip().lower()
    if table_name not in ALLOWED_TABLES:
        return f"Error: Table '{table_name}' is not in the allowed query list."

    raw_limit = args.get("limit", 5)
    try:
        limit = int(raw_limit)
        limit = max(1, min(limit, 10))
    except (ValueError, TypeError):
        limit = 5

    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute(f"SELECT * FROM {table_name} LIMIT {limit}")
        rows = [dict(r) for r in cursor.fetchall()]

    return json.dumps(rows, indent=2)

server.register_tool(
    name="sample_table",
    description=(
        "Fetch a small sample of rows (up to 10 rows) from a specific table to inspect actual data formats. "
        "WHEN TO USE: Use to preview date formatting, status enum strings, or sample values. "
        "WHEN NOT TO USE: Do NOT use for data analytics or full dataset retrieval."
    ),
    input_schema={
        "type": "object",
        "required": ["table_name"],
        "properties": {
            "table_name": {
                "type": "string",
                "description": "Name of the table to sample."
            },
            "limit": {
                "type": "integer",
                "description": "Number of sample rows to retrieve (default 5, maximum 10)."
            }
        }
    },
    handler=sample_table_handler
)

# -------------------------------------------------------------------------
# Resource 1: db://schema
# -------------------------------------------------------------------------
def read_db_schema() -> str:
    schema_doc = """-- Enterprise Analytics Database Schema
CREATE TABLE customers (
    customer_id INTEGER PRIMARY KEY,
    full_name TEXT NOT NULL,
    email TEXT NOT NULL,
    city TEXT NOT NULL,
    country TEXT NOT NULL
);

CREATE TABLE products (
    product_id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    category TEXT NOT NULL,
    price REAL NOT NULL,
    stock_quantity INTEGER NOT NULL
);

CREATE TABLE orders (
    order_id INTEGER PRIMARY KEY,
    customer_id INTEGER NOT NULL REFERENCES customers(customer_id),
    order_date TEXT NOT NULL,
    total_amount REAL NOT NULL,
    status TEXT NOT NULL -- 'COMPLETED', 'SHIPPED', 'PROCESSING', 'CANCELLED'
);

CREATE TABLE employees (
    employee_id INTEGER PRIMARY KEY,
    full_name TEXT NOT NULL,
    department TEXT NOT NULL,
    title TEXT NOT NULL,
    salary REAL NOT NULL
);
"""
    return schema_doc

server.register_resource(
    uri="db://schema",
    name="Database Schema DDL",
    description="Full DDL specifications and column relationships for all queryable business tables.",
    mime_type="text/x-sql",
    reader=read_db_schema
)

# -------------------------------------------------------------------------
# Prompt 1: analyst_prompt
# -------------------------------------------------------------------------
def generate_analyst_prompt(args: Dict[str, Any]) -> list:
    task = args.get("task_description", "General data overview")
    return [
        {
            "role": "user",
            "content": {
                "type": "text",
                "text": (
                    f"You are a Senior SQL Analyst. Given the database schema (customers, products, orders, employees), "
                    f"write a safe, efficient SELECT query to answer: {task}."
                )
            }
        }
    ]

server.register_prompt(
    name="analyst_prompt",
    description="Generates an analytics prompt instructing the model to synthesize SQL queries safely.",
    arguments=[
        {"name": "task_description", "description": "The analytical goal or business question", "required": True}
    ],
    generator=generate_analyst_prompt
)

if __name__ == "__main__":
    server.run_stdio()
