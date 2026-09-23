import { useCallback, useEffect, useState } from 'react';
import { Pressable, StyleSheet, Text, View } from 'react-native';
import { useRouter } from 'expo-router';
import { SafeAreaView } from 'react-native-safe-area-context';

import { ErrorState, Skeleton } from '@/components/common/ui';
import { useSession } from '@/features/auth/session-context';
import { ApiError } from '@/services/api/apiClient';
import { getRestaurants, Restaurant } from '@/services/api/restaurantsApi';
import { RestaurantList } from './restaurant-list';

const PAGE_SIZE = 10;

export function RestaurantsHome() {
  const { user, signOut } = useSession();
  const router = useRouter();
  const [restaurants, setRestaurants] = useState<Restaurant[]>([]);
  const [offset, setOffset] = useState(0);
  const [hasMore, setHasMore] = useState(false);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [loadingMore, setLoadingMore] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const loadFirstPage = useCallback(async () => {
    setError(null);
    try {
      const data = await getRestaurants({ offset: 0, limit: PAGE_SIZE });
      setRestaurants(data);
      setOffset(data.length);
      setHasMore(data.length === PAGE_SIZE);
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : 'Unable to load restaurants.');
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, []);

  useEffect(() => {
    loadFirstPage();
  }, [loadFirstPage]);

  async function loadMore() {
    if (loadingMore || !hasMore) return;
    setLoadingMore(true);
    try {
      const data = await getRestaurants({ offset, limit: PAGE_SIZE });
      setRestaurants((current) => [...current, ...data]);
      setOffset((current) => current + data.length);
      setHasMore(data.length === PAGE_SIZE);
    } catch {
      // keep whatever's already loaded; the next pull-to-refresh will retry
    } finally {
      setLoadingMore(false);
    }
  }

  function handleRefresh() {
    setRefreshing(true);
    loadFirstPage();
  }

  const firstName = user?.name.split(' ')[0] ?? 'there';

  return (
    <SafeAreaView style={styles.safeArea} edges={['top']}>
      <View style={styles.header}>
        <View>
          <Text style={styles.brand}>SAY HI CHAI</Text>
          <Text style={styles.greeting}>Hi, {firstName} 👋</Text>
          <Text style={styles.location}>Discover local favourites</Text>
        </View>
        <Pressable onPress={signOut} style={styles.signOut}>
          <Text style={styles.signOutText}>Sign out</Text>
        </Pressable>
      </View>
      {loading ? (
        <View style={styles.skeletonList}>
          {Array.from({ length: 4 }).map((_, index) => (
            <View key={index} style={styles.skeletonCard}>
              <Skeleton style={styles.skeletonImage} />
              <Skeleton style={styles.skeletonLineWide} />
              <Skeleton style={styles.skeletonLineNarrow} />
            </View>
          ))}
        </View>
      ) : error ? (
        <View style={styles.center}>
          <ErrorState message={error} onRetry={() => { setLoading(true); loadFirstPage(); }} />
        </View>
      ) : (
        <RestaurantList
          restaurants={restaurants}
          refreshing={refreshing}
          onRefresh={handleRefresh}
          onSelect={(restaurant) => router.push({ pathname: '/restaurants/[id]', params: { id: restaurant.id } })}
          onEndReached={loadMore}
          loadingMore={loadingMore}
          hasMore={hasMore}
        />
      )}
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  safeArea: { flex: 1, backgroundColor: '#FFF8F2' },
  header: { paddingHorizontal: 20, paddingTop: 16, paddingBottom: 12, flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center' },
  brand: { color: '#D83B05', fontSize: 11, fontWeight: '900', letterSpacing: 1.4 },
  greeting: { color: '#241913', fontSize: 27, fontWeight: '800', marginTop: 4 },
  location: { color: '#81716A', fontSize: 14, marginTop: 2 },
  signOut: { padding: 9, borderRadius: 8, backgroundColor: '#FEE4E2' },
  signOutText: { color: '#B42318', fontSize: 12, fontWeight: '800' },
  center: { flex: 1, alignItems: 'center', justifyContent: 'center', padding: 20 },
  skeletonList: { padding: 20, gap: 14 },
  skeletonCard: { backgroundColor: '#fff', borderRadius: 18, padding: 14, borderWidth: 1, borderColor: '#F0E3DC', gap: 10 },
  skeletonImage: { height: 120, borderRadius: 14 },
  skeletonLineWide: { height: 16, width: '70%', borderRadius: 8 },
  skeletonLineNarrow: { height: 12, width: '45%', borderRadius: 8 },
});
