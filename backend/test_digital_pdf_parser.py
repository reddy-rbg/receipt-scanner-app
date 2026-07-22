import sys
import types
from pathlib import Path


dotenv = types.ModuleType("dotenv")
dotenv.load_dotenv = lambda: None
sys.modules["dotenv"] = dotenv

anthropic = types.ModuleType("anthropic")
anthropic.Anthropic = lambda api_key=None: None
sys.modules["anthropic"] = anthropic

supabase_module = types.ModuleType("supabase")
supabase_module.Client = object
supabase_module.create_client = lambda *args, **kwargs: None
sys.modules["supabase"] = supabase_module

from app.services import claude


def _pdf_escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def make_text_pdf(lines: list[str]) -> bytes:
    """Create a tiny text PDF without external writer dependencies."""
    stream = ["BT", "/F1 10 Tf", "48 760 Td"]
    for index, line in enumerate(lines):
        if index:
            stream.append("0 -16 Td")
        stream.append(f"({_pdf_escape(line)}) Tj")
    stream.append("ET")
    content = "\n".join(stream).encode("latin-1", errors="replace")
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        b"<< /Length " + str(len(content)).encode() + b" >>\nstream\n" + content + b"\nendstream",
    ]
    output = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for number, obj in enumerate(objects, 1):
        offsets.append(len(output))
        output.extend(f"{number} 0 obj\n".encode())
        output.extend(obj)
        output.extend(b"\nendobj\n")
    xref = len(output)
    output.extend(f"xref\n0 {len(objects) + 1}\n".encode())
    output.extend(b"0000000000 65535 f \n")
    for offset in offsets[1:]:
        output.extend(f"{offset:010d} 00000 n \n".encode())
    output.extend(f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode())
    return bytes(output)


def generated_receipt_pdf() -> tuple[bytes, list[tuple[str, float]], float, float, float]:
    items = [
        ("BASMATI RICE 10LB", 18.99),
        ("GOAT KEEMA 1LB", 14.98),
        ("GOAT LEG 1LB", 15.99),
        ("GREEN CHILI 1LB", 2.49),
        ("RED CHILI 1LB", 2.99),
        ("CILANTRO DHANIA BUNCH", 0.99),
        ("CURRY LEAF PACK", 1.49),
        ("EGGS 60CT", 8.12),
        ("YOGURT 32OZ", 4.49),
        ("WHEAT FLOUR 20LB", 12.99),
        ("TURMERIC POWDER 14OZ", 5.49),
        ("CORIANDER POWDER 14OZ", 4.99),
        ("CUMIN SEED 7OZ", 3.79),
        ("TOOR DAL 4LB", 7.99),
        ("CHANA DAL 4LB", 6.99),
        ("TOMATO 5LB", 5.49),
        ("ONION 10LB", 6.99),
        ("GINGER 1LB", 3.49),
        ("GARLIC 1LB", 2.99),
        ("MANGO PICKLE 1KG", 6.49),
        ("COCONUT OIL 1L", 9.99),
        ("PANEER 14OZ", 4.99),
        ("WHOLE MILK 1GAL", 3.99),
        ("MUTTON MASALA 100G", 2.49),
    ]
    subtotal = round(sum(price for _, price in items), 2)
    discount = 5.00
    tax = 2.35
    total = round(subtotal - discount + tax, 2)
    lines = [
        "OM TEST WHOLESALE MARKET",
        "12345 Test Market Road, Dallas TX-75001",
        "Description Price Qty",
        "Effective From: 07/01/2026 - 07/31/2026",
        "Order by email: orders@omtestmarket.com",
        "Pricing and availability subject to change",
        *[f"{name} {price:.2f}" for name, price in items],
        f"DISCOUNT PROMO -{discount:.2f}",
        f"TAX {tax:.2f}",
        f"TOTAL {total:.2f}",
    ]
    return make_text_pdf(lines), items, discount, tax, total


def test_digital_pdf_summary_lines_are_not_items():
    pdf_bytes, expected_items, expected_discount, expected_tax, expected_total = generated_receipt_pdf()
    parsed = claude.try_parse_digital_price_list_pdf(pdf_bytes, "om-test-receipt.pdf")
    assert parsed is not None

    item_names = [item["name"] for item in parsed["items"]]
    assert len(item_names) == len(expected_items)
    assert "TAX" not in item_names
    assert "TOTAL" not in item_names
    assert all(not name.startswith("DISCOUNT") for name in item_names)

    assert parsed["discount"] == expected_discount
    assert parsed["total_savings"] == expected_discount
    assert parsed["tax"] == expected_tax
    assert parsed["total"] == expected_total
    assert parsed["parse_audit"]["accepted_without_ai"] is True


def test_scan_path_keeps_zero_token_parser_and_correct_totals():
    pdf_bytes, expected_items, expected_discount, expected_tax, expected_total = generated_receipt_pdf()
    claude.check_duplicate = lambda *args, **kwargs: None

    scanned = claude.scan_receipt_image(pdf_bytes, "om-test-receipt.pdf", guest_session_id="smoke-test")
    item_names = [item["name"] for item in scanned["items"]]

    assert len(item_names) == len(expected_items)
    assert "TAX" not in item_names
    assert "TOTAL" not in item_names
    assert scanned["discount"] == expected_discount
    assert scanned["total_savings"] == expected_discount
    assert scanned["tax"] == expected_tax
    assert scanned["total"] == expected_total
    assert scanned["_token_usage"]["input_tokens"] == 0
    assert scanned["_token_usage"]["output_tokens"] == 0
    assert scanned["_token_usage"]["optimized"] is True


if __name__ == "__main__":
    test_digital_pdf_summary_lines_are_not_items()
    test_scan_path_keeps_zero_token_parser_and_correct_totals()
    print("Digital PDF parser regression tests passed.")
