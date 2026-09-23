export function rupees(value: number | string): string {
  const amount = typeof value === "string" ? Number(value) : value;
  if (Number.isNaN(amount)) return "₹0.00";
  return `₹${amount.toFixed(2)}`;
}
