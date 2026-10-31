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
export const reprocessDocument = (id) => data(api.post(`/documents/${id}/reprocess`));
export const deleteDocument = (id) => api.delete(`/documents/${id}`);
export const fileUrl = (id) => `/api/documents/${id}/file`;
export const previewUrl = (id, page = 1) => `/api/documents/${id}/preview?page=${page}`;

// onProgress receives a number from 0 to 1 while the files are sent.
export function uploadDocuments(files, onProgress) {
  const form = new FormData();
  for (const file of files) form.append("files", file);
  return data(api.post("/documents", form, {
    onUploadProgress: (e) => e.total && onProgress?.(e.loaded / e.total),
  }));
}

export const listFindings = (params) => data(api.get("/findings", { params }));
export const reviewFinding = (id, decision, note) =>
  data(api.post(`/findings/${id}/review`, { decision, note }));

export const listNotifications = () => data(api.get("/notifications"));
export const markNotificationRead = (id) => data(api.post(`/notifications/${id}/read`));

export const askQuestion = (question) => data(api.post("/ask", { question }));

// FastAPI puts error messages in "detail".
export const errorMessage = (error) =>
  error?.response?.data?.detail ?? error?.message ?? "Something went wrong";
