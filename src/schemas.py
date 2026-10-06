"""The extraction contract. Missing values stay null; never invent financial data."""
from typing import Annotated
from datetime import date
from pydantic import BaseModel, ConfigDict, StringConstraints, field_validator
Money = Annotated[str, StringConstraints(pattern=r'^-?\d+\.\d{2}$')]
Quantity = Annotated[str, StringConstraints(pattern=r'^-?\d+(\.\d{1,4})?$')]

class LineItem(BaseModel):
    model_config = ConfigDict(extra='forbid')
    description: str | None
    quantity: Quantity | None
    unit_price: Money | None
    amount: Money | None

class Invoice(BaseModel):
    model_config = ConfigDict(extra='forbid')
    vendor: str | None
    invoice_number: str | None
    invoice_date: str | None
    due_date: str | None
    subtotal: Money | None
    tax: Money | None
    total: Money | None
    currency: str | None
    line_items: list[LineItem]
    extraction_notes: list[str]

    @field_validator('invoice_date', 'due_date')
    @classmethod
    def dates(cls, value):
        if value is not None:
            if len(value) != 10 or date.fromisoformat(value).isoformat() != value:
                raise ValueError('Date must be YYYY-MM-DD')
        return value

    @field_validator('vendor', 'invoice_number', 'currency')
    @classmethod
    def blank_to_none(cls, value):
        if value is None: return None
        return value.strip() or None
