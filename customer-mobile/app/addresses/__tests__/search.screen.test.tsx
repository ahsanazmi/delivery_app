import { fireEvent, render, screen, waitFor } from "@testing-library/react-native";

jest.mock("expo-router", () => ({
  Redirect: ({ href }: { href: string }) => {
    const { Text } = require("react-native");
    return <Text testID="redirect">redirect:{href}</Text>;
  },
  useRouter: () => ({ back: mockBack, push: jest.fn(), replace: jest.fn() }),
}));

const mockBack = jest.fn();
const mockUseSession = jest.fn();
jest.mock("@/features/auth/session-context", () => ({
  useSession: () => mockUseSession(),
}));

const mockSetPickedPlace = jest.fn();
jest.mock("@/features/addresses/place-search-context", () => ({
  usePickedPlace: () => ({ pickedPlace: null, setPickedPlace: mockSetPickedPlace }),
}));

const mockSearchPlaces = jest.fn();
jest.mock("@/services/api/locationSearchApi", () => ({
  searchPlaces: (...args: unknown[]) => mockSearchPlaces(...args),
}));

import AddressSearchScreen from "../search";

function basePlace(overrides: Record<string, unknown> = {}) {
  return {
    label: "Azamgarh, Uttar Pradesh", address_line: null, city: "Azamgarh", district: null,
    state: "Uttar Pradesh", postal_code: "276001", country: "India",
    latitude: 26.0654351, longitude: 83.184439,
    formatted_address: "Azamgarh, Uttar Pradesh, India", place_id: "N:765060153",
    ...overrides,
  };
}

describe("Address search screen — Forward Geocoding / Address Search (Phase 9)", () => {
  beforeEach(() => {
    jest.clearAllMocks();
    jest.useFakeTimers();
  });

  afterEach(() => {
    jest.useRealTimers();
  });

  it("Protected route: redirects to /login instead of rendering search for an anonymous session", () => {
    mockUseSession.mockReturnValue({ user: null, accessToken: null });
    render(<AddressSearchScreen />);
    expect(screen.getByTestId("redirect")).toHaveTextContent("redirect:/login");
  });

  it("does not call the API for a query under the minimum length", async () => {
    mockUseSession.mockReturnValue({ user: { id: "u1" }, accessToken: "test-token" });
    render(<AddressSearchScreen />);

    fireEvent.changeText(screen.getByPlaceholderText(/Search for a home/), "A");
    jest.advanceTimersByTime(1000);

    expect(mockSearchPlaces).not.toHaveBeenCalled();
    expect(screen.getByText(/Keep typing to search/)).toBeTruthy();
  });

  it("debounces typing and searches once the customer pauses", async () => {
    mockUseSession.mockReturnValue({ user: { id: "u1" }, accessToken: "test-token" });
    mockSearchPlaces.mockResolvedValue({ results: [basePlace()] });

    render(<AddressSearchScreen />);
    fireEvent.changeText(screen.getByPlaceholderText(/Search for a home/), "Azamgarh");

    // Well before the debounce window — must not have searched yet.
    jest.advanceTimersByTime(100);
    expect(mockSearchPlaces).not.toHaveBeenCalled();

    jest.advanceTimersByTime(400);
    await waitFor(() => expect(mockSearchPlaces).toHaveBeenCalledWith("test-token", "Azamgarh"));
    expect(mockSearchPlaces).toHaveBeenCalledTimes(1);
  });

  it("renders each suggestion's label and formatted address", async () => {
    mockUseSession.mockReturnValue({ user: { id: "u1" }, accessToken: "test-token" });
    mockSearchPlaces.mockResolvedValue({ results: [basePlace()] });

    render(<AddressSearchScreen />);
    fireEvent.changeText(screen.getByPlaceholderText(/Search for a home/), "Azamgarh");
    jest.advanceTimersByTime(400);

    await waitFor(() => expect(screen.getByText("Azamgarh, Uttar Pradesh")).toBeTruthy());
    expect(screen.getByText("Azamgarh, Uttar Pradesh, India")).toBeTruthy();
  });

  it("selecting a suggestion stores it in the picked-place context and navigates back", async () => {
    mockUseSession.mockReturnValue({ user: { id: "u1" }, accessToken: "test-token" });
    const place = basePlace();
    mockSearchPlaces.mockResolvedValue({ results: [place] });

    render(<AddressSearchScreen />);
    fireEvent.changeText(screen.getByPlaceholderText(/Search for a home/), "Azamgarh");
    jest.advanceTimersByTime(400);

    await waitFor(() => expect(screen.getByText("Azamgarh, Uttar Pradesh")).toBeTruthy());
    fireEvent.press(screen.getByText("Azamgarh, Uttar Pradesh"));

    expect(mockSetPickedPlace).toHaveBeenCalledWith(place);
    expect(mockBack).toHaveBeenCalled();
  });

  it("shows the backend's own error message, not a generic crash, when search fails", async () => {
    mockUseSession.mockReturnValue({ user: { id: "u1" }, accessToken: "test-token" });
    const { ApiError } = jest.requireActual("@/services/api/apiClient");
    mockSearchPlaces.mockRejectedValue(new ApiError("Address search is temporarily unavailable.", 503));

    render(<AddressSearchScreen />);
    fireEvent.changeText(screen.getByPlaceholderText(/Search for a home/), "Azamgarh");
    jest.advanceTimersByTime(400);

    await waitFor(() => expect(screen.getByText("Address search is temporarily unavailable.")).toBeTruthy());
  });

  it("shows a no-results message, not a blank screen, when nothing matches", async () => {
    mockUseSession.mockReturnValue({ user: { id: "u1" }, accessToken: "test-token" });
    mockSearchPlaces.mockResolvedValue({ results: [] });

    render(<AddressSearchScreen />);
    fireEvent.changeText(screen.getByPlaceholderText(/Search for a home/), "Nonexistentplace");
    jest.advanceTimersByTime(400);

    await waitFor(() => expect(screen.getByText(/No places found/)).toBeTruthy());
  });
});
