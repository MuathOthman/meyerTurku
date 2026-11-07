import { createFileRoute, redirect } from "@tanstack/react-router";
import { AuthPage } from "@/components/AuthPage";
import { currentUser } from "@/lib/auth";

export const Route = createFileRoute("/signup")({
  beforeLoad: async () => {
    if (await currentUser()) throw redirect({ to: "/app" });
  },
  head: () => ({ meta: [{ title: "Sign up · Keel" }] }),
  component: () => <AuthPage mode="signup" />,
});
