// Display helpers. The API sends money and quantities as strings (Decimal) to keep them exact.

// Display locale per document language: French uses "1 234,56", Moroccan Arabic keeps
// Western digits (as on most Moroccan invoices) with an Arabic layout.
const LOCALES = { en: "en-US", fr: "fr-FR", ar: "ar-MA" };
export const localeFor = (language) => LOCALES[language] ?? "en-US";

// Never invent a currency: an unknown one is shown as a plain amount with a visible warning,
// not silently as dollars.
export function money(value, currency, language) {
  if (value == null || value === "") return "—";
  const amount = Number(value);
  const locale = localeFor(language);
  if (!currency) {
    return `${amount.toLocaleString(locale, { minimumFractionDigits: 2, maximumFractionDigits: 4 })} (currency unknown)`;
  }
  try {
    return new Intl.NumberFormat(locale, { style: "currency", currency, numberingSystem: "latn" }).format(amount);
  } catch {
    return `${amount.toLocaleString(locale, { minimumFractionDigits: 2 })} ${currency}`; // unrecognised code
  }
}

export const number = (value, language) =>
  value == null || value === "" ? "—" : Number(value).toLocaleString(localeFor(language), { maximumFractionDigits: 4 });

// Dates arrive as ISO "YYYY-MM-DD"; they are shown unambiguously (e.g. "5 Mar 2026"), never as 05/03.
export function date(iso, language) {
  if (!iso) return "—";
  const parsed = new Date(`${iso}T00:00:00`);
  if (Number.isNaN(parsed.getTime())) return iso;
  return parsed.toLocaleDateString(localeFor(language), { day: "numeric", month: "short", year: "numeric", numberingSystem: "latn" });
}

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

export const LANGUAGE_LABELS = { en: "English", fr: "French", ar: "Arabic" };

// Processing stages in order, as reported by the worker in document.stage.
export const STAGES = [
  ["reading", "Reading"], ["extracting", "Extracting"], ["indexing", "Indexing"],
  ["identifying", "Identifying"], ["matching", "Matching"], ["verifying", "Verifying"],
];
