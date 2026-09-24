import { createContext, useContext, useState, type ReactNode } from "react";

import type { PlaceSearchResult } from "@/services/api/locationSearchApi";

// Maps & Location System Phase 9 — carries a selected search result back
// to whichever address form pushed the search screen, the same
// across-navigation pattern location-picker-context.tsx (Phase 6)
// already established for the map picker — kept as a separate context
// rather than reused, since a search result carries real address text
// (not just coordinates) and the two screens' consumers shouldn't have
// to guard against the other's shape.

type PickedPlaceContextValue = {
  pickedPlace: PlaceSearchResult | null;
  setPickedPlace: (place: PlaceSearchResult | null) => void;
};

const PickedPlaceContext = createContext<PickedPlaceContextValue | null>(null);

export function PickedPlaceProvider({ children }: { children: ReactNode }) {
  const [pickedPlace, setPickedPlace] = useState<PlaceSearchResult | null>(null);
  return (
    <PickedPlaceContext.Provider value={{ pickedPlace, setPickedPlace }}>
      {children}
    </PickedPlaceContext.Provider>
  );
}

export function usePickedPlace() {
  const context = useContext(PickedPlaceContext);
  if (!context) {
    throw new Error("usePickedPlace must be used within a PickedPlaceProvider");
  }
  return context;
}
