import type {Dashboard} from "./api";

// Compatibility labels for the retained Gulf publication, which predates the
// governed category/channel display-name fields. New publications always win;
// these values only prevent a retained demo authority from exposing native IDs.
const knownCategoryLabels: Record<string, string> = {
  "gulf-mco": "Motorcycle Oils",
  "gulf-pcmo": "Passenger Car Motor Oils",
  "gulf-deo": "Diesel & CV Engine Oils",
  "gulf-tractor": "Tractor & Farm Oils",
  "gulf-gear": "Gear Oils",
  "gulf-atf": "Transmission Fluids",
  "gulf-grease": "Greases",
  "gulf-coolant-brake": "Coolants & Brake Fluids",
  "gulf-hydraulic": "Hydraulic Oils",
  "gulf-compressor-turbine": "Compressor & Turbine Oils",
  "gulf-metalworking": "Metalworking Fluids",
  "gulf-industrial-gear": "Industrial Gear & Circulating",
  "gulf-adblue": "AdBlue & DEF",
  "gulf-ev-fluids": "EV Fluids",
  "gulf-battery": "Batteries",
  "gulf-car-care": "Car Care & Consumables"
};

const knownChannelLabels: Record<string, string> = {
  "bazaar-trade": "Bazaar Trade",
  "gulf-online": "Gulf Direct Online",
  "gulf-marketplace": "Marketplace"
};

function identifierTail(value: string) {
  return value.split(":").at(-1) ?? value;
}

function humanizeIdentifier(value: string) {
  return identifierTail(value)
    .split(/[-_]+/)
    .filter(Boolean)
    .map((part) => part.length <= 3
      ? part.toUpperCase()
      : `${part[0].toUpperCase()}${part.slice(1)}`)
    .join(" ");
}

function normalizedIdentifier(value: string) {
  return value.toLocaleLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "");
}

function usableLabel(candidate: string | null | undefined, id: string) {
  const tail = identifierTail(id);
  if (!candidate) return undefined;
  const normalized = normalizedIdentifier(candidate);
  return normalized !== normalizedIdentifier(id) && normalized !== normalizedIdentifier(tail)
    ? candidate
    : undefined;
}

export function storeName(
  dashboard: Dashboard | undefined,
  id: string,
  governed?: string | null
) {
  return usableLabel(governed, id) ||
    usableLabel(dashboard?.filters.stores.find((store) => store.storeId === id)?.name, id) ||
    humanizeIdentifier(id);
}

export function categoryName(
  dashboard: Dashboard | undefined,
  id: string | null | undefined,
  governed?: string | null
) {
  if (!id) return "Not available";
  return usableLabel(governed, id) ||
    usableLabel(dashboard?.filters.categories?.find((category) => category.categoryId === id)?.name, id) ||
    knownCategoryLabels[identifierTail(id)] ||
    humanizeIdentifier(id);
}

export function categoryNameFromLabel(value: string) {
  const normalized = normalizedIdentifier(value);
  if (knownCategoryLabels[normalized]) return knownCategoryLabels[normalized];
  const retainedId = Object.keys(knownCategoryLabels).find((id) =>
    value.toLocaleLowerCase() === `gulf - ${id.replace(/^gulf-/, "").replaceAll("-", " - ")}`
  );
  return retainedId ? knownCategoryLabels[retainedId] : value;
}

export function channelName(
  dashboard: Dashboard | undefined,
  id: string,
  governed?: string | null
) {
  return usableLabel(governed, id) ||
    usableLabel(dashboard?.filters.channels?.find((channel) => channel.channelId === id)?.name, id) ||
    knownChannelLabels[identifierTail(id)] ||
    humanizeIdentifier(id);
}

export function marketName(dashboard: Dashboard | undefined, id: string) {
  return usableLabel(
    dashboard?.filters.markets.find((market) => market.marketId === id)?.name,
    id
  ) || humanizeIdentifier(id);
}
