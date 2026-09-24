import { fireEvent, render, screen } from "@testing-library/react-native";
import { Pressable, Text } from "react-native";

import { PickedPlaceProvider, usePickedPlace } from "./place-search-context";

// Maps & Location System Phase 9 — same set/read/clear/throws-outside-
// provider guarantees as location-picker-context.test.tsx (Phase 6),
// proven independently since this is a genuinely separate context.

function Probe() {
  const { pickedPlace, setPickedPlace } = usePickedPlace();
  return (
    <>
      <Text testID="value">{pickedPlace ? pickedPlace.label : "none"}</Text>
      <Pressable
        testID="set"
        onPress={() =>
          setPickedPlace({
            label: "Azamgarh, Uttar Pradesh", address_line: null, city: "Azamgarh", district: null,
            state: "Uttar Pradesh", postal_code: "276001", country: "India",
            latitude: 26.0654351, longitude: 83.184439,
            formatted_address: "Azamgarh, Uttar Pradesh", place_id: "N:765060153",
          })
        }
      />
      <Pressable testID="clear" onPress={() => setPickedPlace(null)} />
    </>
  );
}

describe("PickedPlaceProvider / usePickedPlace", () => {
  it("starts with no picked place", () => {
    render(
      <PickedPlaceProvider>
        <Probe />
      </PickedPlaceProvider>,
    );
    expect(screen.getByTestId("value")).toHaveTextContent("none");
  });

  it("a set place is readable, then clearing it removes it again", () => {
    render(
      <PickedPlaceProvider>
        <Probe />
      </PickedPlaceProvider>,
    );

    fireEvent.press(screen.getByTestId("set"));
    expect(screen.getByTestId("value")).toHaveTextContent("Azamgarh, Uttar Pradesh");

    fireEvent.press(screen.getByTestId("clear"));
    expect(screen.getByTestId("value")).toHaveTextContent("none");
  });

  it("throws a clear error when used outside the provider, rather than silently returning undefined", () => {
    const consoleError = jest.spyOn(console, "error").mockImplementation(() => {});
    expect(() => render(<Probe />)).toThrow("usePickedPlace must be used within a PickedPlaceProvider");
    consoleError.mockRestore();
  });
});
