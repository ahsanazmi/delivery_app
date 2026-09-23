# Phase 13 — Customer Mobile Razorpay Checkout

## Scope
Integrate Razorpay checkout into `customer-mobile/`: request payment
initialization, receive checkout information, open Razorpay checkout,
receive the result, send it to backend verification, query/refetch
payment status, display the final result. The mobile callback alone is
never proof of a successful payment — backend verification is mandatory.

## Architecture decision (asked, not assumed)
`react-native-razorpay` is a native module. It does not support React
Native's New Architecture (confirmed via an open, unresolved GitHub issue
on the package: [razorpay/react-native-razorpay#510](https://github.com/razorpay/react-native-razorpay/issues/510)),
and this app was on Expo SDK 57 (React Native 0.86), where the New
Architecture has been mandatory with no opt-out since SDK 55. Presented
this to the user as a real fork — WebView-based checkout (stays on SDK 57
as-is) vs. downgrading the whole app to SDK 54 (the last SDK where the
New Architecture can still be disabled) to use the native SDK. The user
chose the native SDK, explicitly accepting the SDK downgrade.

(Note found during implementation, not acted on: the installed
`react-native-razorpay@3.0.0` package's own bundled documentation claims
New Architecture support was added in v2.3.1 with automatic runtime
detection and fallback — which would contradict the still-open GitHub
issue. This wasn't independently verified either way; the already-decided
SDK 54 downgrade uses the package's original, most battle-tested Legacy
Architecture code path regardless, so this ambiguity didn't need to be
resolved to move forward. Worth re-examining before ever upgrading past
SDK 54 again.)

## What was built

### SDK downgrade (Expo 57 → 54)
- `customer-mobile/package.json` — every `expo-*`/React Native ecosystem
  package pinned to its exact Expo SDK 54 version (sourced from the
  locally-installed `expo` package's own `bundledNativeModules.json`
  manifest, since `npx expo install --fix`'s own version-resolution
  network call failed in this environment — `npm`'s registry access
  itself was unaffected). `react`/`react-dom` → `19.1.0`, `react-native` →
  `0.81.5`, added `@react-navigation/native` (now a direct dependency —
  previously only transitive) and `react-native-razorpay`.
- `customer-mobile/app.json` — added `"newArchEnabled": false` (required:
  SDK 54 defaults new-architecture-on; this is what actually re-enables
  Legacy Architecture) and iOS `infoPlist.LSApplicationQueriesSchemes`
  (`tez`/`phonepe`/`paytmmp`) so UPI apps can be detected/opened from the
  Razorpay checkout sheet, per the package's own iOS integration notes.

### Downgrade fallout fixed
- `app/_layout.tsx` — `expo-router`'s SDK 54 version no longer re-exports
  `DarkTheme`/`DefaultTheme`/`ThemeProvider`; these now come from
  `@react-navigation/native` directly (react-navigation v7 dropped the
  re-export, not the components themselves).
- `components/animated-icon.tsx` — `StyleSheet.absoluteFill` (the
  registered-style-id form) can no longer be spread into
  `StyleSheet.create`'s object under RN 0.81's stricter types; switched to
  `StyleSheet.absoluteFillObject` (the plain-object form meant for this).

### The checkout flow itself
- `services/api/ordersApi.ts` — `OrderPayload.payment_method` widened to
  `"cod" | "razorpay"`.
- `services/api/paymentsApi.ts` — added `razorpay_key_id` to `Payment`;
  added `PaymentRecord` type and two new calls: `verifyPayment()` (`POST
  /api/v1/payments/{id}/verify`) and `getPaymentRecord()` (`GET
  /api/v1/payments/{id}`) — both against the generic, ownership-checked
  `/api/v1/payments/*` router from Phase 5, since no customer-namespaced
  verify/refetch endpoint exists.
- `app/checkout.tsx`:
  - A payment method selector (COD / Pay Online) replaces the old
    COD-only static card, gated by `GET /customer/payment-methods`'
    `available` flag (disabled and unselectable when Razorpay isn't
    configured).
  - `payWithRazorpay()` implements steps 3-6 of the mandated flow: opens
    `RazorpayCheckout.open({key, amount, currency, order_id, prefill})`
    using exactly the checkout information the backend already returned
    (steps 1-2); on a resolved result, sends it to `verifyPayment()`
    (step 5); **regardless of how verify resolves**, independently
    re-reads the payment via `getPaymentRecord()` (step 6) and treats
    *that* read — not the Razorpay callback, not verify's own response —
    as the only source of truth for whether the payment succeeded.
  - `placeOrder()` branches on the selected method: COD keeps its
    existing fire-and-forget `recordOrderPayment` call unchanged;
    Razorpay awaits the full `payWithRazorpay()` flow before navigating,
    and displays one of three outcomes (paid / not completed / status
    unconfirmed) based on the refetched status.

## Files created
- `customer-mobile/app/__tests__/checkout.razorpay.test.tsx` (6 tests)

## Files modified
- `customer-mobile/package.json`, `app.json`
- `customer-mobile/app/_layout.tsx`
- `customer-mobile/components/animated-icon.tsx`
- `customer-mobile/app/checkout.tsx`
- `customer-mobile/services/api/ordersApi.ts`, `paymentsApi.ts`

## Testing
- `npx tsc --noEmit` — clean across the whole app.
- `npx jest` — 15/15 passing (9 pre-existing + 6 new), including explicit
  proof that a verify-says-paid-but-refetch-says-failed scenario reports
  failure (the refetch wins), and that a cancelled Razorpay checkout never
  calls verify at all.
- No backend changes in this phase — Phase 12's backend suite (1094
  passed) still applies unchanged.

## Known limitations
- Not run on an actual device/emulator or EAS/local native build — no
  such environment is available here (consistent with this project's
  established "TypeScript compile + sanity check is the bar" precedent
  for frontend work without a device). The native `react-native-razorpay`
  module itself (its iOS/Android code) has not been exercised at runtime.
- The New Architecture ambiguity noted above (package docs vs. open
  GitHub issue) was not resolved — the SDK 54 downgrade sidesteps it
  entirely for now.
- Android UPI intent filters (the Android equivalent of the iOS
  `LSApplicationQueriesSchemes` addition) weren't added — the package's
  own docs don't call for an Android-side manifest change for this, only
  iOS's `Info.plist`.
