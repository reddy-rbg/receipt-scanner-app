import io
import sys
import types


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

from app.services.claude import auto_crop_receipt_region, optimize_scan_image_for_claude, split_long_receipt_segments


def make_small_receipt_photo() -> bytes:
    from PIL import Image, ImageDraw

    image = Image.new("RGB", (1600, 1200), (22, 26, 30))
    draw = ImageDraw.Draw(image)

    # Simulate shelves/reflections that should not dominate the crop.
    draw.rectangle((30, 40, 240, 180), fill=(80, 82, 86))
    draw.rectangle((1320, 60, 1540, 240), fill=(65, 70, 74))

    # Small white receipt far away in the camera frame.
    receipt_box = (640, 340, 940, 1020)
    draw.rectangle(receipt_box, fill=(244, 240, 218))
    for y in range(390, 920, 34):
        draw.line((675, y, 900, y), fill=(70, 70, 70), width=2)
    draw.rectangle((665, 940, 915, 982), fill=(238, 238, 238))

    output = io.BytesIO()
    image.save(output, format="JPEG", quality=90)
    return output.getvalue()


def test_auto_crop_receipt_region_enlarges_small_receipt():
    image_bytes = make_small_receipt_photo()
    cropped, info = auto_crop_receipt_region(image_bytes)

    assert info["auto_cropped_receipt"] is True
    assert info["crop_ratio"] < 0.45
    assert info["cropped_size"][0] < info["original_size"][0]
    assert info["cropped_size"][1] < info["original_size"][1]


def test_optimize_scan_image_reduces_estimated_vision_tokens():
    image_bytes = make_small_receipt_photo()
    optimized, media_type, info = optimize_scan_image_for_claude(image_bytes)

    assert media_type == "image/jpeg"
    assert optimized
    assert info["auto_cropped_receipt"] is True
    assert info["optimized_size"][0] <= 1800
    assert info["optimized_size"][1] <= 1800
    assert info["estimated_optimized_image_tokens"] < info["estimated_original_image_tokens"]
    assert info["estimated_image_tokens_saved"] > 0
    assert info["optimized_bytes"] == len(optimized)


def test_long_receipt_is_split_into_overlapping_readable_segments():
    from PIL import Image, ImageDraw

    image = Image.new("RGB", (900, 5000), (246, 242, 224))
    draw = ImageDraw.Draw(image)
    for y in range(80, 4920, 44):
        draw.line((70, y, 830, y), fill=(60, 60, 60), width=2)
    output = io.BytesIO()
    image.save(output, format="JPEG", quality=92)

    segments, info = split_long_receipt_segments(output.getvalue())

    assert info["long_receipt_tiled"] is True
    assert 2 <= info["segment_count"] <= 4
    assert len(segments) == info["segment_count"]
    boxes = info["segment_boxes"]
    assert boxes[0][1] == 0
    assert boxes[-1][3] == 5000
    assert all(boxes[index][3] > boxes[index + 1][1] for index in range(len(boxes) - 1))


if __name__ == "__main__":
    test_auto_crop_receipt_region_enlarges_small_receipt()
    test_optimize_scan_image_reduces_estimated_vision_tokens()
    test_long_receipt_is_split_into_overlapping_readable_segments()
    print("Receipt auto-crop regression test passed.")
