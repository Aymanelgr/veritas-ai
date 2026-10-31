// Display helpers. The API sends money and quantities as strings (Decimal) to keep them exact.

export function money(value, currency = "USD") {
  if (value == null || value === "") return "—";
  try {
    return new Intl.NumberFormat("en-US", { style: "currency", currency }).format(Number(value));
  } catch {
    return `${Number(value).toFixed(2)} ${currency}`; // unknown currency code
  }
}

export const number = (value) => (value == null || value === "" ? "—" : Number(value).toLocaleString("en-US"));

export function relativeTime(iso) {
  const seconds = (Date.now() - new Date(iso).getTime()) / 1000;
  if (seconds < 60) return "just now";
  if (seconds < 3600) return `${Math.floor(seconds / 60)} min ago`;
  if (seconds < 86400) return `${Math.floor(seconds / 3600)} h ago`;
  return new Date(iso).toLocaleDateString();
}

export const docTypeLabel = (type) =>
  ({ purchase_order: "Purchase order", invoice: "Invoice", contract: "Contract", other: "Document" })[type] ??
  "Document";
