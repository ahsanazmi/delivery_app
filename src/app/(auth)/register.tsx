import { Redirect } from "expo-router";

import { AuthScreen } from "@/features/auth/auth-screen";
import { useSession } from "@/features/auth/session-context";

export default function RegisterScreen() {
  const { user } = useSession();
  if (user) return <Redirect href="/home" />;
  return <AuthScreen initialMode="register" />;
}
