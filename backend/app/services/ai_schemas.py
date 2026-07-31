"""JSON schemas used by optional Claude structured-output requests."""

from __future__ import annotations

from typing import Any


NULLABLE_STRING: dict[str, Any] = {"type": ["string", "null"]}
NULLABLE_NUMBER: dict[str, Any] = {"type": ["number", "null"]}

RECEIPT_ITEM_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "code": NULLABLE_STRING,
        "name": {"type": "string"},
        "normalized_name": NULLABLE_STRING,
        "product_size": NULLABLE_STRING,
        "quantity": NULLABLE_NUMBER,
        "unit": NULLABLE_STRING,
        "unit_price": NULLABLE_NUMBER,
        "price": NULLABLE_NUMBER,
        "quantity_type": NULLABLE_STRING,
        "unit_label": NULLABLE_STRING,
        "explicit_quantity": {"type": ["boolean", "null"]},
        "source": NULLABLE_STRING,
    },
    "required": [],
    "additionalProperties": False,
}

RECEIPT_VALIDATION_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "is_receipt": {"type": ["boolean", "null"]},
        "confidence": NULLABLE_NUMBER,
    },
    "required": [],
    "additionalProperties": False,
}

RECEIPT_SCAN_OUTPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "error": NULLABLE_STRING,
        "store": NULLABLE_STRING,
        "address": NULLABLE_STRING,
        "date": NULLABLE_STRING,
        "time": NULLABLE_STRING,
        "payment_method": NULLABLE_STRING,
        "transaction_number": NULLABLE_STRING,
        "receipt_number": NULLABLE_STRING,
        "invoice_number": NULLABLE_STRING,
        "order_number": NULLABLE_STRING,
        "subtotal": NULLABLE_NUMBER,
        "discount": NULLABLE_NUMBER,
        "tax": NULLABLE_NUMBER,
        "total": NULLABLE_NUMBER,
        "total_savings": NULLABLE_NUMBER,
        "items": {"type": "array", "items": RECEIPT_ITEM_SCHEMA},
        "handwritten_items": {"type": "array", "items": RECEIPT_ITEM_SCHEMA},
        "returned_items": {"type": "array", "items": RECEIPT_ITEM_SCHEMA},
        "manual_adjustments": {"type": "array", "items": RECEIPT_ITEM_SCHEMA},
        "validation": RECEIPT_VALIDATION_SCHEMA,
        "validation_notes": {"type": "array", "items": {"type": "string"}},
    },
    "required": [],
    "additionalProperties": False,
}
