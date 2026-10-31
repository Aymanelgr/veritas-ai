// Every call to the FastAPI backend lives here, so pages never build URLs themselves.
import axios from "axios";

// X-Veritas-Client proves the request comes from this dashboard (cross-site request forgery
// protection); the session cookie is sent automatically and is never readable by JavaScript.
const api = axios.create({ baseURL: "/api", withCredentials: true, headers: { "X-Veritas-Client": "web" } });
const data = (request) => request.then((response) => response.data);

// When a session expires, every page gets a 401: tell the app to show the sign-in screen.
api.interceptors.response.use(undefined, (error) => {
  if (error?.response?.status === 401 && !error.config.url.startsWith("/auth/")) {
    window.dispatchEvent(new Event("veritas:signed-out"));
  }
  return Promise.reject(error);
});

export const login = (email, password) => data(api.post("/auth/login", { email, password }));
export const logout = () => api.post("/auth/logout");
export const getMe = () => data(api.get("/auth/me"));

export const getStats = () => data(api.get("/stats"));
export const getHealth = () => data(api.get("/health"));
export const listDocuments = () => data(api.get("/documents"));
export const getDocument = (id) => data(api.get(`/documents/${id}`));
// full=true reads the file again instead of reusing the previous reading and extraction.
export const reprocessDocument = (id, full = false) =>
  data(api.post(`/documents/${id}/reprocess`, null, { params: full ? { full: true } : {} }));
export const deleteDocument = (id) => api.delete(`/documents/${id}`);
export const fileUrl = (id) => `/api/documents/${id}/file`;
export const previewUrl = (id, page = 1) => `/api/documents/${id}/preview?page=${page}`;
export const setOverrides = (id, overrides) => data(api.patch(`/documents/${id}/overrides`, overrides));
export const addCorrection = (id, field_path, value, reason) =>
  data(api.post(`/documents/${id}/corrections`, { field_path, value, reason }));
export const undoCorrection = (id, correctionId) => api.delete(`/documents/${id}/corrections/${correctionId}`);
export const getTimeline = (id) => data(api.get(`/documents/${id}/timeline`));
export const simulateCorrections = (id, changes) =>
  data(api.post(`/documents/${id}/simulate`, { changes }));

// onProgress receives a number from 0 to 1 while the files are sent.
// overrides: {doc_type, language, currency, day_first}; "auto" or empty lets Veritas detect it.
export function uploadDocuments(files, onProgress, overrides = {}) {
  const form = new FormData();
  for (const file of files) form.append("files", file);
  for (const [key, value] of Object.entries(overrides)) {
    if (value !== undefined && value !== null && value !== "" && value !== "auto") form.append(key, String(value));
  }
  return data(api.post("/documents", form, {
    onUploadProgress: (e) => e.total && onProgress?.(e.loaded / e.total),
  }));
}

export const confirmLink = (id, note) => data(api.post(`/links/${id}/confirm`, { note: note || null }));
export const rejectLink = (id, note) => data(api.post(`/links/${id}/reject`, { note }));
export const createLink = (invoice_id, purchase_order_id, note) =>
  data(api.post("/links", { invoice_id, purchase_order_id, note }));

export const listFindings = (params) => data(api.get("/findings", { params }));
export const reviewFinding = (id, decision, note) =>
  data(api.post(`/findings/${id}/review`, { decision, note }));
export const attachEvidence = (id, text) => data(api.post(`/findings/${id}/attachments`, { text }));
export const explainFinding = (id) => data(api.get(`/findings/${id}/explain`));
export const draftClarification = (id) => data(api.post(`/findings/${id}/clarification`));

export const listNotifications = () => data(api.get("/notifications"));
export const markNotificationRead = (id) => data(api.post(`/notifications/${id}/read`));

export const getAlertSettings = () => data(api.get("/settings/alerts"));
export const saveAlertSettings = (settings) => data(api.put("/settings/alerts", settings));
export const listDeliveries = () => data(api.get("/settings/alerts/deliveries"));
export const sendTestAlert = () => data(api.post("/settings/alerts/test"));

// The assistant: conversations are saved per user; document_ids limits the search scope.
export const listConversations = () => data(api.get("/conversations"));
export const getConversation = (id) => data(api.get(`/conversations/${id}`));
export const deleteConversation = (id) => api.delete(`/conversations/${id}`);
export const askQuestion = (question, { conversationId, documentIds } = {}) =>
  data(api.post("/ask", { question, conversation_id: conversationId ?? null, document_ids: documentIds?.length ? documentIds : null }));

// FastAPI puts error messages in "detail".
export const errorMessage = (error) =>
  error?.response?.data?.detail ?? error?.message ?? "Something went wrong";
