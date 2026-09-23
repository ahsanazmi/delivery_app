import { apiFetch } from "./apiClient";

export type DocumentType = "DRIVING_LICENSE" | "VEHICLE_REGISTRATION" | "IDENTITY_DOCUMENT" | "BANK_DOCUMENT" | "PROFILE_PHOTO";

export type DocumentVerificationStatus = "PENDING" | "APPROVED" | "REJECTED";

export type RiderDocument = {
  id: string;
  document_type: DocumentType;
  document_number: string | null;
  document_url: string;
  verification_status: DocumentVerificationStatus;
  rejection_reason: string | null;
  created_at: string;
  updated_at: string;
};

export type RiderDocumentInput = {
  document_type: DocumentType;
  document_url: string;
  document_number?: string;
};

export type RiderDocumentUpdateInput = {
  document_url?: string;
  document_number?: string;
};

export function listRiderDocuments(accessToken: string) {
  return apiFetch<RiderDocument[]>("/api/v1/rider/documents", {
    headers: { Authorization: `Bearer ${accessToken}` },
  });
}

export function createRiderDocument(accessToken: string, payload: RiderDocumentInput) {
  return apiFetch<RiderDocument>("/api/v1/rider/documents", {
    method: "POST",
    headers: { "Content-Type": "application/json", Authorization: `Bearer ${accessToken}` },
    body: JSON.stringify(payload),
  });
}

export function updateRiderDocument(accessToken: string, documentId: string, payload: RiderDocumentUpdateInput) {
  return apiFetch<RiderDocument>(`/api/v1/rider/documents/${documentId}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json", Authorization: `Bearer ${accessToken}` },
    body: JSON.stringify(payload),
  });
}

export function deleteRiderDocument(accessToken: string, documentId: string) {
  return apiFetch<void>(`/api/v1/rider/documents/${documentId}`, {
    method: "DELETE",
    headers: { Authorization: `Bearer ${accessToken}` },
  });
}
