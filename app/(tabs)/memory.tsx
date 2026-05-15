import { useCallback, useEffect, useState } from 'react';
import {
  Alert,
  ActivityIndicator,
  RefreshControl,
  ScrollView,
  StyleSheet,
  Text,
  TextInput,
  TouchableOpacity,
  View,
} from 'react-native';
import * as Notifications from 'expo-notifications';
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

type ShoppingPlanItem = {
  item_name: string;
  usual_price: number;
  good_deal_price: number;
  avoid_above_price?: number;
  cheapest_store?: string | null;
  price_range?: number;
};

type ShoppingPlan = {
  plan_items: ShoppingPlanItem[];
  compare_items: ShoppingPlanItem[];
  estimated_total: number;
  estimated_savings: number;
};

type PriceAlert = {
  type: string;
  severity: 'warning' | 'info' | 'tip' | string;
  title: string;
  message: string;
  item_name?: string;
  target_price?: number;
  avoid_above_price?: number;
  store?: string | null;
};

type ReceiptLite = {
  store?: string | null;
  address?: string | null;
  payment_method?: string | null;
  date?: string | null;
  created_at?: string | null;
  total?: number | string | null;
  total_savings?: number | string | null;
  items?: any[];
};

type CategorySpend = {
  key: string;
  label: string;
  total: number;
  receipts: number;
  pct: number;
};

type MonthlySnapshot = {
  label: string;
  total: number;
  receipts: number;
  average: number;
  saved: number;
  topStore: string;
  topStoreTotal: number;
  topStorePct: number;
  previousTotal: number;
  trendPct: number | null;
  topCategory: CategorySpend | null;
  categories: CategorySpend[];
};

type MemoryFilter = 'all' | 'soon' | 'compare' | 'learning';
type MemorySort = 'smart' | 'savings' | 'swing' | 'recent';

const n = (v: any) => Number.parseFloat(v) || 0;
const money = (v: any) => `$${n(v).toFixed(2)}`;
const monthLabel = (key: string) => {
  const [year, month] = key.split('-').map(Number);
  if (!year || !month) return 'This month';
  return new Date(year, month - 1, 1).toLocaleDateString(undefined, { month: 'long', year: 'numeric' });
};
const receiptMonthKey = (receipt: ReceiptLite) => {
  const raw = receipt.date || receipt.created_at || '';
  const parsed = raw ? new Date(raw) : null;
  if (!parsed || Number.isNaN(parsed.getTime())) return '';
  return `${parsed.getFullYear()}-${String(parsed.getMonth() + 1).padStart(2, '0')}`;
};
const receiptSearchText = (receipt: ReceiptLite) => {
  const itemText = (receipt.items || [])
    .map((item:any) => [item?.name, item?.item, item?.code].filter(Boolean).join(' '))
    .join(' ');

  return [
    receipt.store,
    receipt.address,
    receipt.payment_method,
    itemText,
  ].filter(Boolean).join(' ').toLowerCase();
};
const matchAny = (text: string, words: string[]) => words.some(word => text.includes(word));
const receiptCategory = (receipt: ReceiptLite) => {
  const text = receiptSearchText(receipt);
  if (matchAny(text, ['bank', 'atm', 'withdrawal', 'deposit', 'credit union', 'chase', 'wells fargo', 'bank of america', 'capital one', 'payment receipt'])) return { key:'bank', label:'Bank & Finance' };
  if (matchAny(text, ['hospital', 'clinic', 'medical center', 'urgent care', 'doctor', 'dental', 'dentist', 'labcorp', 'quest diagnostics', 'patient'])) return { key:'medical', label:'Hospital & Medical' };
  if (matchAny(text, ['cvs', 'walgreens', 'pharmacy', 'rx ', 'medicine', 'vitamin', 'health'])) return { key:'pharmacy', label:'Pharmacy & Health' };
  if (matchAny(text, ['lowe', 'home depot', 'tractor supply', 'garden', 'mulch', 'soil', 'plant', 'rose', 'fertilizer', 'hardware', 'paint', 'lumber'])) return { key:'garden', label:'Gardening & Hardware' };
  if (matchAny(text, ['restaurant', 'cafe', 'pizza', 'burger', 'taco', 'mcdonald', 'starbucks', 'subway', 'doordash', 'uber eats', 'grubhub'])) return { key:'restaurant', label:'Restaurants' };
  if (matchAny(text, ['walmart', 'kroger', 'aldi', 'costco', 'sam club', 'target grocery', 'supermarket', 'market', 'grocery', 'food', 'seafood', 'milk', 'bread', 'egg'])) return { key:'food', label:'Food & Grocery' };
  if (matchAny(text, ['shell', 'exxon', 'chevron', 'bp ', 'circle k', 'speedway', 'gas', 'fuel', 'auto', 'oil change', 'tire'])) return { key:'fuel', label:'Fuel & Auto' };
  if (matchAny(text, ['ikea', 'bed bath', 'household', 'cleaner', 'detergent', 'furniture', 'kitchen'])) return { key:'home', label:'Home & Household' };
  if (matchAny(text, ['amazon', 'target', 'best buy', 'tj maxx', 'marshalls', 'mall', 'retail'])) return { key:'shopping', label:'Retail Shopping' };
  return { key:'other', label:'Other' };
};

function recommendationLabel(value: string) {
  switch (value) {
    case 'may need soon': return 'May need soon';
    case 'compare before buying': return 'Compare first';
    case 'needs more history': return 'Learning';
    default: return 'Watch price';
  }
}

function dealInsight(item: PriceMemoryItem) {
  const range = n(item.price_range);
  const volatility = n(item.volatility_pct);
  const lowest = n(item.lowest_price);
  const highest = n(item.highest_price);
  const usual = n(item.usual_price);
  const position = range > 0 ? Math.min(1, Math.max(0, (usual - lowest) / range)) : 0.5;

  if (item.recommendation === 'may need soon') {
    return {
      label: 'Buy soon',
      tone: 'good',
      text: `Watch for ${money(item.good_deal_price)} or less${item.cheapest_store ? ` at ${item.cheapest_store}` : ''}.`,
      position,
    };
  }

  if (item.recommendation === 'compare before buying' || range >= 5 || volatility >= 25) {
    return {
      label: 'Price swings',
      tone: 'warn',
      text: `You have paid ${money(lowest)} to ${money(highest)}. Compare before buying again.`,
      position,
    };
  }

  if (item.times_bought <= 1) {
    return {
      label: 'Learning',
      tone: 'neutral',
      text: 'Scan this item again to build a stronger price memory.',
      position,
    };
  }

  return {
    label: 'Stable price',
    tone: 'good',
    text: `Normal price is around ${money(usual)}.`,
    position,
  };
}

function monthlyWatch(snapshot: MonthlySnapshot) {
  const topCategory = snapshot.topCategory?.label || 'your top category';
  const topStore = snapshot.topStore || 'your top store';

  if (snapshot.trendPct !== null && snapshot.trendPct >= 25) {
    return {
      label: 'Spending rising',
      tone: 'warn',
      text: `You are ${snapshot.trendPct.toFixed(0)}% above the previous scanned month. Start with ${topCategory} and ${topStore}.`,
    };
  }

  if (snapshot.trendPct !== null && snapshot.trendPct <= -15) {
    return {
      label: 'Good control',
      tone: 'good',
      text: `You are ${Math.abs(snapshot.trendPct).toFixed(0)}% below the previous scanned month. Keep comparing repeat items before buying.`,
    };
  }

  if (snapshot.topCategory && snapshot.topCategory.pct >= 45) {
    return {
      label: 'Category heavy',
      tone: 'mid',
      text: `${topCategory} is ${snapshot.topCategory.pct.toFixed(0)}% of this month. Check whether repeat items there have better stores or good-deal prices.`,
    };
  }

  if (snapshot.topStorePct >= 50) {
    return {
      label: 'Store concentrated',
      tone: 'mid',
      text: `${topStore} is ${snapshot.topStorePct.toFixed(0)}% of this month. Compare high-swing items before the next trip.`,
    };
  }

  return {
    label: 'Normal pattern',
    tone: 'good',
    text: 'Your spending looks balanced across the receipts scanned so far.',
  };
}

export default function PriceMemoryScreen() {
  const { colors: C } = useTheme();
  const s = createStyles(C);
  const { user } = useAuth();
  const [items, setItems] = useState<PriceMemoryItem[]>([]);
  const [shown, setShown] = useState<PriceMemoryItem[]>([]);
  const [plan, setPlan] = useState<ShoppingPlan | null>(null);
  const [alerts, setAlerts] = useState<PriceAlert[]>([]);
  const [monthly, setMonthly] = useState<MonthlySnapshot | null>(null);
  const [query, setQuery] = useState('');
  const [activeFilter, setActiveFilter] = useState<MemoryFilter>('all');
  const [activeSort, setActiveSort] = useState<MemorySort>('smart');
  const [checkItem, setCheckItem] = useState('');
  const [checkPrice, setCheckPrice] = useState('');
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState('');
  const [scheduledAlerts, setScheduledAlerts] = useState<Record<string, boolean>>({});

  useFocusEffect(useCallback(() => { loadMemory(false); }, [user?.id, user?.guest_session_id]));

  useEffect(() => {
    const q = query.trim().toLowerCase();
    const filtered = items.filter(item => {
      const matchesQuery = !q || [
        item.item_name,
        item.product_size,
        item.cheapest_store,
        item.recommendation,
      ].filter(Boolean).join(' ').toLowerCase().includes(q);

      if (!matchesQuery) return false;
      if (activeFilter === 'soon') return item.recommendation === 'may need soon';
      if (activeFilter === 'compare') return item.recommendation === 'compare before buying';
      if (activeFilter === 'learning') return item.recommendation === 'needs more history' || item.times_bought <= 1;
      return true;
    });

    const sorted = [...filtered].sort((a, b) => {
      if (activeSort === 'savings') {
        return n(b.usual_price) - n(b.good_deal_price) - (n(a.usual_price) - n(a.good_deal_price));
      }
      if (activeSort === 'swing') {
        return n(b.price_range) - n(a.price_range);
      }
      if (activeSort === 'recent') {
        return new Date(b.last_bought_date || 0).getTime() - new Date(a.last_bought_date || 0).getTime();
      }

      const priority = (item: PriceMemoryItem) => {
        if (item.recommendation === 'may need soon') return 4;
        if (item.recommendation === 'compare before buying') return 3;
        if (n(item.price_range) >= 5 || n(item.volatility_pct) >= 25) return 2;
        return 1;
      };
      return priority(b) - priority(a) || n(b.price_range) - n(a.price_range);
    });

    setShown(sorted);
  }, [query, activeFilter, activeSort, items]);

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
      await loadShoppingPlan(headers, isGuest ? (guestId || user.id) : '');
      await loadPriceAlerts(headers, isGuest ? (guestId || user.id) : '', nextItems);
      await loadMonthlySnapshot(headers, isGuest ? (guestId || user.id) : '');
    } catch (e: any) {
      setError(e.message || 'Could not load Price Memory.');
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }

  async function loadShoppingPlan(headers: any, guestId: string) {
    try {
      const url = guestId
        ? `${API}/shopping-plan?session_id=${encodeURIComponent(guestId)}`
        : `${API}/shopping-plan`;
      const res = await fetch(url, { headers });
      const data = await res.json();
      if (res.ok && data.success) {
        setPlan({
          plan_items: data.plan_items || [],
          compare_items: data.compare_items || [],
          estimated_total: n(data.estimated_total),
          estimated_savings: n(data.estimated_savings),
        });
      }
    } catch {
      setPlan(null);
    }
  }

  async function loadPriceAlerts(headers: any, guestId: string, fallbackItems: PriceMemoryItem[]) {
    try {
      const url = guestId
        ? `${API}/price-alerts?session_id=${encodeURIComponent(guestId)}`
        : `${API}/price-alerts`;
      const res = await fetch(url, { headers });
      const data = await res.json();
      if (res.ok && data.success) {
        setAlerts(data.alerts || []);
        return;
      }
    } catch {}

    setAlerts(buildLocalAlerts(fallbackItems));
  }

  async function loadMonthlySnapshot(headers: any, guestId: string) {
    try {
      const url = guestId
        ? `${API}/guest/receipts?session_id=${encodeURIComponent(guestId)}`
        : `${API}/receipts`;
      const res = await fetch(url, { headers });
      const data = await res.json();
      if (!res.ok) throw new Error('Could not load receipts.');
      const receipts: ReceiptLite[] = data.receipts || [];
      const byMonth: Record<string, ReceiptLite[]> = {};

      receipts.forEach(receipt => {
        const key = receiptMonthKey(receipt);
        if (!key) return;
        byMonth[key] = byMonth[key] || [];
        byMonth[key].push(receipt);
      });

      const currentKey = receiptMonthKey({ date: new Date().toISOString() });
      const monthKeys = Object.keys(byMonth).sort();
      const targetKey = byMonth[currentKey] ? currentKey : monthKeys[monthKeys.length - 1];
      if (!targetKey) {
        setMonthly(null);
        return;
      }

      const targetReceipts = byMonth[targetKey] || [];
      const total = targetReceipts.reduce((sum, receipt) => sum + n(receipt.total), 0);
      const saved = targetReceipts.reduce((sum, receipt) => sum + n(receipt.total_savings), 0);
      const storeTotals: Record<string, number> = {};
      const categoryTotals: Record<string, CategorySpend> = {};
      targetReceipts.forEach(receipt => {
        const store = receipt.store || 'Unknown store';
        const totalValue = n(receipt.total);
        const category = receiptCategory(receipt);
        storeTotals[store] = (storeTotals[store] || 0) + totalValue;
        categoryTotals[category.key] = categoryTotals[category.key] || {
          key: category.key,
          label: category.label,
          total: 0,
          receipts: 0,
          pct: 0,
        };
        categoryTotals[category.key].total += totalValue;
        categoryTotals[category.key].receipts += 1;
      });
      const [topStore, topStoreTotal] = Object.entries(storeTotals).sort((a, b) => b[1] - a[1])[0] || ['Unknown store', 0];
      const categories = Object.values(categoryTotals)
        .map(category => ({
          ...category,
          total: n(category.total.toFixed(2)),
          pct: total > 0 ? (category.total / total) * 100 : 0,
        }))
        .sort((a, b) => b.total - a.total);
      const targetIndex = monthKeys.indexOf(targetKey);
      const previousKey = targetIndex > 0 ? monthKeys[targetIndex - 1] : '';
      const previousTotal = (byMonth[previousKey] || []).reduce((sum, receipt) => sum + n(receipt.total), 0);
      const trendPct = previousTotal > 0 ? ((total - previousTotal) / previousTotal) * 100 : null;

      setMonthly({
        label: monthLabel(targetKey),
        total,
        receipts: targetReceipts.length,
        average: targetReceipts.length ? total / targetReceipts.length : 0,
        saved,
        topStore,
        topStoreTotal,
        topStorePct: total > 0 ? (topStoreTotal / total) * 100 : 0,
        previousTotal,
        trendPct,
        topCategory: categories[0] || null,
        categories,
      });
    } catch {
      setMonthly(null);
    }
  }

  function buildLocalAlerts(sourceItems: PriceMemoryItem[]): PriceAlert[] {
    const nextAlerts: PriceAlert[] = [];
    sourceItems.slice(0, 80).forEach(item => {
      if (item.recommendation === 'may need soon') {
        nextAlerts.push({
          type: 'may_need_soon',
          severity: 'info',
          title: `You may need ${item.item_name} soon`,
          message: `Good deal is ${money(item.good_deal_price)}. Usual price is ${money(item.usual_price)}.`,
          item_name: item.item_name,
          target_price: item.good_deal_price,
          store: item.cheapest_store,
        });
      }
      if (n(item.price_range) >= 5 || n(item.volatility_pct) >= 25) {
        nextAlerts.push({
          type: 'price_swing',
          severity: 'warning',
          title: `Compare before buying ${item.item_name}`,
          message: `Your price has ranged from ${money(item.lowest_price)} to ${money(item.highest_price)}.`,
          item_name: item.item_name,
          avoid_above_price: item.avoid_above_price,
          store: item.cheapest_store,
        });
      }
    });
    return nextAlerts.slice(0, 10);
  }

  async function scheduleAlert(alert: PriceAlert) {
    try {
      const permissions = await Notifications.getPermissionsAsync();
      let status = permissions.status;
      if (status !== 'granted') {
        const requested = await Notifications.requestPermissionsAsync();
        status = requested.status;
      }
      if (status !== 'granted') {
        Alert.alert('Notifications disabled', 'Enable notifications to receive shopping reminders.');
        return;
      }

      await Notifications.scheduleNotificationAsync({
        content: {
          title: alert.title,
          body: alert.message,
          data: { type: alert.type, item_name: alert.item_name },
        },
        trigger: {
          type: Notifications.SchedulableTriggerInputTypes.TIME_INTERVAL,
          seconds: 60 * 60 * 24,
        },
      });

      const key = `${alert.type}-${alert.item_name}`;
      setScheduledAlerts(prev => ({ ...prev, [key]: true }));
      Alert.alert('Reminder set', 'I will remind you tomorrow.');
    } catch {
      Alert.alert('Could not set reminder', 'Please try again.');
    }
  }

  const strongItems = items.filter(item => item.recommendation === 'may need soon').length;
  const compareItems = items.filter(item => item.recommendation === 'compare before buying').length;
  const learningItems = items.filter(item => item.recommendation === 'needs more history' || item.times_bought <= 1).length;
  const filterChips: { key: MemoryFilter; label: string; count: number }[] = [
    { key: 'all', label: 'All', count: items.length },
    { key: 'soon', label: 'Need soon', count: strongItems },
    { key: 'compare', label: 'Compare', count: compareItems },
    { key: 'learning', label: 'Learning', count: learningItems },
  ];
  const sortChips: { key: MemorySort; label: string }[] = [
    { key: 'smart', label: 'Smart order' },
    { key: 'savings', label: 'Best savings' },
    { key: 'swing', label: 'Biggest swing' },
    { key: 'recent', label: 'Recent' },
  ];
  const localNextPlan = items.filter(item => item.recommendation === 'may need soon').slice(0, 5);
  const localComparePlan = items
    .filter(item => item.recommendation === 'compare before buying')
    .sort((a, b) => n(b.price_range) - n(a.price_range))
    .slice(0, 4);
  const nextPlan = plan?.plan_items?.length ? plan.plan_items : localNextPlan;
  const comparePlan = plan?.compare_items?.length ? plan.compare_items : localComparePlan;
  const planTotal = plan ? plan.estimated_total : nextPlan.reduce((sum, item) => sum + n(item.usual_price), 0);
  const planSavings = plan ? plan.estimated_savings : 0;
  const avgAvoid = items.length
    ? items.reduce((sum, item) => sum + n(item.avoid_above_price), 0) / items.length
    : 0;
  const checkMatch = checkItem.trim()
    ? items
        .map(item => ({
          item,
          score: item.item_name.toLowerCase().includes(checkItem.trim().toLowerCase()) ? 2 : 0,
        }))
        .filter(row => row.score > 0)
        .sort((a, b) => b.score - a.score)[0]?.item
    : null;
  const currentPrice = n(checkPrice);
  const checkDecision = checkMatch && currentPrice > 0
    ? currentPrice <= n(checkMatch.good_deal_price)
      ? { label:'Buy', tone:'good', text:`This is at or below your good-deal price of ${money(checkMatch.good_deal_price)}.` }
      : currentPrice >= n(checkMatch.avoid_above_price)
        ? { label:'Compare', tone:'bad', text:`This is above your avoid-above price of ${money(checkMatch.avoid_above_price)}.` }
        : { label:'Normal', tone:'mid', text:`This is near your usual price of ${money(checkMatch.usual_price)}.` }
    : null;
  const watch = monthly ? monthlyWatch(monthly) : null;

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

        {monthly ? (
          <View style={s.monthBox}>
            <View style={s.planHeader}>
              <View>
                <Text style={s.monthKicker}>Monthly Snapshot</Text>
                <Text style={s.planTitle}>{monthly.label}</Text>
              </View>
              <View style={s.monthTotalPill}>
                <Text style={s.monthTotalTxt}>{money(monthly.total)}</Text>
              </View>
            </View>

            <View style={s.monthGrid}>
              <View style={s.monthMetric}>
                <Text style={s.monthMetricVal}>{monthly.receipts}</Text>
                <Text style={s.monthMetricLbl}>Receipts</Text>
              </View>
              <View style={s.monthMetric}>
                <Text style={s.monthMetricVal}>{money(monthly.average)}</Text>
                <Text style={s.monthMetricLbl}>Avg trip</Text>
              </View>
              <View style={s.monthMetric}>
                <Text style={[s.monthMetricVal, { color: C.green }]}>{money(monthly.saved)}</Text>
                <Text style={s.monthMetricLbl}>Saved</Text>
              </View>
            </View>

            <View style={s.monthStoreRow}>
              <View style={{ flex: 1 }}>
                <Text style={s.monthStoreLabel}>Top store</Text>
                <Text style={s.monthStoreName} numberOfLines={1}>{monthly.topStore}</Text>
              </View>
              <Text style={s.monthStoreTotal}>{money(monthly.topStoreTotal)}</Text>
            </View>
            <View style={s.monthTrack}>
              <View style={[s.monthTrackFill, { width: `${Math.min(100, Math.round(monthly.topStorePct))}%` }]} />
            </View>
            <Text style={s.monthHint}>
              {monthly.trendPct === null
                ? 'This is your first month with enough scanned receipt history.'
                : `${Math.abs(monthly.trendPct).toFixed(0)}% ${monthly.trendPct >= 0 ? 'higher' : 'lower'} than the previous scanned month.`}
            </Text>

            {watch ? (
              <View style={[
                s.watchBox,
                watch.tone === 'good' && s.watchGood,
                watch.tone === 'warn' && s.watchWarn,
                watch.tone === 'mid' && s.watchMid,
              ]}>
                <Text style={s.watchLabel}>{watch.label}</Text>
                <Text style={s.watchText}>{watch.text}</Text>
              </View>
            ) : null}

            {monthly.categories.length > 0 ? (
              <View style={s.categoryBlock}>
                <View style={s.categoryHeader}>
                  <Text style={s.categoryTitle}>Category breakdown</Text>
                  {monthly.topCategory ? (
                    <Text style={s.categoryTop} numberOfLines={1}>
                      Top: {monthly.topCategory.label}
                    </Text>
                  ) : null}
                </View>
                {monthly.categories.slice(0, 4).map(category => (
                  <View key={category.key} style={s.categoryRow}>
                    <View style={{ flex:1 }}>
                      <View style={s.categoryLine}>
                        <Text style={s.categoryName}>{category.label}</Text>
                        <Text style={s.categoryAmount}>{money(category.total)}</Text>
                      </View>
                      <View style={s.categoryTrack}>
                        <View style={[s.categoryFill, { width: `${Math.min(100, Math.round(category.pct))}%` }]} />
                      </View>
                      <Text style={s.categoryMeta}>
                        {category.receipts} receipt{category.receipts === 1 ? '' : 's'} · {category.pct.toFixed(0)}%
                      </Text>
                    </View>
                  </View>
                ))}
              </View>
            ) : null}
          </View>
        ) : null}

        {items.length > 0 ? (
          <View style={s.planBox}>
            <View style={s.planHeader}>
              <View>
                <Text style={s.planKicker}>Next Purchase Assistant</Text>
                <Text style={s.planTitle}>Smart shopping plan</Text>
              </View>
              <View style={s.planTotalPill}>
                <Text style={s.planTotalTxt}>{money(planTotal)}</Text>
              </View>
            </View>

            {planSavings > 0 ? (
              <Text style={s.planSavings}>Good-deal target could save about {money(planSavings)}.</Text>
            ) : null}

            {nextPlan.length > 0 ? (
              <View style={s.planSection}>
                <Text style={s.planSectionTitle}>May need soon</Text>
                {nextPlan.map((item, index) => (
                  <View key={`${item.item_name}-soon-${index}`} style={s.planRow}>
                    <View style={{ flex: 1 }}>
                      <Text style={s.planItem} numberOfLines={1}>{item.item_name}</Text>
                      <Text style={s.planMeta}>
                        Usual {money(item.usual_price)} · good deal {money(item.good_deal_price)}
                      </Text>
                    </View>
                    <Text style={s.planStore} numberOfLines={1}>{item.cheapest_store || 'Store?'}</Text>
                  </View>
                ))}
              </View>
            ) : (
              <Text style={s.planEmpty}>No repeat item looks due yet. Keep scanning and this will get smarter.</Text>
            )}

            {comparePlan.length > 0 ? (
              <View style={s.planSection}>
                <Text style={s.planSectionTitle}>Compare before buying</Text>
                {comparePlan.map((item, index) => (
                  <View key={`${item.item_name}-compare-${index}`} style={s.compareRow}>
                    <Text style={s.compareItem} numberOfLines={1}>{item.item_name}</Text>
                    <Text style={s.compareRange}>{money(item.price_range)} swing</Text>
                  </View>
                ))}
              </View>
            ) : null}
          </View>
        ) : null}

        {alerts.length > 0 ? (
          <View style={s.alertBox}>
            <View style={s.planHeader}>
              <View>
                <Text style={s.alertKicker}>Price Alerts</Text>
                <Text style={s.planTitle}>Watch before buying</Text>
              </View>
              <View style={s.alertCountPill}>
                <Text style={s.alertCountTxt}>{alerts.length}</Text>
              </View>
            </View>
            {alerts.slice(0, 5).map((alert, index) => {
              const alertKey = `${alert.type}-${alert.item_name}`;
              const scheduled = scheduledAlerts[alertKey];
              return (
                <View key={`${alertKey}-${index}`} style={s.alertRow}>
                  <View style={[
                    s.alertDot,
                    alert.severity === 'warning' && { backgroundColor: C.gold },
                    alert.severity === 'info' && { backgroundColor: C.accent },
                    alert.severity === 'tip' && { backgroundColor: C.green },
                  ]} />
                  <View style={{ flex:1 }}>
                    <Text style={s.alertTitle}>{alert.title}</Text>
                    <Text style={s.alertMsg}>{alert.message}</Text>
                    {alert.store ? <Text style={s.alertStore}>Best known store: {alert.store}</Text> : null}
                  </View>
                  <TouchableOpacity
                    style={[s.remindBtn, scheduled && s.remindBtnDone]}
                    onPress={() => scheduleAlert(alert)}
                    disabled={scheduled}
                    activeOpacity={0.8}
                  >
                    <Text style={[s.remindTxt, scheduled && s.remindTxtDone]}>
                      {scheduled ? 'Set' : 'Remind'}
                    </Text>
                  </TouchableOpacity>
                </View>
              );
            })}
          </View>
        ) : null}

        {items.length > 0 ? (
          <View style={s.checkBox}>
            <Text style={s.planKicker}>Before You Buy</Text>
            <Text style={s.checkTitle}>Check today's price</Text>
            <View style={s.checkInputs}>
              <TextInput
                style={[s.search, { flex: 1.4, marginBottom: 0 }]}
                value={checkItem}
                onChangeText={setCheckItem}
                placeholder="Item name"
                placeholderTextColor={C.text3}
                autoCorrect={false}
              />
              <TextInput
                style={[s.search, { flex: 0.8, marginBottom: 0 }]}
                value={checkPrice}
                onChangeText={setCheckPrice}
                placeholder="$ price"
                placeholderTextColor={C.text3}
                keyboardType="decimal-pad"
              />
            </View>

            {checkDecision && checkMatch ? (
              <View style={[
                s.decisionBox,
                checkDecision.tone === 'good' && s.decisionGood,
                checkDecision.tone === 'bad' && s.decisionBad,
                checkDecision.tone === 'mid' && s.decisionMid,
              ]}>
                <View style={s.decisionTop}>
                  <Text style={s.decisionLabel}>{checkDecision.label}</Text>
                  <Text style={s.decisionPrice}>{money(currentPrice)}</Text>
                </View>
                <Text style={s.decisionText}>{checkDecision.text}</Text>
                <Text style={s.decisionSub} numberOfLines={2}>
                  Matched: {checkMatch.item_name} · lowest {money(checkMatch.lowest_price)} · highest {money(checkMatch.highest_price)}
                </Text>
              </View>
            ) : checkItem.trim() && checkPrice.trim() ? (
              <Text style={s.noMatchText}>No matching Price Memory item found yet.</Text>
            ) : null}
          </View>
        ) : null}

        {items.length > 0 ? (
          <>
            <ScrollView
              horizontal
              showsHorizontalScrollIndicator={false}
              contentContainerStyle={s.filterRow}
              keyboardShouldPersistTaps="handled"
            >
              {filterChips.map(chip => {
                const selected = activeFilter === chip.key;
                return (
                  <TouchableOpacity
                    key={chip.key}
                    style={[s.filterChip, selected && s.filterChipActive]}
                    onPress={() => setActiveFilter(chip.key)}
                    activeOpacity={0.82}
                  >
                    <Text style={[s.filterTxt, selected && s.filterTxtActive]}>{chip.label}</Text>
                    <Text style={[s.filterCount, selected && s.filterCountActive]}>{chip.count}</Text>
                  </TouchableOpacity>
                );
              })}
            </ScrollView>

            <ScrollView
              horizontal
              showsHorizontalScrollIndicator={false}
              contentContainerStyle={s.sortRow}
              keyboardShouldPersistTaps="handled"
            >
              {sortChips.map(chip => {
                const selected = activeSort === chip.key;
                return (
                  <TouchableOpacity
                    key={chip.key}
                    style={[s.sortChip, selected && s.sortChipActive]}
                    onPress={() => setActiveSort(chip.key)}
                    activeOpacity={0.82}
                  >
                    <Text style={[s.sortTxt, selected && s.sortTxtActive]}>{chip.label}</Text>
                  </TouchableOpacity>
                );
              })}
            </ScrollView>
          </>
        ) : null}

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
            {shown.map((item, index) => {
              const insight = dealInsight(item);
              return (
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

                <View style={s.insightBox}>
                  <View style={s.insightTop}>
                    <Text style={[
                      s.insightLabel,
                      insight.tone === 'good' && { color: C.green },
                      insight.tone === 'warn' && { color: C.gold },
                    ]}>
                      {insight.label}
                    </Text>
                    <Text style={s.insightMini}>usual price</Text>
                  </View>
                  <View style={s.priceTrack}>
                    <View style={[s.priceMarker, { left: `${Math.round(insight.position * 100)}%` }]} />
                  </View>
                  <View style={s.trackLabels}>
                    <Text style={s.trackText}>{money(item.lowest_price)}</Text>
                    <Text style={s.trackText}>{money(item.highest_price)}</Text>
                  </View>
                  <Text style={s.insightText}>{insight.text}</Text>
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
              );
            })}
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
  monthBox:{ backgroundColor:C.surface, borderWidth:1, borderColor:C.border, borderRadius:14, padding:14, marginBottom:14 },
  monthKicker:{ color:C.accent, fontSize:10, fontWeight:'800', textTransform:'uppercase', letterSpacing:0.5, marginBottom:3 },
  monthTotalPill:{ backgroundColor:'rgba(124,106,255,0.12)', borderWidth:1, borderColor:'rgba(124,106,255,0.26)', borderRadius:12, paddingHorizontal:10, paddingVertical:7 },
  monthTotalTxt:{ color:C.accent, fontWeight:'900', fontSize:13 },
  monthGrid:{ flexDirection:'row', gap:8, marginBottom:12 },
  monthMetric:{ flex:1, backgroundColor:C.surface2, borderWidth:1, borderColor:C.border, borderRadius:12, padding:10 },
  monthMetricVal:{ color:C.text, fontSize:15, fontWeight:'900' },
  monthMetricLbl:{ color:C.text3, fontSize:10, marginTop:3, fontWeight:'700' },
  monthStoreRow:{ flexDirection:'row', alignItems:'center', justifyContent:'space-between', gap:10, marginBottom:7 },
  monthStoreLabel:{ color:C.text3, fontSize:10, fontWeight:'800', textTransform:'uppercase', letterSpacing:0.5, marginBottom:2 },
  monthStoreName:{ color:C.text, fontSize:13, fontWeight:'900' },
  monthStoreTotal:{ color:C.gold, fontSize:13, fontWeight:'900' },
  monthTrack:{ height:8, borderRadius:99, backgroundColor:C.surface2, overflow:'hidden', borderWidth:1, borderColor:C.border },
  monthTrackFill:{ height:'100%', borderRadius:99, backgroundColor:C.gold },
  monthHint:{ color:C.text2, fontSize:11, lineHeight:16, marginTop:8 },
  watchBox:{ marginTop:10, borderWidth:1, borderRadius:12, padding:11 },
  watchGood:{ backgroundColor:'rgba(74,222,128,0.09)', borderColor:'rgba(74,222,128,0.24)' },
  watchWarn:{ backgroundColor:'rgba(255,107,107,0.08)', borderColor:'rgba(255,107,107,0.24)' },
  watchMid:{ backgroundColor:'rgba(251,191,36,0.08)', borderColor:'rgba(251,191,36,0.24)' },
  watchLabel:{ color:C.text, fontSize:13, fontWeight:'900', marginBottom:4 },
  watchText:{ color:C.text2, fontSize:12, lineHeight:17 },
  categoryBlock:{ marginTop:12, borderTopWidth:1, borderTopColor:C.border, paddingTop:12 },
  categoryHeader:{ flexDirection:'row', alignItems:'center', justifyContent:'space-between', gap:10, marginBottom:8 },
  categoryTitle:{ color:C.text, fontSize:13, fontWeight:'900' },
  categoryTop:{ color:C.accent, fontSize:11, fontWeight:'800', maxWidth:170 },
  categoryRow:{ paddingVertical:6 },
  categoryLine:{ flexDirection:'row', alignItems:'center', justifyContent:'space-between', gap:10, marginBottom:5 },
  categoryName:{ color:C.text2, fontSize:12, fontWeight:'800', flex:1 },
  categoryAmount:{ color:C.text, fontSize:12, fontWeight:'900' },
  categoryTrack:{ height:6, borderRadius:99, backgroundColor:C.surface2, overflow:'hidden' },
  categoryFill:{ height:'100%', borderRadius:99, backgroundColor:C.accent },
  categoryMeta:{ color:C.text3, fontSize:10, marginTop:4, fontWeight:'700' },
  planBox:{ backgroundColor:C.surface, borderWidth:1, borderColor:C.border, borderRadius:14, padding:14, marginBottom:14 },
  planHeader:{ flexDirection:'row', justifyContent:'space-between', alignItems:'flex-start', gap:12, marginBottom:12 },
  planKicker:{ color:C.green, fontSize:10, fontWeight:'800', textTransform:'uppercase', letterSpacing:0.5, marginBottom:3 },
  planTitle:{ color:C.text, fontSize:18, fontWeight:'900' },
  planTotalPill:{ backgroundColor:'rgba(74,222,128,0.10)', borderWidth:1, borderColor:'rgba(74,222,128,0.24)', borderRadius:12, paddingHorizontal:10, paddingVertical:7 },
  planTotalTxt:{ color:C.green, fontWeight:'900', fontSize:13 },
  planSavings:{ color:C.green, fontSize:12, lineHeight:17, marginBottom:4 },
  planSection:{ marginTop:8 },
  planSectionTitle:{ color:C.text3, fontSize:10, fontWeight:'800', textTransform:'uppercase', letterSpacing:0.6, marginBottom:8 },
  planRow:{ flexDirection:'row', alignItems:'center', gap:10, paddingVertical:8, borderTopWidth:1, borderTopColor:C.border },
  planItem:{ color:C.text, fontSize:13, fontWeight:'800' },
  planMeta:{ color:C.text2, fontSize:11, marginTop:2 },
  planStore:{ color:C.accent, fontSize:11, fontWeight:'800', maxWidth:110 },
  planEmpty:{ color:C.text2, fontSize:12, lineHeight:17 },
  compareRow:{ flexDirection:'row', alignItems:'center', justifyContent:'space-between', gap:10, paddingVertical:7, borderTopWidth:1, borderTopColor:C.border },
  compareItem:{ color:C.text2, fontSize:12, flex:1 },
  compareRange:{ color:C.gold, fontSize:11, fontWeight:'900' },
  alertBox:{ backgroundColor:C.surface, borderWidth:1, borderColor:C.border, borderRadius:14, padding:14, marginBottom:14 },
  alertKicker:{ color:C.gold, fontSize:10, fontWeight:'800', textTransform:'uppercase', letterSpacing:0.5, marginBottom:3 },
  alertCountPill:{ backgroundColor:'rgba(251,191,36,0.10)', borderWidth:1, borderColor:'rgba(251,191,36,0.24)', borderRadius:12, minWidth:34, paddingHorizontal:10, paddingVertical:7, alignItems:'center' },
  alertCountTxt:{ color:C.gold, fontWeight:'900', fontSize:13 },
  alertRow:{ flexDirection:'row', alignItems:'flex-start', gap:10, paddingVertical:10, borderTopWidth:1, borderTopColor:C.border },
  alertDot:{ width:9, height:9, borderRadius:5, backgroundColor:C.accent, marginTop:4 },
  alertTitle:{ color:C.text, fontSize:13, fontWeight:'900', lineHeight:18 },
  alertMsg:{ color:C.text2, fontSize:12, lineHeight:17, marginTop:2 },
  alertStore:{ color:C.accent, fontSize:11, fontWeight:'800', marginTop:4 },
  remindBtn:{ backgroundColor:C.surface2, borderWidth:1, borderColor:C.border, borderRadius:10, paddingHorizontal:10, paddingVertical:7, marginTop:1 },
  remindBtnDone:{ backgroundColor:'rgba(74,222,128,0.10)', borderColor:'rgba(74,222,128,0.24)' },
  remindTxt:{ color:C.accent, fontSize:11, fontWeight:'900' },
  remindTxtDone:{ color:C.green },
  checkBox:{ backgroundColor:C.surface, borderWidth:1, borderColor:C.border, borderRadius:14, padding:14, marginBottom:14 },
  checkTitle:{ color:C.text, fontSize:18, fontWeight:'900', marginBottom:10 },
  checkInputs:{ flexDirection:'row', gap:8 },
  decisionBox:{ marginTop:12, borderWidth:1, borderRadius:12, padding:12 },
  decisionGood:{ backgroundColor:'rgba(74,222,128,0.10)', borderColor:'rgba(74,222,128,0.28)' },
  decisionBad:{ backgroundColor:'rgba(255,107,107,0.09)', borderColor:'rgba(255,107,107,0.28)' },
  decisionMid:{ backgroundColor:'rgba(251,191,36,0.09)', borderColor:'rgba(251,191,36,0.28)' },
  decisionTop:{ flexDirection:'row', alignItems:'center', justifyContent:'space-between', gap:10, marginBottom:6 },
  decisionLabel:{ color:C.text, fontSize:18, fontWeight:'900' },
  decisionPrice:{ color:C.accent, fontSize:16, fontWeight:'900' },
  decisionText:{ color:C.text, fontSize:13, lineHeight:18 },
  decisionSub:{ color:C.text2, fontSize:11, marginTop:6, lineHeight:16 },
  noMatchText:{ color:C.text2, fontSize:12, marginTop:10 },
  filterRow:{ gap:8, paddingBottom:10 },
  filterChip:{ flexDirection:'row', alignItems:'center', gap:7, backgroundColor:C.surface, borderWidth:1, borderColor:C.border, borderRadius:99, paddingHorizontal:12, paddingVertical:8 },
  filterChipActive:{ backgroundColor:'rgba(124,106,255,0.14)', borderColor:'rgba(124,106,255,0.38)' },
  filterTxt:{ color:C.text2, fontSize:12, fontWeight:'800' },
  filterTxtActive:{ color:C.text },
  filterCount:{ color:C.text3, fontSize:11, fontWeight:'900' },
  filterCountActive:{ color:C.accent },
  sortRow:{ gap:8, paddingBottom:12 },
  sortChip:{ backgroundColor:C.surface2, borderWidth:1, borderColor:C.border, borderRadius:9, paddingHorizontal:11, paddingVertical:7 },
  sortChipActive:{ backgroundColor:'rgba(74,222,128,0.10)', borderColor:'rgba(74,222,128,0.28)' },
  sortTxt:{ color:C.text2, fontSize:11, fontWeight:'800' },
  sortTxtActive:{ color:C.green },
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
  insightBox:{ marginTop:10, backgroundColor:C.surface2, borderRadius:12, padding:11, borderWidth:1, borderColor:C.border },
  insightTop:{ flexDirection:'row', alignItems:'center', justifyContent:'space-between', gap:8, marginBottom:8 },
  insightLabel:{ color:C.text, fontSize:12, fontWeight:'900' },
  insightMini:{ color:C.text3, fontSize:10, fontWeight:'700' },
  priceTrack:{ height:7, borderRadius:99, backgroundColor:C.border, overflow:'visible', marginHorizontal:4 },
  priceMarker:{ position:'absolute', top:-4, width:4, height:15, borderRadius:99, backgroundColor:C.accent },
  trackLabels:{ flexDirection:'row', justifyContent:'space-between', marginTop:6 },
  trackText:{ color:C.text3, fontSize:10, fontWeight:'700' },
  insightText:{ color:C.text2, fontSize:11, lineHeight:16, marginTop:7 },
  rangeRow:{ marginTop:10, gap:4 },
  rangeText:{ color:C.text2, fontSize:11, lineHeight:15 },
  footerNote:{ marginTop:14, backgroundColor:'rgba(74,222,128,0.08)', borderWidth:1, borderColor:'rgba(74,222,128,0.22)', borderRadius:12, padding:12 },
  footerText:{ color:C.green, fontSize:12, lineHeight:17, textAlign:'center' },
});
