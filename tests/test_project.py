import base64
import json
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch
from http.server import ThreadingHTTPServer
from urllib.request import Request, urlopen
from urllib.error import HTTPError
from pydantic import ValidationError
from src.schemas import Invoice
from src.extract import extract, ollama_extract, source_text, ExtractionError
from src.validate import validate_invoice
from src.pipeline import ingest, approved_export
from src.database import rows, review, audit
from app import handler_for
ROOT=Path(__file__).resolve().parents[1]
CLEAN=(ROOT/'data/sample_invoices/01_clean.txt').read_bytes()

def invoice():return Invoice.model_validate(extract(CLEAN,'clean.txt'))

class Rules(unittest.TestCase):
    def test_clean(self):self.assertEqual(validate_invoice(invoice()),[])
    def test_cent_tolerance(self):
        inv=invoice();inv.total='109.01';self.assertEqual(validate_invoice(inv),[])
        inv.total='109.02';self.assertIn('total_mismatch',[x['code'] for x in validate_invoice(inv)])
    def test_missing_and_dates(self):
        inv=invoice();inv.invoice_number=None;inv.due_date='2026-09-01'
        self.assertEqual({x['code'] for x in validate_invoice(inv)},{'missing_invoice_number','date_order'})
    def test_line_math(self):
        inv=invoice();inv.line_items[0].quantity='3'
        self.assertIn('line_math',[x['code'] for x in validate_invoice(inv)])
    def test_currency(self):
        inv=invoice();inv.currency='JPY'
        self.assertIn('unsupported_currency',[x['code'] for x in validate_invoice(inv)])
    def test_schema_rejects_bad_money_and_date(self):
        for field,value in [('total','NaN'),('total',100.0),('invoice_date','2026-02-30')]:
            raw=invoice().model_dump();raw[field]=value
            with self.assertRaises(ValidationError):Invoice.model_validate(raw)
    def test_credit_note_flag(self):
        inv=invoice();inv.total='-1.00'
        self.assertIn('negative_total',[x['code'] for x in validate_invoice(inv)])

class Storage(unittest.TestCase):
    def setUp(self):self.temp=tempfile.TemporaryDirectory();self.db=Path(self.temp.name)/'test.sqlite3'
    def tearDown(self):self.temp.cleanup()
    def test_fixture_outcomes_idempotence(self):
        for file in sorted((ROOT/'data/sample_invoices').glob('0[1-6]_*.txt')):ingest(file.read_bytes(),file.name,self.db)
        records=rows(self.db)
        self.assertEqual(len(records),6)
        self.assertEqual(sum(x['validation_status']=='ready' for x in records),1)
        self.assertEqual(sum(x['validation_status']=='failed' for x in records),1)
        self.assertEqual(sum(x['validation_status']=='needs_correction' for x in records),4)
        self.assertEqual(approved_export(self.db),[])
        self.assertTrue(ingest(CLEAN,'renamed.txt',self.db)['reused'])
        self.assertEqual(len(rows(self.db)),6)
    def test_approval_export_and_audit(self):
        r=ingest(CLEAN,'clean.txt',self.db)
        review(self.db,r['id'],'approved','Ben','Verified all fields against source.')
        self.assertEqual(len(approved_export(self.db)),1)
        self.assertEqual(len(audit(self.db,r['id'])),2)
        with self.assertRaises(ValueError):review(self.db,r['id'],'rejected','Ben','Changed mind')
    def test_exception_cannot_approve(self):
        file=ROOT/'data/sample_invoices/02_total_mismatch.txt'
        r=ingest(file.read_bytes(),file.name,self.db)
        with self.assertRaises(ValueError):review(self.db,r['id'],'approved','Ben','Checked')
        self.assertEqual(approved_export(self.db),[])
    def test_failed_extraction_retained(self):
        ingest(b'no fields here','bad.txt',self.db)
        r=rows(self.db)[0];self.assertEqual(r['validation_status'],'failed');self.assertIsNone(r['invoice'])
    def test_business_key_normalization(self):
        ingest(CLEAN,'clean.txt',self.db)
        ingest(CLEAN.replace(b'Cedarline Supplies',b'CEDARLINE   SUPPLIES')+b'\nCopy\n','copy.txt',self.db)
        self.assertIn('duplicate_invoice',[x['code'] for x in rows(self.db)[0]['findings']])
    def test_rejected_record_does_not_reserve_key(self):
        r=ingest(CLEAN,'clean.txt',self.db);review(self.db,r['id'],'rejected','Ben','Superseded source')
        ingest(CLEAN+b'\nCorrected source\n','corrected.txt',self.db)
        self.assertEqual(rows(self.db)[0]['validation_status'],'ready')

class Extraction(unittest.TestCase):
    def test_duplicate_labels(self):
        with self.assertRaises(ExtractionError):extract(CLEAN+b'\nTotal: 99.00','x.txt')
    def test_no_silent_truncation(self):
        with self.assertRaises(ExtractionError):source_text(b'x'*60001,'.txt')
    def test_blank_scanned_pdf_rejected(self):
        from io import BytesIO
        from pypdf import PdfWriter
        writer=PdfWriter();writer.add_blank_page(width=612,height=792);buf=BytesIO();writer.write(buf)
        with self.assertRaises(ExtractionError):source_text(buf.getvalue(),'.pdf')
    def test_ollama_schema_and_image_encoding(self):
        raw=invoice().model_dump()
        class Response:
            def __enter__(self):return self
            def __exit__(self,*args):pass
            def read(self,*args):return json.dumps({'message':{'content':json.dumps(raw)}}).encode()
        with patch('src.extract.urlopen',return_value=Response()) as mock:
            self.assertEqual(ollama_extract(b'imagebytes','.png',model='vision-test'),raw)
            payload=json.loads(mock.call_args.args[0].data)
            self.assertEqual(payload['format'],Invoice.model_json_schema())
            self.assertEqual(base64.b64decode(payload['messages'][1]['images'][0]),b'imagebytes')
    def test_nonlocal_endpoint_denied(self):
        with self.assertRaises(ExtractionError):ollama_extract(CLEAN,'.txt',endpoint='https://example.com')

class HTTP(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.db=Path(self.temp.name)/'http.sqlite3'
        self.server=ThreadingHTTPServer(('127.0.0.1',0),handler_for(self.db))
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True);self.thread.start()
        self.url='http://127.0.0.1:'+str(self.server.server_port)
    def tearDown(self):self.server.shutdown();self.server.server_close();self.thread.join();self.temp.cleanup()
    def post(self,path,body,origin=None):
        headers={'Content-Type':'application/json'}
        if origin:headers['Origin']=origin
        return urlopen(Request(self.url+path,data=json.dumps(body).encode(),headers=headers),timeout=5)
    def test_web_ingest_review_export(self):
        with urlopen(self.url) as response:self.assertIn(b'Invoice Intelligence',response.read())
        with self.post('/api/ingest',{'filename':'invoice.txt','data':base64.b64encode(CLEAN).decode()}) as response:r=json.load(response)
        with self.post('/api/review',{'id':r['id'],'action':'approved','actor':'Ben','note':'Verified source'}) as response:self.assertEqual(response.status,200)
        with urlopen(self.url+'/api/export') as response:self.assertEqual(len(json.load(response)),1)
    def test_cross_origin_blocked(self):
        with self.assertRaises(HTTPError) as error:self.post('/api/ingest',{},origin='https://untrusted.example')
        self.assertEqual(error.exception.code,403)
        error.exception.close()
    def test_invalid_json_body_shape(self):
        with self.assertRaises(HTTPError) as error:self.post('/api/ingest',[])
        self.assertEqual(error.exception.code,400)
        error.exception.close()

if __name__=='__main__':unittest.main()
