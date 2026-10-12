import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";

import ApplyPartner from "./ApplyPartner";

const { useSessionMock, signInMock, registerRestaurantMock, navigateMock } = vi.hoisted(() => ({
  useSessionMock: vi.fn(),
  signInMock: vi.fn(),
  registerRestaurantMock: vi.fn(),
  navigateMock: vi.fn(),
}));

vi.mock("@/features/auth/session-context", () => ({
  useSession: useSessionMock,
}));

// MapLibre needs WebGL, which jsdom doesn't have.
vi.mock("@/features/restaurant/RestaurantLocationMap", () => ({
  RestaurantLocationMap: () => <div data-testid="location-map" />,
}));

vi.mock("@/services/api/authApi", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/services/api/authApi")>();
  return { ...actual, registerRestaurant: registerRestaurantMock };
});

vi.mock("react-router-dom", async (importOriginal) => {
  const actual = await importOriginal<typeof import("react-router-dom")>();
  return { ...actual, useNavigate: () => navigateMock };
});

function fill(label: RegExp, value: string) {
  fireEvent.change(screen.getByLabelText(label), { target: { value } });
}

function fillValidForm() {
  fill(/^your name/i, "Ramesh Gupta");
  fill(/^email/i, "ramesh@swad.in");
  fill(/^password/i, "Chai@12345");
  fill(/^confirm password/i, "Chai@12345");
  fill(/^restaurant name/i, "Swad Bhojnalaya");
  fill(/^restaurant phone/i, "9387650002");
  fill(/^full address/i, "Near Bus Stand, Shahganj");
}

function renderPage() {
  useSessionMock.mockReturnValue({ status: "anonymous", signIn: signInMock });
  return render(
    <MemoryRouter>
      <ApplyPartner />
    </MemoryRouter>,
  );
}

describe("Apply as restaurant partner", () => {
  afterEach(() => {
    vi.clearAllMocks();
  });

  it("splits a pasted Google Maps coordinate pair and shows the map", () => {
    renderPage();
    expect(screen.queryByTestId("location-map")).not.toBeInTheDocument();

    fill(/^latitude/i, "26.0486, 82.6847");

    expect(screen.getByLabelText(/^latitude/i)).toHaveValue("26.0486");
    expect(screen.getByLabelText(/^longitude/i)).toHaveValue("82.6847");
    expect(screen.getByTestId("location-map")).toBeInTheDocument();
  });

  it("blocks submit when passwords don't match", () => {
    renderPage();
    fillValidForm();
    fill(/^confirm password/i, "Different@1");
    fill(/^latitude/i, "26.0486, 82.6847");

    fireEvent.click(screen.getByRole("button", { name: /submit application/i }));

    expect(screen.getByRole("alert")).toHaveTextContent(/passwords don't match/i);
    expect(registerRestaurantMock).not.toHaveBeenCalled();
  });

  it("submits the application, then signs in and opens the dashboard", async () => {
    registerRestaurantMock.mockResolvedValue({ user: { id: "u1" } });
    signInMock.mockResolvedValue({ role: "RESTAURANT_OWNER" });
    renderPage();
    fillValidForm();
    fill(/^latitude/i, "26.0486, 82.6847");

    fireEvent.click(screen.getByRole("button", { name: /submit application/i }));

    await waitFor(() => expect(navigateMock).toHaveBeenCalledWith("/dashboard", { replace: true }));
    expect(registerRestaurantMock).toHaveBeenCalledWith(
      expect.objectContaining({
        owner_name: "Ramesh Gupta",
        email: "ramesh@swad.in",
        owner_phone: null,
        restaurant_name: "Swad Bhojnalaya",
        latitude: 26.0486,
        longitude: 82.6847,
      }),
    );
    expect(registerRestaurantMock.mock.calls[0][0]).not.toHaveProperty("confirm_password");
    expect(signInMock).toHaveBeenCalledWith("ramesh@swad.in", "Chai@12345");
  });
});
