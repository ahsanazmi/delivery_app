import {
    createContext,
    PropsWithChildren,
    useContext,
    useMemo,
    useState,
} from "react";

export type CartLine = {
  id: string;
  productId: string;
  restaurantId: string;
  restaurantName: string;
  productName: string;
  price: number;
  quantity: number;
  imageUrl?: string | null;
};

type CartContextValue = {
  items: CartLine[];
  itemCount: number;
  subtotal: number;
  addItem: (
    item: Omit<CartLine, "id" | "quantity"> & { quantity?: number },
  ) => void;
  updateQuantity: (productId: string, nextQuantity: number) => void;
  removeItem: (productId: string) => void;
  clearCart: () => void;
};

const CartContext = createContext<CartContextValue | null>(null);

export function CartProvider({ children }: PropsWithChildren) {
  const [items, setItems] = useState<CartLine[]>([]);

  const value = useMemo<CartContextValue>(() => {
    const subtotal = items.reduce(
      (sum, item) => sum + item.price * item.quantity,
      0,
    );
    const itemCount = items.reduce((sum, item) => sum + item.quantity, 0);

    function addItem(
      itemInput: Omit<CartLine, "id" | "quantity"> & { quantity?: number },
    ) {
      const qty = Math.max(1, itemInput.quantity ?? 1);
      setItems((current) => {
        const hasItems = current.length > 0;
        if (hasItems && current[0].restaurantId !== itemInput.restaurantId) {
          return current;
        }

        const existing = current.find(
          (entry) => entry.productId === itemInput.productId,
        );
        if (existing) {
          return current.map((entry) =>
            entry.productId === itemInput.productId
              ? {
                  ...entry,
                  quantity: entry.quantity + qty,
                  price: itemInput.price || entry.price,
                }
              : entry,
          );
        }

        const nextItem: CartLine = {
          id: `${itemInput.productId}-${Date.now()}`,
          productId: itemInput.productId,
          restaurantId: itemInput.restaurantId,
          restaurantName: itemInput.restaurantName,
          productName: itemInput.productName,
          price: itemInput.price,
          quantity: qty,
          imageUrl: itemInput.imageUrl,
        };

        return [...current, nextItem];
      });
    }

    function updateQuantity(productId: string, nextQuantity: number) {
      setItems((current) =>
        current
          .map((item) =>
            item.productId === productId
              ? { ...item, quantity: Math.max(0, nextQuantity) }
              : item,
          )
          .filter((item) => item.quantity > 0),
      );
    }

    function removeItem(productId: string) {
      setItems((current) =>
        current.filter((item) => item.productId !== productId),
      );
    }

    function clearCart() {
      setItems([]);
    }

    return {
      items,
      itemCount,
      subtotal,
      addItem,
      updateQuantity,
      removeItem,
      clearCart,
    };
  }, [items]);

  return <CartContext.Provider value={value}>{children}</CartContext.Provider>;
}

export function useCart() {
  const context = useContext(CartContext);
  if (!context) throw new Error("useCart must be used inside CartProvider");
  return context;
}
