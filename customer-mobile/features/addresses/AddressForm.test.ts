import { addressToFormValues, formValuesToPayload, validateAddressForm } from "./AddressForm";

// Maps & Location System Phase 5 — pure-function coverage for the form's
// validation and payload-shaping logic, independent of rendering.

const VALID_VALUES = {
  label: "Home",
  recipient_name: "Ravi Kumar",
  phone: "9999999999",
  address_line: "1 Main Road",
  city: "Azamgarh",
  district: "Azamgarh",
  state: "Uttar Pradesh",
  postal_code: "276001",
  landmark: "",
  latitude: null,
  longitude: null,
  formatted_address: null,
  place_id: null,
  is_default: false,
};

describe("validateAddressForm", () => {
  it("accepts a fully valid form", () => {
    expect(validateAddressForm(VALID_VALUES)).toBeNull();
  });

  it("rejects a recipient name under 2 characters", () => {
    expect(validateAddressForm({ ...VALID_VALUES, recipient_name: "R" })).toMatch(/recipient/i);
  });

  it("rejects a phone number under 8 digits", () => {
    expect(validateAddressForm({ ...VALID_VALUES, phone: "12345" })).toMatch(/phone/i);
  });

  it("rejects a missing city", () => {
    expect(validateAddressForm({ ...VALID_VALUES, city: "A" })).toMatch(/city/i);
  });

  it("rejects a missing postal code", () => {
    expect(validateAddressForm({ ...VALID_VALUES, postal_code: "1" })).toMatch(/postal/i);
  });

  it("does not require district — optional in this market's addressing, unlike city/state", () => {
    expect(validateAddressForm({ ...VALID_VALUES, district: "" })).toBeNull();
  });
});

describe("formValuesToPayload", () => {
  it("trims whitespace and converts blank optional fields to null", () => {
    const payload = formValuesToPayload({
      ...VALID_VALUES,
      district: "  ",
      landmark: "  ",
    });
    expect(payload.district).toBeNull();
    expect(payload.landmark).toBeNull();
    expect(payload.recipient_name).toBe("Ravi Kumar");
  });

  it("defaults a blank label to Home", () => {
    const payload = formValuesToPayload({ ...VALID_VALUES, label: "  " });
    expect(payload.label).toBe("Home");
  });

  it("carries a real district/landmark through untouched", () => {
    const payload = formValuesToPayload({ ...VALID_VALUES, district: "Jaunpur", landmark: "Near the temple" });
    expect(payload.district).toBe("Jaunpur");
    expect(payload.landmark).toBe("Near the temple");
  });
});

describe("addressToFormValues", () => {
  it("converts a null district/landmark from the API into an empty editable string", () => {
    const values = addressToFormValues({
      id: "a1", user_id: "u1", label: "Home", recipient_name: "Ravi", phone: "9999999999",
      address_line: "1 Road", city: "Town", district: null, state: "ST", postal_code: "123456",
      landmark: null, latitude: null, longitude: null, formatted_address: null, place_id: null,
      is_default: true, is_active: true, created_at: "", updated_at: "",
    });
    expect(values.district).toBe("");
    expect(values.landmark).toBe("");
    expect(values.is_default).toBe(true);
  });

  it("carries an existing address' coordinates through for re-editing on the map", () => {
    const values = addressToFormValues({
      id: "a1", user_id: "u1", label: "Home", recipient_name: "Ravi", phone: "9999999999",
      address_line: "1 Road", city: "Azamgarh", district: "Azamgarh", state: "UP", postal_code: "276001",
      landmark: null, latitude: 26.068, longitude: 83.1836, formatted_address: null, place_id: null,
      is_default: true, is_active: true, created_at: "", updated_at: "",
    });
    expect(values.latitude).toBe(26.068);
    expect(values.longitude).toBe(83.1836);
  });
});

describe("Maps & Location System Phase 6 — map-picked coordinates", () => {
  it("formValuesToPayload carries a picked latitude/longitude straight through", () => {
    const payload = formValuesToPayload({ ...VALID_VALUES, latitude: 26.068, longitude: 83.1836 });
    expect(payload.latitude).toBe(26.068);
    expect(payload.longitude).toBe(83.1836);
  });

  it("formValuesToPayload leaves latitude/longitude null when no location was ever picked — manual entry alone must stay fully valid", () => {
    const payload = formValuesToPayload(VALID_VALUES);
    expect(payload.latitude).toBeNull();
    expect(payload.longitude).toBeNull();
  });

  it("validateAddressForm never requires a picked location — the map is optional, never a hard requirement", () => {
    expect(validateAddressForm({ ...VALID_VALUES, latitude: null, longitude: null })).toBeNull();
  });
});
