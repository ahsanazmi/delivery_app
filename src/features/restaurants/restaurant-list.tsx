import { Image, Pressable, RefreshControl, ScrollView, StyleSheet, Text, View } from 'react-native';

import type { Restaurant } from '@/types/restaurant';
import { deliveryLabel, rupees } from '@/utils/currency';

type Props = {
  restaurants: Restaurant[];
  refreshing: boolean;
  onRefresh: () => void;
  onSelect: (restaurant: Restaurant) => void;
};

export function RestaurantList({ restaurants, refreshing, onRefresh, onSelect }: Props) {
  return (
    <ScrollView
      style={styles.scroll}
      contentContainerStyle={styles.content}
      refreshControl={<RefreshControl refreshing={refreshing} onRefresh={onRefresh} tintColor="#FF5A1F" />}>
      <Text style={styles.sectionTitle}>Open restaurants</Text>
      {restaurants.length === 0 ? <EmptyState /> : restaurants.map((restaurant) => <RestaurantCard key={restaurant.id} restaurant={restaurant} onPress={() => onSelect(restaurant)} />)}
    </ScrollView>
  );
}

export function RestaurantCard({ restaurant, onPress }: { restaurant: Restaurant; onPress: () => void }) {
  return (
    <Pressable accessibilityRole="button" onPress={onPress} style={({ pressed }) => [styles.card, pressed && styles.pressed]}>
      <RestaurantImage uri={restaurant.cover_image_url ?? restaurant.logo_url} />
      <View style={styles.cardBody}>
        <View style={styles.cardHeading}><Text numberOfLines={1} style={styles.name}>{restaurant.name}</Text><Text style={styles.rating}>★ {Number(restaurant.average_rating).toFixed(1)}</Text></View>
        <Text numberOfLines={1} style={styles.address}>{restaurant.address}</Text>
        <View style={styles.metaRow}><Text style={styles.meta}>Min. order {rupees(restaurant.minimum_order)}</Text><Text style={styles.dot}>•</Text><Text style={styles.meta}>{deliveryLabel(restaurant.delivery_fee)}</Text></View>
      </View>
    </Pressable>
  );
}

export function RestaurantImage({ uri, large = false }: { uri: string | null; large?: boolean }) {
  if (uri) return <Image source={{ uri }} style={[styles.image, large && styles.largeImage]} />;
  return <View style={[styles.image, styles.fallbackImage, large && styles.largeImage]}><Text style={styles.fallbackEmoji}>🍲</Text></View>;
}

function EmptyState() {
  return <View style={styles.empty}><Text style={styles.emptyEmoji}>🍽️</Text><Text style={styles.emptyTitle}>No restaurants are open right now</Text><Text style={styles.emptyCopy}>Pull down to refresh, or check back shortly.</Text></View>;
}

const styles = StyleSheet.create({
  scroll: { flex: 1 }, content: { padding: 20, paddingBottom: 40, gap: 14 }, sectionTitle: { color: '#241913', fontSize: 19, fontWeight: '800', marginBottom: 2 },
  card: { backgroundColor: '#fff', borderRadius: 18, overflow: 'hidden', borderWidth: 1, borderColor: '#F0E3DC' }, pressed: { opacity: 0.75 },
  image: { width: '100%', height: 132, backgroundColor: '#FFE4D6' }, largeImage: { height: 240 }, fallbackImage: { justifyContent: 'center', alignItems: 'center' }, fallbackEmoji: { fontSize: 46 },
  cardBody: { padding: 14, gap: 6 }, cardHeading: { flexDirection: 'row', gap: 8, alignItems: 'center' }, name: { flex: 1, color: '#241913', fontSize: 17, fontWeight: '800' },
  rating: { color: '#157347', backgroundColor: '#E8F6EE', borderRadius: 7, overflow: 'hidden', paddingHorizontal: 7, paddingVertical: 3, fontSize: 12, fontWeight: '800' },
  address: { color: '#81716A', fontSize: 13 }, metaRow: { flexDirection: 'row', gap: 7, alignItems: 'center' }, meta: { color: '#5F5049', fontSize: 13, fontWeight: '700' }, dot: { color: '#B5A9A3' },
  empty: { backgroundColor: '#fff', borderRadius: 18, padding: 30, alignItems: 'center', borderWidth: 1, borderColor: '#F0E3DC' }, emptyEmoji: { fontSize: 34 }, emptyTitle: { color: '#241913', fontWeight: '800', marginTop: 12, textAlign: 'center' }, emptyCopy: { color: '#81716A', marginTop: 6, textAlign: 'center', lineHeight: 20 },
});
