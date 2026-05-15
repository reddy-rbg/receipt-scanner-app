import { useCallback, useEffect, useState } from 'react';
import {
  ActivityIndicator,
  RefreshControl,
  ScrollView,
  StyleSheet,
  Text,
  TextInput,
  TouchableOpacity,
  View,
} from 'react-native';
import { useFocusEffect } from 'expo-router';
import { getGuestSessionId, getUserToken, useAuth } from '../../stores/authStore';
import { DARK_COLORS, useTheme } from '../../stores/themeStore';

const API = 'https://web-production-3605f4.up.railway.app';

type PriceMemoryItem = {
  item_name: string;
  product_size?: string | null;
  times_bought: number;
  lowest_price: number;
  highest_price: number;
  average_price: number;
  usual_price: number;
  price_range: number;
  volatility_pct: number;
  good_deal_price: number;
  avoid_above_price: number;
  cheapest_store?: string | null;
  last_bought_date?: string | null;
  buy_frequency_days?: number | null;
  next_expected_date?: string | null;
  recommendation: string;
};

const n = (v: any) => Number.parseFloat(v) || 0;
const money = (v: any) => `$${n(v).toFixed(2)}`;

function recommendationLabel(value: string) {
  switch (value) {
    case 'may need soon': return 'May need soon';
    case 'compare before buying': return 'Compare first';
    case 'needs more history': return 'Learning';
    default: return 'Watch price';
  }
}

export default function PriceMemoryScreen() {
  const { colors: C } = useTheme();
  const s = createStyles(C);
  const { user } = useAuth();
  const [items, setItems] = useState<PriceMemoryItem[]>([]);
  const [shown, setShown] = useState<PriceMemoryItem[]>([]);
  const [query, setQuery] = useState('');
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState('');

  useFocusEffect(useCallback(() => { loadMemory(false); }, [user?.id, user?.guest_session_id]));

  useEffect(() => {
    const q = query.trim().toLowerCase();
    if (!q) {
      setShown(items);
      return;
    }
    setShown(items.filter(item => [
      item.item_name,
      item.product_size,
      item.cheapest_store,
      item.recommendation,
    ].filter(Boolean).join(' ').toLowerCase().includes(q)));
  }, [query, items]);

  async function loadMemory(isRefresh = false) {
    if (!user) return;
    if (isRefresh) setRefreshing(true);
    else setLoading(true);
    setError('');

    try {
      const token = getUserToken();
      const guestId = getGuestSessionId();
      const isGuest = !!guestId || user.is_guest || user.isGuest || token === 'guest';
      const headers: any = {};
      if (!isGuest && token) headers.Authorization = `Bearer ${token}`;
      const url = isGuest
        ? `${API}/price-memory?session_id=${encodeURIComponent(guestId || user.id)}&limit=150`
        : `${API}/price-memory?limit=150`;

      const res = await fetch(url, { headers });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || 'Could not load Price Memory.');
      const nextItems = data.items || [];
      setItems(nextItems);
      setShown(nextItems);
    } catch (e: any) {
      setError(e.message || 'Could not load Price Memory.');
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }

  const strongItems = items.filter(item => item.recommendation === 'may need soon').length;
  const compareItems = items.filter(item => item.recommendation === 'compare before buying').length;
  const avgAvoid = items.length
    ? items.reduce((sum, item) => sum + n(item.avoid_above_price), 0) / items.length
    : 0;

  return (
    <View style={s.screen}>
      <ScrollView
        contentContainerStyle={s.content}
        refreshControl={<RefreshControl refreshing={refreshing} onRefresh={() => loadMemory(true)} tintColor={C.accent} />}
        showsVerticalScrollIndicator={false}
        keyboardShouldPersistTaps="handled"
      >
        <View style={s.hero}>
          <Text style={s.heroKicker}>AI Shopping Memory</Text>
          <Text style={s.heroTitle}>Price Memory</Text>
          <Text style={s.heroSub}>Your app learns the prices you actually paid and turns them into buy, compare, and avoid signals.</Text>
        </View>

        <View style={s.statsRow}>
          <View style={s.statBox}>
            <Text style={s.statVal}>{items.length}</Text>
            <Text style={s.statLbl}>Tracked</Text>
          </View>
          <View style={s.statBox}>
            <Text style={[s.statVal, { color: C.green }]}>{strongItems}</Text>
            <Text style={s.statLbl}>Need soon</Text>
          </View>
          <View style={s.statBox}>
            <Text style={[s.statVal, { color: C.gold }]}>{compareItems}</Text>
            <Text style={s.statLbl}>Compare</Text>
          </View>
        </View>

        <View style={s.searchWrap}>
          <TextInput
            style={s.search}
            value={query}
            onChangeText={setQuery}
            placeholder="Search item, store, signal..."
            placeholderTextColor={C.text3}
            autoCorrect={false}
            returnKeyType="search"
          />
          {query ? (
            <TouchableOpacity style={s.clearBtn} onPress={() => setQuery('')}>
              <Text style={s.clearTxt}>Clear</Text>
            </TouchableOpacity>
          ) : null}
        </View>

        {loading ? (
          <View style={s.stateBox}>
            <ActivityIndicator color={C.accent} />
            <Text style={s.stateText}>Building your Price Memory...</Text>
          </View>
        ) : error ? (
          <View style={s.stateBox}>
            <Text style={s.errorText}>{error}</Text>
            <TouchableOpacity style={s.retryBtn} onPress={() => loadMemory(false)}>
              <Text style={s.retryTxt}>Retry</Text>
            </TouchableOpacity>
          </View>
        ) : shown.length === 0 ? (
          <View style={s.stateBox}>
            <Text style={s.emptyTitle}>No price memory yet</Text>
            <Text style={s.stateText}>Scan receipts with item prices. Repeat purchases become smarter over time.</Text>
          </View>
        ) : (
          <View style={s.list}>
            {shown.map((item, index) => (
              <View key={`${item.item_name}-${item.product_size || ''}-${index}`} style={s.card}>
                <View style={s.cardHeader}>
                  <View style={{ flex: 1 }}>
                    <Text style={s.itemName} numberOfLines={2}>{item.item_name}</Text>
                    <Text style={s.itemMeta}>
                      {[item.product_size, item.cheapest_store, item.last_bought_date].filter(Boolean).join('  ·  ')}
                    </Text>
                  </View>
                  <View style={s.signalPill}>
                    <Text style={s.signalTxt}>{recommendationLabel(item.recommendation)}</Text>
                  </View>
                </View>

                <View style={s.priceGrid}>
                  <View>
                    <Text style={s.priceLbl}>Usual</Text>
                    <Text style={s.priceVal}>{money(item.usual_price)}</Text>
                  </View>
                  <View>
                    <Text style={s.priceLbl}>Good deal</Text>
                    <Text style={[s.priceVal, { color: C.green }]}>{money(item.good_deal_price)}</Text>
                  </View>
                  <View>
                    <Text style={s.priceLbl}>Avoid above</Text>
                    <Text style={[s.priceVal, { color: C.red }]}>{money(item.avoid_above_price)}</Text>
                  </View>
                </View>

                <View style={s.rangeRow}>
                  <Text style={s.rangeText}>
                    Lowest {money(item.lowest_price)} · Highest {money(item.highest_price)} · {item.times_bought} buy{item.times_bought === 1 ? '' : 's'}
                  </Text>
                  {item.buy_frequency_days ? (
                    <Text style={s.rangeText}>Every ~{item.buy_frequency_days} days</Text>
                  ) : null}
                </View>
              </View>
            ))}
          </View>
        )}

        {items.length > 0 ? (
          <View style={s.footerNote}>
            <Text style={s.footerText}>Average avoid-above signal: {money(avgAvoid)}. Use this before buying repeat items.</Text>
          </View>
        ) : null}
      </ScrollView>
    </View>
  );
}

const createStyles = (C: typeof DARK_COLORS) => StyleSheet.create({
  screen:{ flex:1, backgroundColor:C.bg },
  content:{ padding:16, paddingBottom:40 },
  hero:{ marginBottom:16 },
  heroKicker:{ color:C.accent, fontSize:11, fontWeight:'700', textTransform:'uppercase', letterSpacing:0.6, marginBottom:6 },
  heroTitle:{ color:C.text, fontSize:30, fontWeight:'900', letterSpacing:0 },
  heroSub:{ color:C.text2, fontSize:13, lineHeight:19, marginTop:6 },
  statsRow:{ flexDirection:'row', gap:10, marginBottom:14 },
  statBox:{ flex:1, backgroundColor:C.surface, borderWidth:1, borderColor:C.border, borderRadius:12, padding:12 },
  statVal:{ color:C.accent, fontSize:22, fontWeight:'900' },
  statLbl:{ color:C.text2, fontSize:11, marginTop:2 },
  searchWrap:{ flexDirection:'row', alignItems:'center', gap:8, marginBottom:14 },
  search:{ flex:1, backgroundColor:C.surface2, borderWidth:1, borderColor:C.border, borderRadius:12, color:C.text, paddingHorizontal:14, paddingVertical:11, fontSize:14 },
  clearBtn:{ paddingHorizontal:12, paddingVertical:10, borderRadius:10, backgroundColor:C.surface2, borderWidth:1, borderColor:C.border },
  clearTxt:{ color:C.accent, fontSize:12, fontWeight:'700' },
  stateBox:{ alignItems:'center', justifyContent:'center', backgroundColor:C.surface, borderWidth:1, borderColor:C.border, borderRadius:14, padding:24, gap:10 },
  stateText:{ color:C.text2, fontSize:13, textAlign:'center', lineHeight:19 },
  errorText:{ color:C.red, fontSize:13, textAlign:'center', lineHeight:19 },
  retryBtn:{ backgroundColor:C.accent, borderRadius:10, paddingHorizontal:16, paddingVertical:9 },
  retryTxt:{ color:'#fff', fontWeight:'700', fontSize:13 },
  emptyTitle:{ color:C.text, fontSize:17, fontWeight:'800' },
  list:{ gap:10 },
  card:{ backgroundColor:C.surface, borderWidth:1, borderColor:C.border, borderRadius:14, padding:14 },
  cardHeader:{ flexDirection:'row', alignItems:'flex-start', gap:10, marginBottom:12 },
  itemName:{ color:C.text, fontSize:15, fontWeight:'800', lineHeight:20 },
  itemMeta:{ color:C.text3, fontSize:11, marginTop:4 },
  signalPill:{ backgroundColor:'rgba(124,106,255,0.12)', borderWidth:1, borderColor:'rgba(124,106,255,0.24)', borderRadius:99, paddingHorizontal:9, paddingVertical:4 },
  signalTxt:{ color:C.accent, fontSize:10, fontWeight:'800' },
  priceGrid:{ flexDirection:'row', justifyContent:'space-between', backgroundColor:C.surface2, borderRadius:12, padding:12, gap:8 },
  priceLbl:{ color:C.text3, fontSize:10, marginBottom:3 },
  priceVal:{ color:C.text, fontSize:15, fontWeight:'900' },
  rangeRow:{ marginTop:10, gap:4 },
  rangeText:{ color:C.text2, fontSize:11, lineHeight:15 },
  footerNote:{ marginTop:14, backgroundColor:'rgba(74,222,128,0.08)', borderWidth:1, borderColor:'rgba(74,222,128,0.22)', borderRadius:12, padding:12 },
  footerText:{ color:C.green, fontSize:12, lineHeight:17, textAlign:'center' },
});
