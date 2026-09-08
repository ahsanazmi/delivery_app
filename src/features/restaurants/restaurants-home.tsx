import { useCallback, useEffect, useState } from 'react';
import { ActivityIndicator, Pressable, StyleSheet, Text, View } from 'react-native';
import { useRouter } from 'expo-router';
import { SafeAreaView } from 'react-native-safe-area-context';

import { useSession } from '@/features/auth/session-context';
import { ApiError } from '@/services/api/apiClient';
import { getRestaurants, Restaurant } from '@/services/api/restaurantsApi';
import { RestaurantList } from './restaurant-list';

export function RestaurantsHome() {
  const { user, signOut } = useSession();
  const router = useRouter();
  const [restaurants, setRestaurants] = useState<Restaurant[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const loadRestaurants = useCallback(async () => {
    setError(null);
    try {
      setRestaurants(await getRestaurants());
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : 'Unable to load restaurants.');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { loadRestaurants(); }, [loadRestaurants]);
  const firstName = user?.name.split(' ')[0] ?? 'there';

  return (
    <SafeAreaView style={styles.safeArea} edges={['top']}>
      <View style={styles.header}><View><Text style={styles.brand}>SAY HI CHAI</Text><Text style={styles.greeting}>Hi, {firstName} 👋</Text><Text style={styles.location}>Discover local favourites</Text></View><Pressable onPress={signOut} style={styles.signOut}><Text style={styles.signOutText}>Sign out</Text></Pressable></View>
      {loading ? <View style={styles.center}><ActivityIndicator size="large" color="#FF5A1F" /></View> : error ? <View style={styles.center}><Text style={styles.error}>{error}</Text><Pressable style={styles.retry} onPress={() => { setLoading(true); loadRestaurants(); }}><Text style={styles.retryText}>Try again</Text></Pressable></View> : <RestaurantList restaurants={restaurants} refreshing={loading} onRefresh={() => { setLoading(true); loadRestaurants(); }} onSelect={(restaurant) => router.push({ pathname: '/restaurants/[id]', params: { id: restaurant.id } })} />}
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  safeArea: { flex: 1, backgroundColor: '#FFF8F2' }, header: { paddingHorizontal: 20, paddingTop: 16, paddingBottom: 12, flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center' },
  brand: { color: '#D83B05', fontSize: 11, fontWeight: '900', letterSpacing: 1.4 }, greeting: { color: '#241913', fontSize: 27, fontWeight: '800', marginTop: 4 }, location: { color: '#81716A', fontSize: 14, marginTop: 2 },
  signOut: { padding: 9, borderRadius: 8, backgroundColor: '#FEE4E2' }, signOutText: { color: '#B42318', fontSize: 12, fontWeight: '800' }, center: { flex: 1, alignItems: 'center', justifyContent: 'center', padding: 28 }, error: { color: '#B42318', textAlign: 'center', lineHeight: 21 }, retry: { backgroundColor: '#FF5A1F', marginTop: 14, borderRadius: 10, paddingHorizontal: 16, paddingVertical: 11 }, retryText: { color: '#fff', fontWeight: '800' },
});
