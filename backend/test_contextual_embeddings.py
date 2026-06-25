import sys
import types


supabase_module = types.ModuleType("supabase")
supabase_module.Client = object
supabase_module.create_client = lambda *args, **kwargs: None
sys.modules["supabase"] = supabase_module

dotenv = types.ModuleType("dotenv")
dotenv.load_dotenv = lambda *args, **kwargs: None
sys.modules["dotenv"] = dotenv

anthropic = types.ModuleType("anthropic")
anthropic.Anthropic = lambda api_key=None: None
sys.modules["anthropic"] = anthropic

from app.services import database


def test_receipt_item_embedding_text_is_contextual():
    text = database._receipt_item_embedding_text({
        "item_name_original": "CILANTRO",
        "item_name_normalized": "cilantro",
        "code": "123",
        "product_size": None,
        "store": "India Mart",
        "purchase_date": "2026-05-23",
        "quantity": 3,
        "unit": "each",
        "unit_price": 0.59,
        "line_price": 1.77,
        "explicit_quantity": True,
        "metadata": {"category": "produce"},
    })

    assert "Item: CILANTRO" in text
    assert "Store: India Mart" in text
    assert "Quantity: 3 each" in text
    assert "Unit price: $0.59" in text
    assert "Line total: $1.77" in text
    assert "Category: produce" in text
    assert "typo-tolerant item search" in text


if __name__ == "__main__":
    test_receipt_item_embedding_text_is_contextual()
    print("Contextual embedding tests passed.")
