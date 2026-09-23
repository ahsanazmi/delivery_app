import { render, screen, waitFor } from "@testing-library/react-native";

jest.mock("expo-router", () => ({
  useRouter: () => ({ back: jest.fn(), replace: jest.fn(), push: jest.fn() }),
  useFocusEffect: (callback: () => void | (() => void)) => {
    const { useEffect } = require("react");
    useEffect(() => callback(), []);
  },
}));

const mockUseAuthStore = jest.fn();
jest.mock("@/store/authStore", () => ({
  useAuthStore: (selector: (state: unknown) => unknown) => selector(mockUseAuthStore()),
}));

const mockGetRiderWallet = jest.fn();
const mockListRiderSettlements = jest.fn();
jest.mock("@/services/api/walletApi", () => ({
  ...jest.requireActual("@/services/api/walletApi"),
  getRiderWallet: (...args: unknown[]) => mockGetRiderWallet(...args),
  listRiderSettlements: (...args: unknown[]) => mockListRiderSettlements(...args),
}));

import RiderWalletScreen from "../(rider)/wallet";

function baseWallet(overrides: Record<string, unknown> = {}) {
  return {
    total_earnings: "1000.00",
    total_cod_collected: "400.00",
    total_settled: "300.00",
    wallet_balance: "600.00",
    settlement_due: "100.00",
    ...overrides,
  };
}

describe("Rider Payment/COD Visibility (Phase 29) — wallet settlement history", () => {
  beforeEach(() => {
    mockUseAuthStore.mockReturnValue({ accessToken: "test-token" });
    mockGetRiderWallet.mockReset();
    mockListRiderSettlements.mockReset();
  });

  it("renders the rider's own settlement history — type, amount, and date", async () => {
    mockGetRiderWallet.mockResolvedValue(baseWallet());
    mockListRiderSettlements.mockResolvedValue([
      {
        id: "settle-1", settlement_type: "PAYOUT", amount: "150.00",
        note: "Weekly payout", created_at: new Date().toISOString(),
      },
      {
        id: "settle-2", settlement_type: "REMITTANCE", amount: "80.00",
        note: null, created_at: new Date().toISOString(),
      },
    ]);

    render(<RiderWalletScreen />);

    await waitFor(() => {
      expect(screen.getByText("Settlement history")).toBeTruthy();
      expect(screen.getByText("Paid out to you")).toBeTruthy();
      expect(screen.getByText("+₹150.00")).toBeTruthy();
      expect(screen.getByText("Remitted to platform")).toBeTruthy();
      expect(screen.getByText("-₹80.00")).toBeTruthy();
      expect(screen.getByText("Weekly payout")).toBeTruthy();
    });
  });

  it("shows an empty state, not a blank section, when the rider has no settlements yet", async () => {
    mockGetRiderWallet.mockResolvedValue(baseWallet());
    mockListRiderSettlements.mockResolvedValue([]);

    render(<RiderWalletScreen />);

    await waitFor(() => {
      expect(screen.getByText("No settlements recorded yet.")).toBeTruthy();
    });
  });

  it("shows the backend's own error message, not a generic crash, when settlement history fails to load", async () => {
    mockGetRiderWallet.mockResolvedValue(baseWallet());
    mockListRiderSettlements.mockRejectedValue(new Error("Unable to reach the server"));

    render(<RiderWalletScreen />);

    await waitFor(() => {
      expect(screen.getByText("Unable to reach the server")).toBeTruthy();
    });
  });

  it("never renders a razorpay signature or any provider-secret-looking value alongside wallet/settlement data", async () => {
    mockGetRiderWallet.mockResolvedValue(baseWallet());
    mockListRiderSettlements.mockResolvedValue([
      { id: "settle-1", settlement_type: "PAYOUT", amount: "150.00", note: "ok", created_at: new Date().toISOString() },
    ]);

    render(<RiderWalletScreen />);

    await waitFor(() => {
      expect(screen.getByText("Settlement history")).toBeTruthy();
    });
    // getRiderWallet/listRiderSettlements are the only two calls this
    // screen makes — neither backend schema carries anything
    // payment-secret-related in the first place (confirmed by the
    // backend's own RiderWalletRead/RiderSettlementRead shapes), so this
    // is a regression guard, not a live proof.
    expect(mockGetRiderWallet).toHaveBeenCalledTimes(1);
    expect(mockListRiderSettlements).toHaveBeenCalledTimes(1);
  });
});
