const LABELS = {
  insufficient_evidence: "Insufficient evidence",
  purchase_order: "Purchase order",
  not_invoiced: "Not invoiced",
  approved: "Confirmed",
  rejected: "Dismissed",
  resolved: "Resolved",
  superseded: "Superseded",
};

// A small coloured pill; the colour comes from the value (e.g. "critical", "processed").
export default function Badge({ value, label }) {
  if (!value) return null;
  const text = label ?? LABELS[value] ?? value.charAt(0).toUpperCase() + value.slice(1).replaceAll("_", " ");
  return <span className={`badge badge-${value}`}>{text}</span>;
}
