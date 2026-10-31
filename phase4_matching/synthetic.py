"""Generate a synthetic dataset of purchase orders and invoices with known answers.

Real documents with labelled answers are hard to get, so we generate them. Because
we create every document, we know the truth: which invoice belongs to which PO and
which discrepancies were injected. That lets us MEASURE matching (Phase 4) and
verification (Phase 5) instead of assuming they work.

Difficulties built in:
  - some invoices omit the PO reference
  - supplier names and item descriptions are written differently on the invoice
  - line items appear in a different order
  - "distractor" POs from the same supplier and buyer that must NOT be matched
  - orphan invoices with no PO at all
  - injected discrepancies: quantity change, price change, extra item, arithmetic error

Usage:
    python -m phase4_matching.synthetic          # writes data/synthetic/dataset.json
"""

import json
import random
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

from phase3_extraction.schemas import ExtractedDocument, LineItem

OUT = Path(__file__).resolve().parent.parent / "data" / "synthetic" / "dataset.json"
TAX_RATE = Decimal("0.20")

# Each name has variants a real invoice might use.
SUPPLIERS = {
    "Nordline Industrial Supplies": ["Nordline Industrial Supplies Ltd", "NORDLINE IND. SUPPLIES"],
    "Kestrel Office Solutions": ["Kestrel Office Solutions Inc.", "Kestrel Office"],
    "Sahara Electrical Trading": ["Sahara Electrical Trading SARL", "SAHARA ELECTRICAL"],
    "Blueport Logistics Equipment": ["Blueport Logistics Equipment GmbH", "Blueport Logistics"],
}
BUYERS = ["Atlas Manufacturing SARL", "Riverside Foods Ltd", "Orion Medical Center", "Cedar Construction Co."]

# (description, variant used on invoices, typical unit price)
CATALOG = [
    ("Hydraulic pump HP-200", "HP-200 Hydraulic Pump", 1250),
    ("Steel bolts M8", "M8 steel bolt", Decimal("0.40")),
    ("Safety gloves (box)", "Box of safety gloves", 15),
    ("Industrial LED floodlight 100W", "100W LED flood light, industrial", 89),
    ("Copper cable 2.5mm (100m roll)", "2.5mm copper cable roll 100m", 64),
    ("Office chair ergonomic", "Ergonomic office chair", 210),
    ("A4 printer paper (500 sheets)", "Paper A4 ream 500", Decimal("4.50")),
    ("Pallet jack 2.5t", "2.5 ton pallet truck", 380),
    ("Laptop docking station USB-C", "USB-C docking station for laptops", 145),
    ("Circuit breaker 32A", "32A breaker", 22),
    ("Safety helmet (white)", "White hard hat", 18),
    ("Stretch wrap film 500mm", "500mm pallet stretch film", 12),
]


def _totals(items: list[LineItem]) -> dict:
    subtotal = sum((i.total for i in items), Decimal(0))
    tax = (subtotal * TAX_RATE).quantize(Decimal("0.01"))
    return {"subtotal": subtotal, "tax": tax, "total": subtotal + tax}


def _item(rng: random.Random, entry, variant: bool = False, qty: int | None = None) -> LineItem:
    description, alt, price = entry
    quantity = Decimal(qty if qty is not None else rng.choice([1, 2, 3, 5, 10, 20, 50, 100, 500]))
    price = Decimal(str(price))
    return LineItem(description=alt if variant else description, quantity=quantity,
                    unit_price=price, total=quantity * price)


def generate(n_transactions: int = 150, seed: int = 7) -> dict:
    rng = random.Random(seed)
    documents: dict[str, dict] = {}
    links: list[list[str]] = []  # [invoice_id, po_id]
    issues: dict[str, list[dict]] = {}  # invoice_id -> injected discrepancies

    def add(doc_id: str, doc: ExtractedDocument) -> None:
        documents[doc_id] = json.loads(doc.model_dump_json())

    for t in range(n_transactions):
        supplier = rng.choice(list(SUPPLIERS))
        buyer = rng.choice(BUYERS)
        po_date = date(2026, 1, 1) + timedelta(days=rng.randint(0, 270))
        entries = rng.sample(CATALOG, rng.randint(2, 4))
        po_items = [_item(rng, e) for e in entries]
        po_id, inv_id = f"PO-2026-{1000 + t}", f"INV-2026-{5000 + t}"

        add(po_id, ExtractedDocument(
            doc_type="purchase_order", number=po_id, issue_date=po_date, buyer=buyer,
            supplier=supplier, currency="USD", line_items=po_items, **_totals(po_items),
        ))

        # A second, unrelated PO between the same parties: a trap for the matcher.
        if rng.random() < 0.25:
            other = rng.sample([e for e in CATALOG if e not in entries], 2)
            other_items = [_item(rng, e) for e in other]
            add(f"PO-2026-{3000 + t}", ExtractedDocument(
                doc_type="purchase_order", number=f"PO-2026-{3000 + t}",
                issue_date=po_date + timedelta(days=rng.randint(-20, 20)), buyer=buyer,
                supplier=supplier, currency="USD", line_items=other_items, **_totals(other_items),
            ))

        # The invoice: same items, possibly reworded and reordered.
        inv_items = [
            _item(rng, e, variant=rng.random() < 0.5, qty=int(i.quantity))
            for e, i in zip(entries, po_items)
        ]
        found = []
        roll = rng.random()
        if roll < 0.15:
            k = rng.randrange(len(inv_items))
            new_qty = inv_items[k].quantity + rng.choice([1, 2, 5])
            inv_items[k] = inv_items[k].model_copy(update={
                "quantity": new_qty, "total": new_qty * inv_items[k].unit_price})
            found.append({"type": "quantity_mismatch", "item": entries[k][0]})
        elif roll < 0.25:
            k = rng.randrange(len(inv_items))
            new_price = (inv_items[k].unit_price * Decimal("1.10")).quantize(Decimal("0.01"))
            inv_items[k] = inv_items[k].model_copy(update={
                "unit_price": new_price, "total": inv_items[k].quantity * new_price})
            found.append({"type": "price_mismatch", "item": entries[k][0]})
        elif roll < 0.32:
            extra = rng.choice([e for e in CATALOG if e not in entries])
            inv_items.append(_item(rng, extra))
            found.append({"type": "unexpected_item", "item": extra[0]})
        rng.shuffle(inv_items)

        totals = _totals(inv_items)
        if 0.32 <= roll < 0.38:
            totals["total"] += Decimal("100.00")  # total does not add up
            found.append({"type": "arithmetic_error", "item": None})

        add(inv_id, ExtractedDocument(
            doc_type="invoice", number=inv_id,
            references=[po_id] if rng.random() < 0.7 else [],
            issue_date=po_date + timedelta(days=rng.randint(5, 40)), buyer=buyer,
            supplier=rng.choice([supplier, *SUPPLIERS[supplier]]), currency="USD",
            line_items=inv_items, **totals,
        ))
        links.append([inv_id, po_id])
        issues[inv_id] = found

    # Orphan invoices: no PO exists for them.
    for t in range(n_transactions // 10):
        supplier = rng.choice(list(SUPPLIERS))
        items = [_item(rng, e) for e in rng.sample(CATALOG, 2)]
        inv_id = f"INV-2026-{8000 + t}"
        add(inv_id, ExtractedDocument(
            doc_type="invoice", number=inv_id, issue_date=date(2026, 6, 1) + timedelta(days=t),
            buyer=rng.choice(BUYERS), supplier=supplier, currency="USD", line_items=items,
            **_totals(items),
        ))
        issues[inv_id] = []

    return {"documents": documents, "links": links, "issues": issues}


def load() -> dict:
    """Load the dataset, converting documents back into Pydantic objects."""
    raw = json.loads(OUT.read_text(encoding="utf-8"))
    raw["documents"] = {k: ExtractedDocument(**v) for k, v in raw["documents"].items()}
    return raw


def main() -> None:
    dataset = generate()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(dataset, indent=1), encoding="utf-8")
    docs = dataset["documents"].values()
    print(f"{len(dataset['documents'])} documents "
          f"({sum(d['doc_type'] == 'purchase_order' for d in docs)} POs, "
          f"{sum(d['doc_type'] == 'invoice' for d in docs)} invoices), "
          f"{len(dataset['links'])} true links, "
          f"{sum(len(v) for v in dataset['issues'].values())} injected issues -> {OUT}")


if __name__ == "__main__":
    main()
