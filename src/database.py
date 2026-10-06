from contextlib import contextmanager
"""SQLite staging records, human decisions, and append-only application audit events."""
import json
import sqlite3
import unicodedata
from pathlib import Path

def normalize(s):
    return ' '.join(unicodedata.normalize('NFKC',s or '').casefold().split())

@contextmanager
def connect(path):
    Path(path).parent.mkdir(parents=True,exist_ok=True)
    db=sqlite3.connect(path, timeout=20)
    try:
        db.row_factory = sqlite3.Row
        db.executescript('''
        CREATE TABLE IF NOT EXISTS documents (
          id INTEGER PRIMARY KEY, source_hash TEXT UNIQUE NOT NULL, filename TEXT NOT NULL,
          created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
          mode TEXT NOT NULL, model TEXT, raw_json TEXT, invoice_json TEXT,
          vendor_key TEXT, invoice_key TEXT, currency TEXT, total_cents INTEGER,
          findings_json TEXT NOT NULL, validation_status TEXT NOT NULL,
          review_status TEXT NOT NULL DEFAULT 'pending', error TEXT);
        CREATE INDEX IF NOT EXISTS business_key ON documents(vendor_key,invoice_key);
        CREATE TABLE IF NOT EXISTS audit_events (
          id INTEGER PRIMARY KEY, document_id INTEGER NOT NULL,
          created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
          action TEXT NOT NULL, actor TEXT NOT NULL, note TEXT NOT NULL);
        ''')
        with db:
            yield db
    finally:
        db.close()

def rows(path):
    with connect(path) as db: out=[dict(r) for r in db.execute('SELECT * FROM documents ORDER BY id DESC')]
    for r in out:
        r['invoice']=json.loads(r.pop('invoice_json')) if r['invoice_json'] else None
        r['findings']=json.loads(r.pop('findings_json'))
        r['raw']=json.loads(r.pop('raw_json')) if r['raw_json'] else None
    return out

def review(path, document_id, action, actor, note):
    if action not in ('approved','rejected'): raise ValueError('Review action must be approved or rejected.')
    if not actor.strip() or not note.strip(): raise ValueError('Reviewer name and source verification note are required.')
    with connect(path) as db:
        db.execute('BEGIN IMMEDIATE')
        row=db.execute('SELECT * FROM documents WHERE id=?',(document_id,)).fetchone()
        if row is None: raise ValueError('Document does not exist.')
        if row['review_status']!='pending': raise ValueError('Document already reviewed.')
        if action=='approved' and row['validation_status']!='ready': raise ValueError('Resolve findings before approval. Re-upload a corrected source as a new document.')
        db.execute('UPDATE documents SET review_status=? WHERE id=?',(action,document_id))
        db.execute('INSERT INTO audit_events(document_id,action,actor,note) VALUES(?,?,?,?)',(document_id,action,actor.strip(),note.strip()))

def audit(path,document_id):
    with connect(path) as db: return [dict(r) for r in db.execute('SELECT * FROM audit_events WHERE document_id=? ORDER BY id',(document_id,))]
