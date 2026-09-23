import { render, screen } from "@testing-library/react-native";

jest.mock("expo-router", () => ({
  Redirect: ({ href }: { href: string }) => {
    const { Text } = require("react-native");
    return <Text testID="redirect">redirect:{href}</Text>;
  },
  useRouter: () => ({ back: jest.fn(), push: jest.fn(), replace: jest.fn() }),
}));

const mockUseSession = jest.fn();
jest.mock("@/features/auth/session-context", () => ({
  useSession: () => mockUseSession(),
}));

jest.mock("@/services/api/profileApi", () => ({
  updateProfile: jest.fn(),
}));

import ProfileScreen from "../profile";

describe("Protected route — profile screen", () => {
  it("redirects to /login instead of rendering profile content for an anonymous (no-user) session", () => {
    mockUseSession.mockReturnValue({ user: null, accessToken: null, signOut: jest.fn(), refresh: jest.fn() });
    render(<ProfileScreen />);
    expect(screen.getByTestId("redirect")).toHaveTextContent("redirect:/login");
    expect(screen.queryByText(/save/i)).toBeNull();
  });

  it("renders the profile content, not a redirect, for a logged-in user", () => {
    mockUseSession.mockReturnValue({
      user: { id: "u1", name: "Ravi", email: "ravi@example.com" },
      accessToken: "test-token",
      signOut: jest.fn(),
      refresh: jest.fn(),
    });
    render(<ProfileScreen />);
    expect(screen.queryByTestId("redirect")).toBeNull();
  });
});
