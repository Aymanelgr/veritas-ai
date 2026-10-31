# Example documents for Veritas AI

Ten realistic scenarios to upload and test. Formats are mixed on purpose: digital PDFs,
Word files, text files, and **scanned** images/PDFs (slightly tilted and grainy, like a
real office scanner), so OCR is exercised too.

## How to use

1. Open the dashboard (http://localhost:5173) and make sure the worker is running.
2. Drag **all the files of one folder** onto the upload box (or several folders at once:
   the companies and numbers are all different, so they can't be mixed up).
3. Wait until both documents say *processed* (OCR takes ~15 s per scanned page).
4. Open the **invoice** and compare with the expected result below.

Tip: upload the purchase order first. The invoice is linked as soon as both exist, in either order.

## Scenarios

| Folder | Files | Situation | Veritas should show |
|---|---|---|---|
| `01_perfect_match` | `purchase_order.pdf`, `invoice_scan.png` | **Perfect match.** The invoice matches the order exactly. | Linked by the PO reference. All checks pass; nothing to review. |
| `02_quantity_mismatch` | `purchase_order.docx`, `invoice_scanned.pdf` | **Quantity changed without approval.** 3 microscopes were ordered; the invoice bills 4. Nothing explains the change. | CRITICAL: invoiced quantity of 'Microscope LX-400' does not match (3 vs 4), no approval found. |
| `03_approved_change` | `purchase_order.pdf`, `invoice.txt` | **Quantity changed, with documented approval.** 40 life jackets ordered, 50 invoiced, and the invoice notes the buyer approved it by email. | WARNING (not critical): the quantity difference is flagged but explained by the approval line. |
| `04_price_increase` | `purchase_order.pdf`, `invoice_scan.png` | **Unit price increased.** LED panels ordered at $28.00 each are invoiced at $31.50. | CRITICAL: invoiced unit price of 'LED panel 60x60' does not match the order. |
| `05_unexpected_item` | `purchase_order.docx`, `invoice.pdf` | **Item that was never ordered.** The invoice adds a hedge trimmer that is not on the purchase order. | CRITICAL: 'Hedge trimmer HT-20' was not ordered. |
| `06_arithmetic_error` | `purchase_order.pdf`, `invoice_scan.png` | **Total that does not add up.** Every line is right, but the invoice's grand total is $100 too high. | CRITICAL: subtotal plus tax does not equal the total. |
| `07_no_po_reference` | `purchase_order.pdf`, `invoice_scan.png` | **Invoice without a PO number.** The invoice never mentions the PO number, writes the supplier name differently and rewords every item. | Linked anyway by fuzzy matching (supplier, buyer, items, dates). All checks pass. |
| `08_orphan_invoice` | `invoice.docx` | **Invoice with no purchase order.** A cleaning company sends an invoice, but no matching order exists. | WARNING: no matching purchase order was found. The invoice's own arithmetic is correct. |
| `09_partial_invoice` | `purchase_order.pdf`, `invoice_scanned.pdf` | **Partial invoice.** Three items were ordered; this invoice bills only two (the third ships later). | INFO only: 'Anchor bolt kit' was ordered but is not on this invoice (it may be invoiced separately). |
| `10_late_delivery` | `purchase_order.txt`, `invoice_scan.png` | **Late delivery.** The order required delivery by September 15; the goods shipped on September 22. | WARNING: goods were not shipped by the required delivery date. |
| `11_currency_not_stated` | `purchase_order.pdf`, `invoice.pdf` | **Currency not stated.** Both documents show prices with a '$' sign but never say which dollar. | WARNING: prices and totals NOT compared because the currency is unknown ('$' alone is not assumed to be US dollars). Quantities are still checked. |
| `12_currency_mismatch` | `purchase_order.pdf`, `invoice.pdf` | **Different currencies.** The order is in euros; the invoice for the same goods is in Moroccan dirhams. | CRITICAL: the invoice currency (MAD) differs from the order (EUR). Prices and totals are NOT compared, because there is no currency conversion. |
| `13_french_dirhams` | `bon_de_commande.pdf`, `facture_scan.png` | **French documents in dirhams.** A French purchase order and a SCANNED French invoice: '1 234,56 DH' numbers, day-first dates (18/09/2026), accents. The invoice bills 50 reams of paper instead of 40. | CRITICAL: quantity of 'Ramette papier A4' differs (40 ordered, 50 invoiced), with the money impact in MAD. Amounts read correctly despite the French number format. |
| `14_arabic` | `purchase_order_arabic.pdf`, `invoice_arabic.pdf` | **Arabic documents.** An Arabic purchase order and invoice (right-to-left text, MAD). They match exactly. | Linked by the order reference; no problems. (Arabic support is EXPERIMENTAL: see the README's language section for what was evaluated.) |

## Things to try on the way

- **Ctrl+K** and type a company name or number to jump to a document.
- On an invoice page, hover a problem: its row lights up in *Order vs invoice*.
- Click a scanned page to zoom; click an extracted value to see the line it came from.
- Ask: *"How many life jackets were ordered and how many were invoiced?"* or
  *"Which invoices are from Summit Electrical Wholesale?"*
- In *Reviews*, use **J/K** to move, **C** to confirm, **D** to dismiss, and **Undo** in the toast.

To regenerate these files: `python scripts/make_examples.py`.
To check them automatically (no upload needed): `python scripts/check_examples.py`.
