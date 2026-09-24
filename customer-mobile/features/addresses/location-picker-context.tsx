import { createContext, useContext, useState, type ReactNode } from "react";

// Maps & Location System Phase 6 — carries a coordinate picked on the
// map screen back to whichever address form pushed it, across a real
// screen navigation (Expo Router has no built-in "return a result"
// mechanism the way startActivityForResult does). The map-picker screen
// writes here right before calling router.back(); the form reads it via
// useFocusEffect on return and clears it immediately after consuming it,
// so a stale pick can never leak into a later, unrelated add/edit.

export type PickedLocation = {
  latitude: number;
  longitude: number;
};

type LocationPickerContextValue = {
  pickedLocation: PickedLocation | null;
  setPickedLocation: (location: PickedLocation | null) => void;
};

const LocationPickerContext = createContext<LocationPickerContextValue | null>(null);

export function LocationPickerProvider({ children }: { children: ReactNode }) {
  const [pickedLocation, setPickedLocation] = useState<PickedLocation | null>(null);
  return (
    <LocationPickerContext.Provider value={{ pickedLocation, setPickedLocation }}>
      {children}
    </LocationPickerContext.Provider>
  );
}

export function useLocationPicker() {
  const context = useContext(LocationPickerContext);
  if (!context) {
    throw new Error("useLocationPicker must be used within a LocationPickerProvider");
  }
  return context;
}
