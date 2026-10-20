"""Session scoped, receipt driven execution; no hardware or billing adapters here."""
import os

def enabled(conn):
    value=(getattr(conn,'config',{}) or {}).get('harness',{}).get('enabled')
    return value is True if value is not None else os.getenv('FULL_TOOL_HARNESS','0')=='1'
