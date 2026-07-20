"""SQLite state store. Agents never touch SQL — only enforcement.py functions.
PII scoping and append-only logging are properties of THIS layer, not of prompts."""

import sqlite3, time, json, os

DB_PATH = os.environ.get("KHAAO_DB", "/home/claude/khaao/khaao.db")

SCHEMA = """
CREATE TABLE IF NOT EXISTS restaurants(
  id INTEGER PRIMARY KEY, name TEXT, location TEXT, status TEXT DEFAULT 'active',
  rating REAL DEFAULT 0, rating_count INTEGER DEFAULT 0,
  payout_number TEXT, commission_free_left INTEGER DEFAULT 10);

CREATE TABLE IF NOT EXISTS customers(
  id INTEGER PRIMARY KEY, phone TEXT, address TEXT);           -- PII lives here only

CREATE TABLE IF NOT EXISTS orders(
  id INTEGER PRIMARY KEY, restaurant_id INTEGER, customer_id INTEGER,
  items TEXT, total INTEGER, status TEXT DEFAULT 'placed',
  created_at REAL, updated_at REAL);

CREATE TABLE IF NOT EXISTS refunds(
  id INTEGER PRIMARY KEY, order_id INTEGER UNIQUE, amount INTEGER,
  reason TEXT, approved_by TEXT, created_at REAL);

CREATE TABLE IF NOT EXISTS escalations(
  id INTEGER PRIMARY KEY, category TEXT, severity TEXT, issue TEXT,
  recommendation TEXT, status TEXT DEFAULT 'open', created_at REAL);

CREATE TABLE IF NOT EXISTS run_log(
  id INTEGER PRIMARY KEY, ts REAL, agent TEXT, event TEXT, detail TEXT);
"""

def conn():
    c = sqlite3.connect(DB_PATH)
    c.row_factory = sqlite3.Row
    return c

def init():
    with conn() as c:
        c.executescript(SCHEMA)

def now():
    return time.time()

# ---- append-only log: no update/delete path exists anywhere in this codebase ----
def append_log(agent: str, event: str, detail: dict, c=None):
    row = (now(), agent, event, json.dumps(detail, ensure_ascii=False))
    if c is not None:
        c.execute("INSERT INTO run_log(ts,agent,event,detail) VALUES(?,?,?,?)", row)
    else:
        with conn() as c2:
            c2.execute("INSERT INTO run_log(ts,agent,event,detail) VALUES(?,?,?,?)", row)

def read_log(since_ts: float = 0):
    with conn() as c:
        return [dict(r) for r in c.execute(
            "SELECT * FROM run_log WHERE ts>=? ORDER BY id", (since_ts,))]
