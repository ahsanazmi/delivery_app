import { fireEvent, render, screen } from "@testing-library/react-native";
import { Pressable, Text } from "react-native";

import { LocationPickerProvider, useLocationPicker } from "./location-picker-context";

// Maps & Location System Phase 6 — the context that carries a picked
// coordinate from the map screen back into whichever address form
// pushed it. Proves: starts empty, a write is readable, and a
// consumed value is cleared so it can never leak into a later,
// unrelated add/edit (the same guarantee AddressForm's own
// useFocusEffect relies on).

function Probe() {
  const { pickedLocation, setPickedLocation } = useLocationPicker();
  return (
    <>
      <Text testID="value">{pickedLocation ? `${pickedLocation.latitude},${pickedLocation.longitude}` : "none"}</Text>
      <Pressable testID="set" onPress={() => setPickedLocation({ latitude: 26.068, longitude: 83.1836 })} />
      <Pressable testID="clear" onPress={() => setPickedLocation(null)} />
    </>
  );
}

describe("LocationPickerProvider / useLocationPicker", () => {
  it("starts with no picked location", () => {
    render(
      <LocationPickerProvider>
        <Probe />
      </LocationPickerProvider>,
    );
    expect(screen.getByTestId("value")).toHaveTextContent("none");
  });

  it("a set location is readable, then clearing it removes it again", () => {
    render(
      <LocationPickerProvider>
        <Probe />
      </LocationPickerProvider>,
    );

    fireEvent.press(screen.getByTestId("set"));
    expect(screen.getByTestId("value")).toHaveTextContent("26.068,83.1836");

    fireEvent.press(screen.getByTestId("clear"));
    expect(screen.getByTestId("value")).toHaveTextContent("none");
  });

  it("throws a clear error when used outside the provider, rather than silently returning undefined", () => {
    const consoleError = jest.spyOn(console, "error").mockImplementation(() => {});
    expect(() => render(<Probe />)).toThrow("useLocationPicker must be used within a LocationPickerProvider");
    consoleError.mockRestore();
  });
});
