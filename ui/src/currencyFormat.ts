const unavailable = "Not available";

function trimCompactAmount(value: number, digits: number) {
  return value.toFixed(digits).replace(/\.0+$|(?<=\.[0-9])0+$/, "");
}

/**
 * Format monetary minor units using the compact notation used by the reference
 * dashboard. This is presentation only; it never performs currency conversion.
 */
export function formatMoneyMinor(
  value: number | null | undefined,
  currencyCode: string | null | undefined
) {
  if (value === null || value === undefined || !currencyCode) return unavailable;
  const major = value / 100;
  const absolute = Math.abs(major);
  const sign = major < 0 ? "−" : "";
  const symbol = new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: currencyCode,
    currencyDisplay: "narrowSymbol"
  }).formatToParts(0).find((part) => part.type === "currency")?.value ?? `${currencyCode} `;

  if (currencyCode === "INR") {
    if (absolute >= 1e7) return `${sign}${symbol}${trimCompactAmount(absolute / 1e7, 2)} Cr`;
    if (absolute >= 1e5) return `${sign}${symbol}${trimCompactAmount(absolute / 1e5, 2)}L`;
    return `${sign}${symbol}${absolute.toLocaleString("en-IN", {maximumFractionDigits: 2})}`;
  }
  if (absolute >= 1e9) return `${sign}${symbol}${trimCompactAmount(absolute / 1e9, 2)}B`;
  if (absolute >= 1e6) return `${sign}${symbol}${trimCompactAmount(absolute / 1e6, 2)}M`;
  if (absolute >= 1e3) return `${sign}${symbol}${trimCompactAmount(absolute / 1e3, 1)}K`;
  return `${sign}${symbol}${absolute.toLocaleString("en-US", {maximumFractionDigits: 2})}`;
}

/**
 * Format an aggregate business value. Unlike a unit price, an aggregate is
 * always expressed in the reference dashboard's compact scale, including
 * fractional lakh values below one lakh (for example, ₹0.86L).
 */
export function formatAggregateMoneyMinor(
  value: number | null | undefined,
  currencyCode: string | null | undefined
) {
  if (value === null || value === undefined || !currencyCode) return unavailable;
  const major = value / 100;
  const absolute = Math.abs(major);
  const sign = major < 0 ? "−" : "";
  const symbol = new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: currencyCode,
    currencyDisplay: "narrowSymbol"
  }).formatToParts(0).find((part) => part.type === "currency")?.value ?? `${currencyCode} `;

  if (absolute === 0) return `${symbol}0`;
  if (currencyCode === "INR") {
    if (absolute >= 1e7) return `${sign}${symbol}${trimCompactAmount(absolute / 1e7, 2)} Cr`;
    return `${sign}${symbol}${trimCompactAmount(absolute / 1e5, 2)}L`;
  }
  if (absolute >= 1e9) return `${sign}${symbol}${trimCompactAmount(absolute / 1e9, 2)}B`;
  if (absolute >= 1e6) return `${sign}${symbol}${trimCompactAmount(absolute / 1e6, 2)}M`;
  return `${sign}${symbol}${trimCompactAmount(absolute / 1e3, 2)}K`;
}
