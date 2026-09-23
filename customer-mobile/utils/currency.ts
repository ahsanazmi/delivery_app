export function rupees(value: string | number) {
  return `₹${Number(value).toFixed(0)}`;
}

export function deliveryLabel(value: string | number) {
  const fee = Number(value);
  return fee === 0 ? 'Free delivery' : `${rupees(fee)} delivery`;
}
