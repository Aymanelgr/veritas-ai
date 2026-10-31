import { createContext, useContext } from "react";

// The signed-in user, available to any component. The backend enforces every permission;
// hiding buttons here only avoids showing actions that would be refused.
export const UserContext = createContext(null);
export const useUser = () => useContext(UserContext);

const RANK = { viewer: 1, reviewer: 2, admin: 3 };
export const can = (user, role) => (RANK[user?.role] ?? 0) >= RANK[role];
