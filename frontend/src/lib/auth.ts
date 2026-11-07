// Accounts live in the backend's MongoDB. The login itself is an httpOnly cookie this code cannot read.
import { request } from "@/lib/api";

export type User = { id: string; name: string; email: string };
type Answer = { user: User | null };

const send = (url: string, body?: object) =>
  request<Answer>(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body ?? {}),
  });

/** Who is logged in. If the backend cannot say, nobody is: the login page reports the problem. */
export async function currentUser(): Promise<User | null> {
  try {
    return (await request<Answer>("/api/auth/session")).user;
  } catch {
    return null;
  }
}

export const signUp = (details: { name: string; email: string; password: string }) =>
  send("/api/auth/signup", details);

export const logIn = (details: { email: string; password: string }) =>
  send("/api/auth/login", details);

export const logOut = () => send("/api/auth/logout");
