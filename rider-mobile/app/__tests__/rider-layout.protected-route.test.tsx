import { render, screen } from "@testing-library/react-native";

jest.mock("expo-router", () => ({
  Redirect: ({ href }: { href: string }) => {
    const { Text } = require("react-native");
    return <Text testID="redirect">redirect:{href}</Text>;
  },
  Stack: Object.assign(
    ({ children }: { children?: unknown }) => {
      const { View } = require("react-native");
      return <View testID="rider-stack">{children}</View>;
    },
    { Screen: () => null },
  ),
}));

jest.mock("@/features/location/use-background-location", () => ({
  useBackgroundLocationTracking: jest.fn(),
}));
jest.mock("@/features/location/use-location-reporter", () => ({
  useLocationReporter: jest.fn(),
}));
jest.mock("@/features/location/use-tracking-eligibility", () => ({
  useTrackingEligibility: jest.fn(() => false),
}));

const mockUseAuthStore = jest.fn();
jest.mock("@/store/authStore", () => ({
  useAuthStore: (selector: (state: unknown) => unknown) => selector(mockUseAuthStore()),
}));

import RiderLayout from "../(rider)/_layout";

function setAuthState(state: { status: string; user: { role: string } | null; accessToken: string | null }) {
  mockUseAuthStore.mockReturnValue(state);
}

describe("Protected route + role routing — rider group layout", () => {
  it("redirects to /login instead of rendering rider screens for an unauthenticated session", () => {
    setAuthState({ status: "unauthenticated", user: null, accessToken: null });
    render(<RiderLayout />);
    expect(screen.getByTestId("redirect")).toHaveTextContent("redirect:/login");
  });

  it("redirects to /login for an authenticated non-rider account (role routing) — a customer/owner/admin token must never reach rider screens", () => {
    setAuthState({ status: "authenticated", user: { role: "CUSTOMER" }, accessToken: "test-token" });
    render(<RiderLayout />);
    expect(screen.getByTestId("redirect")).toHaveTextContent("redirect:/login");
  });

  it("renders the rider screen stack for an authenticated rider", () => {
    setAuthState({ status: "authenticated", user: { role: "RIDER" }, accessToken: "test-token" });
    render(<RiderLayout />);
    expect(screen.queryByTestId("redirect")).toBeNull();
    expect(screen.getByTestId("rider-stack")).toBeTruthy();
  });
});
