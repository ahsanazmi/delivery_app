import { Redirect } from "expo-router";

import ProfileScreen from "@/app/profile";
import { useSession } from "@/features/auth/session-context";

export default function ProfileTabScreen() {
  const { user } = useSession();
  if (!user) return <Redirect href="/(auth)/login" />;
  return <ProfileScreen />;
}
