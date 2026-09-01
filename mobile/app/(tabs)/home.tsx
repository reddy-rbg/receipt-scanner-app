import AsyncStorage from '@react-native-async-storage/async-storage';
import { Ionicons } from '@expo/vector-icons';
import { router, useFocusEffect } from 'expo-router';
import { useCallback, useMemo, useState } from 'react';
import {
  ActivityIndicator,
  RefreshControl,
  ScrollView,
  StyleSheet,
  Text,
  TouchableOpacity,
  View,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';

import { API } from '../../config/api';
import { getGuestSessionId, getUserToken, useAuth } from '../../stores/authStore';
import { useTheme } from '../../stores/themeStore';

const SHOP_STORAGE_KEY = 'receiptai_shop_list_v1';

type Summary = {
  receipts: number;
  spent: number;
  saved: number;
};

type Receipt = {
  id?: string | number;
  store?: string;
  date?: string;
  time?: string;
  created_at?: string;
  total?: number;
  items?: unknown[];
};

type ShoppingItem = {
  name?: string;
  checked?: boolean;
};

const numberValue = (value: unknown) => Number.parseFloat(String(value ?? '')) || 0;
const money = (value: unknown) => `$${numberValue(value).toFixed(2)}`;

function displayName(user: ReturnType<typeof useAuth.getState>['user']) {
  if (!user || user.is_guest || user.isGuest) return 'there';
  return user.name?.trim().split(/\s+/)[0] || user.email?.split('@')[0] || 'there';
}

function initial(user: ReturnType<typeof useAuth.getState>['user']) {
  const source = user?.name || user?.email || 'G';
  return source.trim().charAt(0).toUpperCase();
}

function receiptDate(receipt?: Receipt | null) {
  if (!receipt) return '';
  if (receipt.date) return [receipt.date, receipt.time].filter(Boolean).join(' · ');
  if (!receipt.created_at) return '';
  const parsed = new Date(receipt.created_at);
  if (Number.isNaN(parsed.getTime())) return '';
  return parsed.toLocaleDateString(undefined, { month: 'short', day: 'numeric' });
}

export default function HomeScreen() {
  const { user } = useAuth();
  const { colors: C, isDark } = useTheme();
  const s = useMemo(() => createStyles(C, isDark), [C, isDark]);
  const [summary, setSummary] = useState<Summary>({ receipts: 0, spent: 0, saved: 0 });
  const [latestReceipt, setLatestReceipt] = useState<Receipt | null>(null);
  const [shoppingItems, setShoppingItems] = useState<ShoppingItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);

  const loadHome = useCallback(async (refresh = false) => {
    if (!user) return;
    if (refresh) setRefreshing(true);
    else setLoading(true);

    const guestId = getGuestSessionId();
    const token = getUserToken();
    const guestMode = Boolean(guestId || user.is_guest || user.isGuest || token === 'guest');
    const headers: Record<string, string> = {};
    if (!guestMode && token) headers.Authorization = `Bearer ${token}`;
    const sessionId = guestId || user.id;

    try {
      const [summaryResult, receiptsResult, shoppingResult] = await Promise.allSettled([
        fetch(guestMode ? `${API}/summary?session_id=${encodeURIComponent(sessionId)}` : `${API}/summary`, { headers }),
        fetch(guestMode ? `${API}/guest/receipts?session_id=${encodeURIComponent(sessionId)}` : `${API}/receipts`, { headers }),
        AsyncStorage.getItem(`${SHOP_STORAGE_KEY}:${user.id}`),
      ]);

      if (summaryResult.status === 'fulfilled' && summaryResult.value.ok) {
        const data = await summaryResult.value.json();
        setSummary({
          receipts: numberValue(data.total_receipts),
          spent: numberValue(data.total_spent),
          saved: numberValue(data.total_saved),
        });
      }

      if (receiptsResult.status === 'fulfilled' && receiptsResult.value.ok) {
        const data = await receiptsResult.value.json();
        const receipts: Receipt[] = Array.isArray(data.receipts) ? data.receipts : [];
        receipts.sort((a, b) => new Date(b.created_at || b.date || 0).getTime() - new Date(a.created_at || a.date || 0).getTime());
        setLatestReceipt(receipts[0] || null);
      }

      if (shoppingResult.status === 'fulfilled' && shoppingResult.value) {
        const parsed = JSON.parse(shoppingResult.value);
        setShoppingItems(Array.isArray(parsed) ? parsed.filter(item => item?.name) : []);
      } else {
        setShoppingItems([]);
      }
    } catch {
      // Home remains usable offline; each destination performs its own refresh.
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, [user]);

  useFocusEffect(useCallback(() => {
    loadHome();
  }, [loadHome]));

  const remainingItems = shoppingItems.filter(item => !item.checked).length;
  const greeting = new Date().getHours() < 12 ? 'Good morning' : new Date().getHours() < 18 ? 'Good afternoon' : 'Good evening';

  return (
    <SafeAreaView style={s.safe} edges={['top']}>
      <ScrollView
        style={s.screen}
        contentContainerStyle={s.content}
        showsVerticalScrollIndicator={false}
        refreshControl={<RefreshControl refreshing={refreshing} onRefresh={() => loadHome(true)} tintColor={C.accent} />}
      >
        <View style={s.header}>
          <View style={s.wordmark}>
            <View style={s.logoMark}>
              <View style={s.logoBack} />
              <View style={s.logoFront} />
            </View>
            <Text style={s.wordmarkText}>ReceiptAI</Text>
          </View>
          <TouchableOpacity
            style={s.avatar}
            onPress={() => router.push('/profile')}
            accessibilityRole="button"
            accessibilityLabel="Open profile"
            activeOpacity={0.82}
          >
            <Text style={s.avatarText}>{initial(user)}</Text>
          </TouchableOpacity>
        </View>

        <View style={s.intro}>
          <Text style={s.eyebrow}>{greeting}, {displayName(user)}</Text>
          <Text style={s.displayTitle}>Your purchases,{`\n`}beautifully understood.</Text>
          <Text style={s.subtitle}>Capture a receipt once. ReceiptAI organizes it, remembers prices, and helps with the next trip.</Text>
        </View>

        <View style={s.scanHero}>
          <View style={s.glowOne} />
          <View style={s.glowTwo} />
          <View style={s.scanCopy}>
            <Text style={s.scanKicker}>Ready when you are</Text>
            <Text style={s.scanTitle}>Scan a receipt</Text>
            <Text style={s.scanSubtitle}>Camera, gallery, multi-page image or PDF</Text>
          </View>
          <View style={s.receiptPaper}>
            <View style={s.paperLineWide} />
            <View style={s.paperLine} />
            <View style={s.paperLineShort} />
            <Ionicons name="receipt-outline" size={32} color={C.accent} />
          </View>
          <TouchableOpacity
            style={s.scanButton}
            onPress={() => router.push('/')}
            accessibilityRole="button"
            accessibilityLabel="Scan a receipt"
            activeOpacity={0.88}
          >
            <Ionicons name="scan-outline" size={20} color={isDark ? '#17141D' : '#FFFDF8'} />
            <Text style={s.scanButtonText}>Start capture</Text>
          </TouchableOpacity>
        </View>

        <TouchableOpacity
          style={s.shoppingCard}
          onPress={() => router.push('/shop')}
          accessibilityRole="button"
          accessibilityLabel={`Open shopping list with ${remainingItems} remaining items`}
          activeOpacity={0.86}
        >
          <View style={s.shoppingIcon}>
            <Ionicons name="cart-outline" size={23} color={isDark ? '#141820' : '#253018'} />
          </View>
          <View style={s.shoppingCopy}>
            <Text style={s.shoppingKicker}>Shopping list</Text>
            <Text style={s.shoppingTitle}>
              {remainingItems ? `${remainingItems} item${remainingItems === 1 ? '' : 's'} ready for your next trip` : 'Plan your next shopping trip'}
            </Text>
            <Text style={s.shoppingSubtitle}>{remainingItems ? 'Check your price memory before you buy' : 'Build a list with prices beside you'}</Text>
          </View>
          <View style={s.arrowButton}>
            <Ionicons name="arrow-forward" size={17} color="#FFFDF8" />
          </View>
        </TouchableOpacity>

        <View style={s.sectionHeader}>
          <Text style={s.sectionTitle}>Latest activity</Text>
          <TouchableOpacity onPress={() => router.push('/receipts')} activeOpacity={0.75}>
            <Text style={s.sectionAction}>All receipts</Text>
          </TouchableOpacity>
        </View>

        {loading ? (
          <View style={s.loadingRow}>
            <ActivityIndicator color={C.accent} />
            <Text style={s.loadingText}>Loading your latest purchase…</Text>
          </View>
        ) : latestReceipt ? (
          <TouchableOpacity
            style={s.latestCard}
            onPress={() => router.push({ pathname: '/receipts', params: { receiptId: String(latestReceipt.id || '') } })}
            accessibilityRole="button"
            accessibilityLabel={`Open latest receipt from ${latestReceipt.store || 'merchant'}`}
            activeOpacity={0.84}
          >
            <View style={s.latestIcon}>
              <Ionicons name="basket-outline" size={21} color="#FFFDF8" />
            </View>
            <View style={s.latestCopy}>
              <Text style={s.latestStore} numberOfLines={1}>{latestReceipt.store || 'Saved receipt'}</Text>
              <Text style={s.latestMeta} numberOfLines={1}>
                {[receiptDate(latestReceipt), `${latestReceipt.items?.length || 0} items`].filter(Boolean).join(' · ')}
              </Text>
            </View>
            <Text style={s.latestTotal}>{money(latestReceipt.total)}</Text>
            <Ionicons name="chevron-forward" size={17} color={C.text3} />
          </TouchableOpacity>
        ) : (
          <TouchableOpacity style={s.emptyCard} onPress={() => router.push('/')} activeOpacity={0.84}>
            <Ionicons name="receipt-outline" size={22} color={C.accent} />
            <View style={{ flex: 1 }}>
              <Text style={s.emptyTitle}>Your first receipt starts here</Text>
              <Text style={s.emptyText}>Scan one to unlock spending and price memory.</Text>
            </View>
          </TouchableOpacity>
        )}

        <View style={s.statsRow}>
          <TouchableOpacity style={s.stat} onPress={() => router.push('/receipts')} activeOpacity={0.8}>
            <Text style={s.statLabel}>Receipts</Text>
            <Text style={s.statValue}>{summary.receipts}</Text>
          </TouchableOpacity>
          <TouchableOpacity style={s.stat} onPress={() => router.push('/memory')} activeOpacity={0.8}>
            <Text style={s.statLabel}>Recorded</Text>
            <Text style={s.statValue}>{money(summary.spent)}</Text>
          </TouchableOpacity>
          <TouchableOpacity style={s.stat} onPress={() => router.push('/memory')} activeOpacity={0.8}>
            <Text style={s.statLabel}>Saved</Text>
            <Text style={[s.statValue, { color: C.accent3 }]}>{money(summary.saved)}</Text>
          </TouchableOpacity>
        </View>
      </ScrollView>
    </SafeAreaView>
  );
}

const createStyles = (C: any, isDark: boolean) => StyleSheet.create({
  safe: { flex: 1, backgroundColor: C.bg },
  screen: { flex: 1, backgroundColor: C.bg },
  content: { paddingHorizontal: 18, paddingTop: 8, paddingBottom: 30 },
  header: { minHeight: 48, flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between' },
  wordmark: { flexDirection: 'row', alignItems: 'center', gap: 9 },
  wordmarkText: { color: C.text, fontSize: 14, fontWeight: '800', letterSpacing: -0.2 },
  logoMark: { width: 28, height: 28, position: 'relative' },
  logoBack: { position: 'absolute', left: 2, top: 2, width: 17, height: 23, borderRadius: 6, backgroundColor: C.accent, transform: [{ rotate: '-8deg' }] },
  logoFront: { position: 'absolute', right: 1, bottom: 1, width: 17, height: 21, borderRadius: 6, backgroundColor: C.accent3, opacity: 0.82, transform: [{ rotate: '9deg' }] },
  avatar: { width: 42, height: 42, borderRadius: 16, alignItems: 'center', justifyContent: 'center', backgroundColor: C.accent, shadowColor: C.accent, shadowOpacity: 0.22, shadowRadius: 12, shadowOffset: { width: 0, height: 7 }, elevation: 4 },
  avatarText: { color: '#FFFDF8', fontSize: 13, fontWeight: '900' },
  intro: { paddingTop: 22, paddingHorizontal: 2, paddingBottom: 16 },
  eyebrow: { color: C.accent, fontSize: 11, fontWeight: '900', letterSpacing: 1.2, textTransform: 'uppercase', marginBottom: 9 },
  displayTitle: { color: C.text, fontFamily: isDark ? undefined : 'Georgia', fontSize: 36, lineHeight: 39, fontWeight: isDark ? '800' : '400', letterSpacing: -1.3 },
  subtitle: { maxWidth: 330, color: C.text2, fontSize: 13, lineHeight: 19, marginTop: 11 },
  scanHero: { minHeight: 232, overflow: 'hidden', borderRadius: 30, padding: 20, backgroundColor: isDark ? '#171420' : '#EDE8FF', borderWidth: 1, borderColor: isDark ? 'rgba(255,255,255,0.08)' : 'rgba(101,86,243,0.12)', shadowColor: isDark ? '#000' : '#62517A', shadowOpacity: 0.16, shadowRadius: 22, shadowOffset: { width: 0, height: 13 }, elevation: 5 },
  glowOne: { position: 'absolute', width: 190, height: 190, borderRadius: 95, right: -44, top: -55, backgroundColor: C.accent, opacity: isDark ? 0.28 : 0.2 },
  glowTwo: { position: 'absolute', width: 145, height: 145, borderRadius: 73, right: 38, bottom: -70, backgroundColor: C.accent3, opacity: isDark ? 0.24 : 0.22 },
  scanCopy: { maxWidth: '58%', zIndex: 2 },
  scanKicker: { color: isDark ? C.accent3 : C.accent, fontSize: 10, fontWeight: '900', letterSpacing: 1, textTransform: 'uppercase' },
  scanTitle: { color: C.text, fontFamily: isDark ? undefined : 'Georgia', fontSize: 28, lineHeight: 32, fontWeight: isDark ? '800' : '400', marginTop: 7, letterSpacing: -0.7 },
  scanSubtitle: { color: C.text2, fontSize: 11, lineHeight: 16, marginTop: 7 },
  receiptPaper: { position: 'absolute', right: 25, top: 26, width: 103, height: 132, padding: 13, justifyContent: 'flex-end', alignItems: 'center', borderRadius: 10, backgroundColor: isDark ? '#FCF8EF' : '#FFFDF8', transform: [{ rotate: '5deg' }], shadowColor: '#251C31', shadowOpacity: 0.25, shadowRadius: 14, shadowOffset: { width: 0, height: 9 }, elevation: 6 },
  paperLineWide: { position: 'absolute', top: 18, left: 14, right: 14, height: 4, borderRadius: 3, backgroundColor: '#DCD5E7' },
  paperLine: { position: 'absolute', top: 31, left: 14, right: 23, height: 3, borderRadius: 2, backgroundColor: '#E8E2EB' },
  paperLineShort: { position: 'absolute', top: 43, left: 14, width: 45, height: 3, borderRadius: 2, backgroundColor: '#E8E2EB' },
  scanButton: { position: 'absolute', left: 20, bottom: 20, minHeight: 48, flexDirection: 'row', alignItems: 'center', gap: 9, paddingHorizontal: 18, borderRadius: 18, backgroundColor: isDark ? '#F6F1E8' : '#17141D', shadowColor: '#17141D', shadowOpacity: 0.25, shadowRadius: 13, shadowOffset: { width: 0, height: 8 }, elevation: 5 },
  scanButtonText: { color: isDark ? '#17141D' : '#FFFDF8', fontSize: 13, fontWeight: '900' },
  shoppingCard: { minHeight: 94, marginTop: 14, flexDirection: 'row', alignItems: 'center', gap: 12, padding: 14, borderRadius: 24, backgroundColor: isDark ? '#2B2136' : '#3B2850', shadowColor: '#271A35', shadowOpacity: 0.18, shadowRadius: 17, shadowOffset: { width: 0, height: 10 }, elevation: 5 },
  shoppingIcon: { width: 50, height: 50, flexShrink: 0, borderRadius: 18, alignItems: 'center', justifyContent: 'center', backgroundColor: '#C8F37C' },
  shoppingCopy: { flex: 1, minWidth: 0 },
  shoppingKicker: { color: '#CBC3D4', fontSize: 9, fontWeight: '900', letterSpacing: 1, textTransform: 'uppercase' },
  shoppingTitle: { color: '#FFFDF8', fontSize: 13, lineHeight: 17, fontWeight: '900', marginTop: 3 },
  shoppingSubtitle: { color: '#61DDD0', fontSize: 10, lineHeight: 14, marginTop: 3 },
  arrowButton: { width: 32, height: 32, flexShrink: 0, borderRadius: 12, alignItems: 'center', justifyContent: 'center', backgroundColor: 'rgba(255,255,255,0.1)' },
  sectionHeader: { marginTop: 22, marginBottom: 10, flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between' },
  sectionTitle: { color: C.text, fontSize: 14, fontWeight: '900' },
  sectionAction: { color: C.accent, fontSize: 11, fontWeight: '900' },
  latestCard: { minHeight: 72, flexDirection: 'row', alignItems: 'center', gap: 11, padding: 11, borderRadius: 20, backgroundColor: C.card, borderWidth: 1, borderColor: C.border, shadowColor: '#000', shadowOpacity: isDark ? 0.18 : 0.07, shadowRadius: 12, shadowOffset: { width: 0, height: 7 }, elevation: 3 },
  latestIcon: { width: 45, height: 45, flexShrink: 0, borderRadius: 16, alignItems: 'center', justifyContent: 'center', backgroundColor: C.accent },
  latestCopy: { flex: 1, minWidth: 0 },
  latestStore: { color: C.text, fontSize: 13, fontWeight: '900' },
  latestMeta: { color: C.text2, fontSize: 10, marginTop: 4 },
  latestTotal: { color: C.text, fontSize: 14, fontWeight: '900' },
  loadingRow: { minHeight: 72, flexDirection: 'row', alignItems: 'center', gap: 10, paddingHorizontal: 15, borderRadius: 20, backgroundColor: C.card, borderWidth: 1, borderColor: C.border },
  loadingText: { color: C.text2, fontSize: 12 },
  emptyCard: { minHeight: 72, flexDirection: 'row', alignItems: 'center', gap: 12, padding: 14, borderRadius: 20, backgroundColor: C.card, borderWidth: 1, borderColor: C.border },
  emptyTitle: { color: C.text, fontSize: 12, fontWeight: '900' },
  emptyText: { color: C.text2, fontSize: 10, lineHeight: 14, marginTop: 3 },
  statsRow: { flexDirection: 'row', gap: 8, marginTop: 12 },
  stat: { flex: 1, minHeight: 70, padding: 12, borderRadius: 18, backgroundColor: C.card, borderWidth: 1, borderColor: C.border },
  statLabel: { color: C.text3, fontSize: 9, fontWeight: '800', textTransform: 'uppercase', letterSpacing: 0.6 },
  statValue: { color: C.text, fontSize: 16, fontWeight: '900', marginTop: 7 },
});
