import {
    createContext,
    PropsWithChildren,
    useCallback,
    useContext,
    useEffect,
    useMemo,
    useState,
} from "react";

import { useSession } from "@/features/auth/session-context";
import {
    addCartItem,
    applyCoupon as applyCouponRequest,
    clearCart as clearCartRequest,
    getCart,
    removeCartItem,
    removeCoupon as removeCouponRequest,
    updateCartItem,
    type CartItemLine,
    type CartResponse,
    type CartRestaurant,
} from "@/services/api/cartApi";
import { ApiError } from "@/services/api/apiClient";

type CartContextValue = {
  restaurant: CartRestaurant | null;
  items: CartItemLine[];
  itemCount: number;
  subtotal: number;
  deliveryFee: number;
  tax: number;
  discount: number;
  total: number;
  loading: boolean;
  error: string | null;
  removedItems: string[];
  couponCode: string | null;
  couponMessage: string | null;
  refresh: () => Promise<void>;
  addItem: (productId: string, quantity?: number) => Promise<void>;
  updateQuantity: (itemId: string, quantity: number) => Promise<void>;
  removeItem: (itemId: string) => Promise<void>;
  clearCart: () => Promise<void>;
  applyCoupon: (code: string) => Promise<void>;
  removeCoupon: () => Promise<void>;
  getQuantityForProduct: (productId: string) => number;
  decreaseProductQuantity: (productId: string) => Promise<void>;
};

const EMPTY_STATE = {
  restaurant: null as CartRestaurant | null,
  items: [] as CartItemLine[],
  subtotal: 0,
  deliveryFee: 0,
  tax: 0,
  discount: 0,
  total: 0,
  itemCount: 0,
  removedItems: [] as string[],
  couponCode: null as string | null,
  couponMessage: null as string | null,
};

function toState(cart: CartResponse) {
  return {
    restaurant: cart.restaurant,
    items: cart.items,
    subtotal: cart.subtotal,
    deliveryFee: cart.delivery_fee,
    tax: cart.tax,
    discount: cart.discount,
    total: cart.total,
    itemCount: cart.total_items,
    removedItems: cart.removed_items,
    couponCode: cart.coupon_code,
    couponMessage: cart.coupon_message,
  };
}

const CartContext = createContext<CartContextValue | null>(null);

export function CartProvider({ children }: PropsWithChildren) {
  const { accessToken } = useSession();
  const [state, setState] = useState(EMPTY_STATE);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    if (!accessToken) {
      setState(EMPTY_STATE);
      return;
    }
    setLoading(true);
    setError(null);
    try {
      const cart = await getCart(accessToken);
      setState(toState(cart));
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : "Unable to load your cart.");
    } finally {
      setLoading(false);
    }
  }, [accessToken]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const value = useMemo<CartContextValue>(() => {
    async function addItem(productId: string, quantity = 1) {
      if (!accessToken) {
        throw new Error("Please sign in to add items to your cart.");
      }
      const cart = await addCartItem(accessToken, productId, quantity);
      setState(toState(cart));
    }

    async function updateQuantity(itemId: string, quantity: number) {
      if (!accessToken) return;
      const cart =
        quantity > 0
          ? await updateCartItem(accessToken, itemId, quantity)
          : await removeCartItem(accessToken, itemId);
      setState(toState(cart));
    }

    async function removeItem(itemId: string) {
      if (!accessToken) return;
      const cart = await removeCartItem(accessToken, itemId);
      setState(toState(cart));
    }

    async function clearCart() {
      if (!accessToken) return;
      await clearCartRequest(accessToken);
      setState(EMPTY_STATE);
    }

    async function applyCoupon(code: string) {
      if (!accessToken) throw new Error("Please sign in to apply a coupon.");
      const cart = await applyCouponRequest(accessToken, code);
      setState(toState(cart));
    }

    async function removeCoupon() {
      if (!accessToken) return;
      const cart = await removeCouponRequest(accessToken);
      setState(toState(cart));
    }

    function getQuantityForProduct(productId: string) {
      return state.items.find((item) => item.product_id === productId)?.quantity ?? 0;
    }

    async function decreaseProductQuantity(productId: string) {
      const item = state.items.find((entry) => entry.product_id === productId);
      if (!item) return;
      await updateQuantity(item.id, item.quantity - 1);
    }

    return {
      ...state,
      loading,
      error,
      refresh,
      addItem,
      updateQuantity,
      removeItem,
      clearCart,
      applyCoupon,
      removeCoupon,
      getQuantityForProduct,
      decreaseProductQuantity,
    };
  }, [accessToken, state, loading, error, refresh]);

  return <CartContext.Provider value={value}>{children}</CartContext.Provider>;
}

export function useCart() {
  const context = useContext(CartContext);
  if (!context) throw new Error("useCart must be used inside CartProvider");
  return context;
}
