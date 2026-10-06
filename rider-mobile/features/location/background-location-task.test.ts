// Maps & Location System Phase 22 — Rider Location Permission's
// "Background location unavailable" state. Covers only the new
// checkBackgroundLocationAvailability() addition — the rest of this
// module (starting/stopping the real background task) predates this
// phase and isn't touched here.
//
// This module's own getModules() loads expo-task-manager/expo-location
// via a real dynamic import() — deliberately, so importing this file at
// all never breaks Expo Go (see its own docstring). That dynamic
// import() has no support under this project's Jest/Babel CJS transform
// (ERR_VM_DYNAMIC_IMPORT_CALLBACK_MISSING_FLAG, confirmed by running
// this test), so getModules() always resolves to null here — the same
// "unsupported runtime" path a real Expo Go session hits. That's exactly
// what this one meaningful test proves: the function degrades safely to
// "unavailable" rather than throwing, in the one runtime state Jest can
// actually exercise for this file.

import { checkBackgroundLocationAvailability } from "./background-location-task";

describe("checkBackgroundLocationAvailability", () => {
  it("resolves to unavailable, never throws, when the runtime doesn't support the background location modules", async () => {
    await expect(checkBackgroundLocationAvailability()).resolves.toBe("unavailable");
  });
});
