receipt = {
    "store": "Walmart",
    "date": "2026-05-04",
    "total": 12.96,
    "items": [
        {"name": "Whole Milk",  "price": 3.49},
        {"name": "White Bread", "price": 2.78},
        {"name": "Dozen Eggs",  "price": 4.29},
        {"name": "Butter",      "price": 2.40}
    ]
}

print("Store:", receipt["store"])
print("Total: $" + str(receipt["total"]))
print("Items bought:")

for item in receipt["items"]:
    print(" -", item["name"], "→ $" + str(item["price"]))