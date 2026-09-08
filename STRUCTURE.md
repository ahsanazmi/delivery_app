Project folder structure for building a Swiggy-like delivery app (Expo + React Native)

Top-level

- src/: application source

Core folders

- src/screens/: app screens (Home, Restaurant, Cart, Checkout, Orders, DeliveryTracking, Profile, Auth)
- src/components/: reusable UI components (buttons, cards, lists, headers, map markers)
- src/navigation/: navigation stacks and tab setup
- src/services/: external integrations (API clients, sockets, maps)
  - src/services/api/: REST/HTTP client code
- src/store/: app state (Redux/RTK, Zustand, or Context)
- src/hooks/: custom hooks
- src/utils/: helpers and utilities
- src/constants/: app-wide constants and configs
- src/types/: TypeScript types and interfaces
- src/assets/: static assets (images, icons)

Feature folders

- src/features/restaurants/: restaurant listings, details, menus
- src/features/orders/: order creation, history, status
- src/features/delivery/: courier tracking, live location, ETA
- src/features/auth/: login, signup, password flows
- src/features/profile/: user settings, addresses
- src/features/cart/: cart logic and promotions

Next steps (suggested)

1. Choose a state solution (Redux Toolkit / Zustand / Context + hooks).
2. Scaffold navigation (`src/navigation/RootNavigator.tsx`).
3. Add an `apiClient` in `src/services/api` to target your FastAPI backend.
4. Scaffold one screen (Home) + one component (RestaurantCard) to verify wiring.

If you want, I can scaffold the initial screen/component and a sample API client next.
