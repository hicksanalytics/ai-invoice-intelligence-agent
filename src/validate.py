"""Deterministic financial checks. Model confidence is never treated as proof."""
from decimal import Decimal
from .schemas import Invoice

def cents(value: str) -> int:
    return int(Decimal(value) * 100)

def validate_invoice(invoice: Invoice, large_amount_cents=1_000_000):
    findings = []
    def add(code, message): findings.append({'code': code, 'message': message})
    for name in ['vendor', 'invoice_number', 'invoice_date', 'due_date', 'subtotal', 'tax', 'total', 'currency']:
        if getattr(invoice, name) is None: add('missing_' + name, f'{name} is missing; verify the source.')
    if invoice.currency and invoice.currency != 'USD':
        add('unsupported_currency', 'This MVP supports USD invoices only; do not mix currencies.')
    for name in ['subtotal', 'tax', 'total']:
        v = getattr(invoice, name)
        if v is not None and cents(v) < 0: add('negative_' + name, 'Credit notes and negative amounts need a separate workflow.')
    if all(getattr(invoice, k) is not None for k in ['subtotal', 'tax', 'total']):
        delta = cents(invoice.subtotal) + cents(invoice.tax) - cents(invoice.total)
        if abs(delta) > 1: add('total_mismatch', f'Subtotal plus tax differs from total by {abs(delta)} cents.')
    if invoice.invoice_date and invoice.due_date and invoice.due_date < invoice.invoice_date:
        add('date_order', 'Due date precedes invoice date.')
    if invoice.total is not None and cents(invoice.total) >= large_amount_cents:
        add('large_amount', f'Total meets the configured review threshold of ${large_amount_cents / 100:,.2f}.')
    if not invoice.line_items: add('missing_line_items', 'No line items were extracted.')
    for i, item in enumerate(invoice.line_items, 1):
        if not item.description: add('line_description', f'Line {i} needs a description.')
        if any(getattr(item, k) is None for k in ['quantity', 'unit_price', 'amount']):
            add('line_missing', f'Line {i} has missing numeric fields.'); continue
        if any(Decimal(getattr(item,k)) < 0 for k in ['quantity','unit_price','amount']):
            add('line_negative', f'Line {i} contains a negative amount or quantity.')
        expected = Decimal(item.quantity) * Decimal(item.unit_price)
        if abs(expected - Decimal(item.amount)) > Decimal('0.01'):
            add('line_math', f'Line {i} quantity times unit price differs from its amount.')
    if invoice.line_items and invoice.subtotal is not None and all(x.amount is not None for x in invoice.line_items):
        delta = sum(cents(x.amount) for x in invoice.line_items) - cents(invoice.subtotal)
        if abs(delta) > 1: add('line_subtotal', f'Line amounts differ from subtotal by {abs(delta)} cents.')
    if invoice.extraction_notes: add('extraction_uncertainty', 'Extraction notes require verification: ' + '; '.join(invoice.extraction_notes))
    return findings
