"""Verification script for college server checks."""
import sys
import json
sys.path.insert(0, '.')
from servers.college_server import server

# Check 1: list_events with hackathon query
print('=== Check 1: list_events with hackathon ===')
result = server.tools['list_events']['handler']({'query': 'hackathon'})
print(result[:500])

# Check 2: search_courses with no args
print('\n=== Check 2: search_courses empty ===')
result2 = server.tools['search_courses']['handler']({})
parsed = json.loads(result2)
print(f'Count: {len(parsed)} courses returned')
print('First:', json.dumps(parsed[0], indent=2) if parsed else 'None')

# Check 3: get_faculty with FAC01
print('\n=== Check 3: get_faculty FAC01 ===')
result3 = server.tools['get_faculty']['handler']({'name_or_id': 'FAC01'})
print(result3[:400])

# Check 4: SQL injection defense
print('\n=== Check 4: SQL injection attempt ===')
injection = "x' OR '1'='1"
result4 = server.tools['list_events']['handler']({'query': injection})
print(f"Injection result: {result4}")
result5 = server.tools['list_events']['handler']({'query': '%'})
print(f"Wildcard result: {result5[:200]}")
