import { Redirect } from 'expo-router';

import { AuthScreen } from '@/features/auth/auth-screen';
import { useSession } from '@/features/auth/session-context';

export default function LoginScreen() {
  const { user } = useSession();
  return user ? <Redirect href="/home" /> : <AuthScreen />;
}
