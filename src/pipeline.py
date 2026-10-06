import hashlib
import json
import os
from .extract import extract, ExtractionError, MAX_BYTES
from .schemas import Invoice
from .validate import validate_invoice, cents
from .database import connect, normalize, rows

def ingest(data,filename,path,mode='demo',model=None,threshold_cents=1_000_000):
    if len(data)>MAX_BYTES: raise ExtractionError('File exceeds 10 MB.')
    if threshold_cents < 0: raise ValueError('Review threshold must be nonnegative.')
    digest=hashlib.sha256(data).hexdigest()
    with connect(path) as db:
        existing=db.execute('SELECT id FROM documents WHERE source_hash=?',(digest,)).fetchone()
        if existing: return {'id':existing['id'],'reused':True}
    raw=None; invoice=None; findings=[]; error=None
    try:
        raw=extract(data,filename,mode,model)
        invoice=Invoice.model_validate(raw)
        findings=validate_invoice(invoice,threshold_cents)
    except Exception as e:
        # Persist failed extractions separately from schema-valid candidate invoices.
        error=str(e)[:3000]
    with connect(path) as db:
        db.execute('BEGIN IMMEDIATE')
        existing=db.execute('SELECT id FROM documents WHERE source_hash=?',(digest,)).fetchone()
        if existing: return {'id':existing['id'],'reused':True}
        vendor=normalize(invoice.vendor) if invoice else ''
        number=normalize(invoice.invoice_number) if invoice else ''
        if invoice and vendor and number:
            duplicate=db.execute("SELECT id FROM documents WHERE vendor_key=? AND invoice_key=? AND review_status!='rejected' AND invoice_json IS NOT NULL",(vendor,number)).fetchone()
            if duplicate: findings.append({'code':'duplicate_invoice','message':f'Vendor and invoice number match document #{duplicate["id"]}; verify before proceeding.'})
        status='failed' if error else ('needs_correction' if findings else 'ready')
        cur=db.execute('''INSERT INTO documents(source_hash,filename,mode,model,raw_json,invoice_json,vendor_key,invoice_key,currency,total_cents,findings_json,validation_status,error)
        VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)''',(digest,filename,mode,(model or os.getenv('OLLAMA_MODEL','qwen3:4b-instruct')) if mode=='ollama' else None,
        json.dumps(raw) if raw is not None else None,invoice.model_dump_json() if invoice else None,vendor,number,
        invoice.currency if invoice else None,cents(invoice.total) if invoice and invoice.total else None,json.dumps(findings),status,error))
        document_id=cur.lastrowid
        db.execute('INSERT INTO audit_events(document_id,action,actor,note) VALUES(?,?,?,?)',(document_id,'ingested','pipeline',f'{mode} extraction; validation {status}'))
    return {'id':document_id,'reused':False}

def approved_export(path):
    return [{'document_id':r['id'],'source_hash':r['source_hash'],'invoice':r['invoice']} for r in rows(path) if r['review_status']=='approved' and r['validation_status']=='ready']
