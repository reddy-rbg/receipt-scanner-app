import { useCallback, useEffect, useRef, useState } from 'react';
import {
  Alert,
  ActivityIndicator,
  KeyboardAvoidingView,
  Platform,
  RefreshControl,
  Share,
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
  dailyPace: number;
  projectedTotal: number;
  daysRemaining: number;
  suggestedTarget: number;
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
type MemoryView = 'today' | 'spending' | 'items' | 'more';

const n = (v: any) => Number.parseFloat(v) || 0;
const money = (v: any) => `$${n(v).toFixed(2)}`;
const parseReceiptDate = (value: any) => {
  const raw = String(value || '').trim();
  if (!raw) return null;

  const shortDate = raw.match(/^(\d{1,2})[/-](\d{1,2})[/-](\d{2})$/);
  const parsed = shortDate
    ? new Date(2000 + Number(shortDate[3]), Number(shortDate[1]) - 1, Number(shortDate[2]))
    : new Date(raw);

  if (Number.isNaN(parsed.getTime())) return null;
  const year = parsed.getFullYear();
  const nextYear = new Date().getFullYear() + 1;
  if (year < 2020 || year > nextYear) return null;
  return parsed;
};
const monthLabel = (key: string) => {
  const [year, month] = key.split('-').map(Number);
  if (!year || !month) return 'This month';
  return new Date(year, month - 1, 1).toLocaleDateString(undefined, { month: 'long', year: 'numeric' });
};
const receiptMonthKey = (receipt: ReceiptLite) => {
  const parsed = parseReceiptDate(receipt.date) || parseReceiptDate(receipt.created_at);
  if (!parsed || Number.isNaN(parsed.getTime())) return '';
  return `${parsed.getFullYear()}-${String(parsed.getMonth() + 1).padStart(2, '0')}`;
};
const receiptDateValue = (receipt: ReceiptLite) => {
  const parsed = parseReceiptDate(receipt.date) || parseReceiptDate(receipt.created_at);
  return parsed && !Number.isNaN(parsed.getTime()) ? parsed : null;
};
const daysInMonthKey = (key: string) => {
  const [year, month] = key.split('-').map(Number);
  if (!year || !month) return 30;
  return new Date(year, month, 0).getDate();
};
const normalizeSearchText = (value: any) => String(value || '')
  .toLowerCase()
  .replace(/[^a-z0-9]+/g, ' ')
  .replace(/\s+/g, ' ')
  .trim();
const searchTokens = (value: any) => normalizeSearchText(value)
  .split(' ')
  .filter(token => token.length >= 2);
const fuzzyScore = (query: string, target: string) => {
  const q = normalizeSearchText(query);
  const t = normalizeSearchText(target);
  if (!q || !t) return 0;
  if (t.includes(q)) return 100;

  const qTokens = searchTokens(q);
  const tTokens = searchTokens(t);
  if (!qTokens.length || !tTokens.length) return 0;

  let score = 0;
  qTokens.forEach(qToken => {
    const best = Math.max(...tTokens.map(tToken => {
      if (tToken === qToken) return 24;
      if (tToken.startsWith(qToken) || qToken.startsWith(tToken)) return 18;
      if (tToken.length >= 4 && qToken.length >= 4 && tToken.slice(0, 4) === qToken.slice(0, 4)) return 14;
      if (tToken.includes(qToken) || qToken.includes(tToken)) return 10;
      return 0;
    }));
    score += best;
  });

  return score / qTokens.length;
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
const returnWindowDays = (categoryKey: string) => {
  if (categoryKey === 'garden' || categoryKey === 'home') return 90;
  if (categoryKey === 'shopping') return 30;
  if (categoryKey === 'pharmacy' || categoryKey === 'medical' || categoryKey === 'bank') return 0;
  if (categoryKey === 'food' || categoryKey === 'restaurant') return 7;
  return 30;
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

function itemConfidence(item: PriceMemoryItem) {
  if (item.times_bought >= 4 && n(item.price_range) > 0) {
    return { label: 'Strong', tone: 'good', text: `${item.times_bought} buys` };
  }
  if (item.times_bought >= 2) {
    return { label: 'Growing', tone: 'mid', text: `${item.times_bought} buys` };
  }
  return { label: 'Learning', tone: 'low', text: '1 buy' };
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

function monthlyReportText(snapshot: MonthlySnapshot, watch: ReturnType<typeof monthlyWatch>) {
  const categoryLines = snapshot.categories
    .slice(0, 4)
    .map(category => `- ${category.label}: ${money(category.total)} (${category.pct.toFixed(0)}%)`)
    .join('\n');

  return [
    `ReceiptAI Monthly Snapshot - ${snapshot.label}`,
    '',
    `Total spent: ${money(snapshot.total)}`,
    `Projected month end: ${money(snapshot.projectedTotal)}`,
    `Receipts: ${snapshot.receipts}`,
    `Average trip: ${money(snapshot.average)}`,
    `Daily pace: ${money(snapshot.dailyPace)}`,
    `Savings found: ${money(snapshot.saved)}`,
    `Top store: ${snapshot.topStore} (${money(snapshot.topStoreTotal)})`,
    snapshot.topCategory ? `Top category: ${snapshot.topCategory.label} (${money(snapshot.topCategory.total)})` : '',
    '',
    `Spending watch: ${watch.label}`,
    watch.text,
    categoryLines ? `\nCategory breakdown:\n${categoryLines}` : '',
  ].filter(Boolean).join('\n');
}

export default function PriceMemoryScreen() {
  const { colors: C } = useTheme();
  const s = createStyles(C);
  const { user } = useAuth();
  const scrollRef = useRef<ScrollView | null>(null);
  const [items, setItems] = useState<PriceMemoryItem[]>([]);
  const [shown, setShown] = useState<PriceMemoryItem[]>([]);
  const [plan, setPlan] = useState<ShoppingPlan | null>(null);
  const [alerts, setAlerts] = useState<PriceAlert[]>([]);
  const [monthly, setMonthly] = useState<MonthlySnapshot | null>(null);
  const [recentReceipts, setRecentReceipts] = useState<ReceiptLite[]>([]);
  const [query, setQuery] = useState('');
  const [activeFilter, setActiveFilter] = useState<MemoryFilter>('all');
  const [activeSort, setActiveSort] = useState<MemorySort>('smart');
  const [activeView, setActiveView] = useState<MemoryView>('today');
  const [checkItem, setCheckItem] = useState('');
  const [checkPrice, setCheckPrice] = useState('');
  const [liveCheck, setLiveCheck] = useState<any>(null);
  const [liveChecking, setLiveChecking] = useState(false);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState('');
  const [scheduledAlerts, setScheduledAlerts] = useState<Record<string, boolean>>({});
  const [autoAlertEnabled, setAutoAlertEnabled] = useState(false);

  const keepBeforeBuyVisible = () => {
    setTimeout(() => scrollRef.current?.scrollToEnd({ animated: true }), 280);
  };

  useFocusEffect(useCallback(() => { loadMemory(false); }, [user?.id, user?.guest_session_id]));

  useEffect(() => {
    const q = query.trim();
    const filtered = items.filter(item => {
      const searchable = [
        item.item_name,
        item.product_size,
        item.cheapest_store,
        item.recommendation,
      ].filter(Boolean).join(' ');
      const matchesQuery = !q || fuzzyScore(q, searchable) >= 12;

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

  async function runLivePriceCheck() {
    if (!checkItem.trim() || !n(checkPrice)) {
      Alert.alert('Enter item and price', 'Add the item name and today’s price to compare it with your receipts.');
      return;
    }
    if (!user) return;

    setLiveChecking(true);
    setLiveCheck(null);
    try {
      const token = getUserToken();
      const guestId = getGuestSessionId();
      const isGuest = !!guestId || user.is_guest || user.isGuest || token === 'guest';
      const headers: any = { 'Content-Type': 'application/json' };
      if (!isGuest && token) headers.Authorization = `Bearer ${token}`;
      const res = await fetch(`${API}/live-price-check`, {
        method: 'POST',
        headers,
        body: JSON.stringify({
          item_name: checkItem,
          current_price: n(checkPrice),
          session_id: isGuest ? (guestId || user.id) : undefined,
        }),
      });
      const data = await res.json();
      if (!res.ok || data.success === false) {
        throw new Error(data.detail || data.message || 'Could not compare this price.');
      }
      setLiveCheck(data);
    } catch (e: any) {
      Alert.alert('Live price check failed', e.message || 'Please try again.');
    } finally {
      setLiveChecking(false);
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
      setRecentReceipts(receipts);
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
      const now = new Date();
      const isCurrentMonth = targetKey === currentKey;
      const daysInMonth = daysInMonthKey(targetKey);
      const elapsedDays = isCurrentMonth ? Math.max(1, now.getDate()) : daysInMonth;
      const daysRemaining = isCurrentMonth ? Math.max(0, daysInMonth - now.getDate()) : 0;
      const dailyPace = total / elapsedDays;
      const projectedTotal = isCurrentMonth ? dailyPace * daysInMonth : total;
      const suggestedTarget = previousTotal > 0
        ? Math.max(total, previousTotal)
        : Math.max(total, projectedTotal * 0.9);

      setMonthly({
        label: monthLabel(targetKey),
        total,
        receipts: targetReceipts.length,
        average: targetReceipts.length ? total / targetReceipts.length : 0,
        saved,
        dailyPace,
        projectedTotal,
        daysRemaining,
        suggestedTarget,
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

  async function scheduleTopAlerts() {
    const topAlerts = alerts.slice(0, 5);
    if (!topAlerts.length) {
      Alert.alert('No alerts yet', 'Price Memory needs more repeat purchases before it can schedule alerts.');
      return;
    }

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

      for (const alert of topAlerts) {
        await Notifications.scheduleNotificationAsync({
          content: {
            title: alert.title,
            body: alert.message,
            data: { type: alert.type, item_name: alert.item_name },
          },
          trigger: {
            type: Notifications.SchedulableTriggerInputTypes.TIME_INTERVAL,
            seconds: alert.severity === 'warning' ? 60 * 60 * 12 : 60 * 60 * 24,
          },
        });
      }

      setScheduledAlerts(prev => {
        const next = { ...prev };
        topAlerts.forEach(alert => { next[`${alert.type}-${alert.item_name}`] = true; });
        return next;
      });
      setAutoAlertEnabled(true);
      Alert.alert('Smart alerts enabled', `Scheduled ${topAlerts.length} shopping reminder${topAlerts.length === 1 ? '' : 's'}.`);
    } catch {
      Alert.alert('Could not enable alerts', 'Please try again.');
    }
  }

  async function shareMonthlyReport() {
    if (!monthly || !watch) return;
    try {
      await Share.share({
        title: `ReceiptAI ${monthly.label} report`,
        message: monthlyReportText(monthly, watch),
      });
    } catch {
      Alert.alert('Could not share report', 'Please try again.');
    }
  }

  async function shareHouseholdBrief() {
    const lines = [
      'ReceiptAI household shopping brief',
      '',
      actionCards.length ? 'This week:' : '',
      ...actionCards.map((action, index) => `${index + 1}. ${action.label}: ${action.title} - ${action.text}`),
      storeTripPlan.length ? '\nBest store plan:' : '',
      ...storeTripPlan.map(store => `${store.store}: ${store.items.slice(0, 3).map(item => item.item_name).join(', ')}`),
      returnWatch.length ? '\nReturn/warranty watch:' : '',
      ...returnWatch.map(row => `${row.store}: ${money(row.total)} - ${row.daysLeft} day${row.daysLeft === 1 ? '' : 's'} left`),
    ].filter(Boolean);

    try {
      await Share.share({
        title: 'ReceiptAI household shopping brief',
        message: lines.join('\n'),
      });
    } catch {
      Alert.alert('Could not share brief', 'Please try again.');
    }
  }

  const strongItems = items.filter(item => item.recommendation === 'may need soon').length;
  const compareItems = items.filter(item => item.recommendation === 'compare before buying').length;
  const learningItems = items.filter(item => item.recommendation === 'needs more history' || item.times_bought <= 1).length;
  const confidentItems = items.filter(item => item.times_bought >= 2 && n(item.price_range) > 0).length;
  const confidencePct = items.length ? Math.round((confidentItems / items.length) * 100) : 0;
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
  const savingsOpportunities = items
    .map(item => ({
      item,
      perBuy: Math.max(0, n(item.usual_price) - n(item.good_deal_price)),
      swing: n(item.price_range),
      repeatWeight: Math.min(4, Math.max(1, n(item.times_bought))),
    }))
    .filter(row => row.perBuy > 0.25 || row.swing >= 2)
    .sort((a, b) => (b.perBuy * b.repeatWeight + b.swing * 0.2) - (a.perBuy * a.repeatWeight + a.swing * 0.2))
    .slice(0, 4);
  const totalOpportunity = savingsOpportunities.reduce((sum, row) => sum + row.perBuy, 0);
  const compareRiskPct = items.length ? Math.round((compareItems / items.length) * 100) : 0;
  const opportunityBoost = Math.min(20, Math.round(totalOpportunity * 2));
  const healthScore = items.length
    ? Math.max(5, Math.min(100, Math.round(confidencePct * 0.65 + (100 - compareRiskPct) * 0.25 + opportunityBoost)))
    : 0;
  const healthLabel = healthScore >= 75 ? 'Healthy' : healthScore >= 45 ? 'Needs attention' : 'Learning mode';
  const storeIntelligence = Object.values(items.reduce((acc, item) => {
    const store = item.cheapest_store?.trim();
    if (!store) return acc;
    acc[store] = acc[store] || { store, items: 0, opportunity: 0, bestItem: '' };
    const opportunity = Math.max(0, n(item.usual_price) - n(item.good_deal_price));
    acc[store].items += 1;
    acc[store].opportunity += opportunity;
    if (!acc[store].bestItem || opportunity > acc[store].opportunity / Math.max(1, acc[store].items)) {
      acc[store].bestItem = item.item_name;
    }
    return acc;
  }, {} as Record<string, { store: string; items: number; opportunity: number; bestItem: string }>))
    .sort((a, b) => b.items - a.items || b.opportunity - a.opportunity)
    .slice(0, 4);
  const loyaltySignals = storeIntelligence
    .map(store => {
      const avgOpportunity = store.items ? store.opportunity / store.items : 0;
      const status = store.items >= 3 && avgOpportunity >= 1
        ? 'Good loyalty'
        : store.items >= 2
          ? 'Useful store'
          : 'Watch list';
      const advice = status === 'Good loyalty'
        ? `This store often wins on tracked items. Start here for ${store.bestItem || 'repeat purchases'}.`
        : status === 'Useful store'
          ? `Good for some items, but compare prices before a bigger trip.`
          : `Needs more scanned history before trusting it as a go-to store.`;
      return { ...store, avgOpportunity, status, advice };
    })
    .slice(0, 3);
  const nextPlan = plan?.plan_items?.length ? plan.plan_items : localNextPlan;
  const comparePlan = plan?.compare_items?.length ? plan.compare_items : localComparePlan;
  const storeTripPlan = Object.values([...nextPlan, ...comparePlan].reduce((acc, item) => {
    const store = item.cheapest_store?.trim() || 'Compare nearby stores';
    const key = normalizeSearchText(`${store}-${item.item_name}`);
    if (acc.seen[key]) return acc;
    acc.seen[key] = true;
    acc.stores[store] = acc.stores[store] || { store, items: [] as ShoppingPlanItem[], total: 0 };
    acc.stores[store].items.push(item);
    acc.stores[store].total += n(item.good_deal_price || item.usual_price);
    return acc;
  }, { stores: {} as Record<string, { store: string; items: ShoppingPlanItem[]; total: number }>, seen: {} as Record<string, boolean> }).stores)
    .sort((a, b) => b.items.length - a.items.length || b.total - a.total)
    .slice(0, 3);
  const learningQueue = items
    .filter(item => item.times_bought <= 1 || item.recommendation === 'needs more history')
    .sort((a, b) => n(b.usual_price) - n(a.usual_price))
    .slice(0, 4);
  const planTotal = plan ? plan.estimated_total : nextPlan.reduce((sum, item) => sum + n(item.usual_price), 0);
  const planSavings = plan ? plan.estimated_savings : 0;
  const avgAvoid = items.length
    ? items.reduce((sum, item) => sum + n(item.avoid_above_price), 0) / items.length
    : 0;
  const checkMatch = checkItem.trim()
    ? items
        .map(item => ({
          item,
          score: fuzzyScore(checkItem, [
            item.item_name,
            item.product_size,
            item.cheapest_store,
          ].filter(Boolean).join(' ')),
        }))
        .filter(row => row.score >= 12)
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
  const actionCards = [
    nextPlan[0] ? {
      label: 'Buy soon',
      title: nextPlan[0].item_name,
      text: `Look for ${money(nextPlan[0].good_deal_price)} or less${nextPlan[0].cheapest_store ? ` at ${nextPlan[0].cheapest_store}` : ''}.`,
      tone: 'good',
    } : null,
    comparePlan[0] ? {
      label: 'Compare',
      title: comparePlan[0].item_name,
      text: `Price swings about ${money(comparePlan[0].price_range)}. Check another store before buying.`,
      tone: 'warn',
    } : null,
    savingsOpportunities[0] ? {
      label: 'Save more',
      title: savingsOpportunities[0].item.item_name,
      text: `Best opportunity is about ${money(savingsOpportunities[0].perBuy)} per buy.`,
      tone: 'good',
    } : null,
    watch && watch.tone === 'warn' ? {
      label: 'Slow down',
      title: 'Monthly pace',
      text: watch.text,
      tone: 'bad',
    } : null,
  ].filter(Boolean).slice(0, 3) as { label: string; title: string; text: string; tone: string }[];
  const smartQuestions = [
    savingsOpportunities[0] ? `How can I save on ${savingsOpportunities[0].item.item_name}?` : '',
    storeIntelligence[0] ? `What should I buy at ${storeIntelligence[0].store}?` : '',
    comparePlan[0] ? `Where did I buy ${comparePlan[0].item_name} cheapest?` : '',
    monthly ? `Explain my ${monthly.label} spending in simple terms` : '',
  ].filter(Boolean).slice(0, 4);
  const priceDoctor = learningItems > confidentItems
    ? {
      label: 'Build more memory',
      text: `${learningItems} items need another scan before their price advice becomes reliable.`,
      fix: learningQueue[0] ? `Next useful scan: ${learningQueue[0].item_name}.` : 'Scan repeat purchases first.',
      tone: 'mid',
    }
    : compareItems > Math.max(1, strongItems)
      ? {
        label: 'Too many price swings',
        text: `${compareItems} items should be compared before buying again.`,
        fix: comparePlan[0] ? `Start with ${comparePlan[0].item_name}.` : 'Use the compare filter before shopping.',
        tone: 'warn',
      }
      : savingsOpportunities[0]
        ? {
          label: 'Savings available',
          text: `The clearest saving is ${money(savingsOpportunities[0].perBuy)} per buy.`,
          fix: `Watch ${savingsOpportunities[0].item.item_name} for ${money(savingsOpportunities[0].item.good_deal_price)} or less.`,
          tone: 'good',
        }
        : {
          label: 'Looking balanced',
          text: 'No major price issue stands out from the receipts scanned.',
          fix: 'Keep scanning repeat purchases to improve confidence.',
          tone: 'good',
        };
  const dataQualityFlags = [
    items.some(item => !item.cheapest_store) ? {
      label: 'Missing stores',
      text: `${items.filter(item => !item.cheapest_store).length} item${items.filter(item => !item.cheapest_store).length === 1 ? '' : 's'} do not have a cheapest store yet.`,
    } : null,
    items.some(item => n(item.usual_price) <= 0 || n(item.good_deal_price) <= 0) ? {
      label: 'Missing prices',
      text: `${items.filter(item => n(item.usual_price) <= 0 || n(item.good_deal_price) <= 0).length} item${items.filter(item => n(item.usual_price) <= 0 || n(item.good_deal_price) <= 0).length === 1 ? '' : 's'} need cleaner price data.`,
    } : null,
    items.some(item => n(item.volatility_pct) >= 75 || n(item.price_range) >= 25) ? {
      label: 'High swings',
      text: `${items.filter(item => n(item.volatility_pct) >= 75 || n(item.price_range) >= 25).length} item${items.filter(item => n(item.volatility_pct) >= 75 || n(item.price_range) >= 25).length === 1 ? '' : 's'} have unusually wide price ranges.`,
    } : null,
  ].filter(Boolean).slice(0, 3) as { label: string; text: string }[];
  const budgetGuardrail = monthly ? {
    remaining: Math.max(0, monthly.suggestedTarget - monthly.total),
    overTarget: Math.max(0, monthly.total - monthly.suggestedTarget),
    dailyRoom: Math.max(0, (monthly.suggestedTarget - monthly.total) / Math.max(1, monthly.daysRemaining || 1)),
    progressPct: monthly.suggestedTarget > 0 ? Math.min(100, Math.round((monthly.total / monthly.suggestedTarget) * 100)) : 0,
  } : null;
  const receiptCoverage = monthly ? {
    elapsedDays: Math.max(1, daysInMonthKey(receiptMonthKey({ date: new Date().toISOString() })) - monthly.daysRemaining),
    receiptsPerWeek: monthly.receipts / Math.max(1, Math.max(1, daysInMonthKey(receiptMonthKey({ date: new Date().toISOString() })) - monthly.daysRemaining) / 7),
    score: Math.min(100, Math.round((monthly.receipts / Math.max(3, Math.max(1, daysInMonthKey(receiptMonthKey({ date: new Date().toISOString() })) - monthly.daysRemaining) / 3)) * 100)),
  } : null;
  const coverageLabel = receiptCoverage
    ? receiptCoverage.score >= 75 ? 'Good coverage' : receiptCoverage.score >= 40 ? 'Partial coverage' : 'Thin coverage'
    : '';
  const spendPattern = monthly ? {
    storeConcentration: Math.round(monthly.topStorePct),
    categoryConcentration: monthly.topCategory ? Math.round(monthly.topCategory.pct) : 0,
    label: monthly.topStorePct >= 55
      ? 'Store-heavy month'
      : monthly.topCategory && monthly.topCategory.pct >= 45
        ? 'Category-heavy month'
        : 'Balanced spread',
    insight: monthly.topStorePct >= 55
      ? `${monthly.topStore} holds ${Math.round(monthly.topStorePct)}% of this scanned month. Price-check the biggest items before your next trip.`
      : monthly.topCategory && monthly.topCategory.pct >= 45
        ? `${monthly.topCategory.label} is ${Math.round(monthly.topCategory.pct)}% of this scanned month. Review that category first for savings.`
        : 'Spending is spread across stores and categories, so focus on repeat items with price swings.',
    focus: monthly.topCategory?.label || monthly.topStore || 'Repeat purchases',
  } : null;
  const categoryAdvice = monthly?.categories
    .slice(0, 4)
    .map(category => {
      const advice = category.key === 'food'
        ? 'Check repeat staples and compare weekly grocery trips.'
        : category.key === 'garden'
          ? 'Watch seasonal items and keep receipts for returns.'
          : category.key === 'medical' || category.key === 'pharmacy'
            ? 'Track reimbursement, HSA/FSA, and recurring medicine costs.'
            : category.key === 'bank'
              ? 'Keep for proof, but exclude from shopping savings decisions.'
              : category.key === 'restaurant'
                ? 'Limit repeat dining spikes before the month-end forecast rises.'
                : category.key === 'fuel'
                  ? 'Compare station patterns and refill before high-price routes.'
                  : category.key === 'shopping'
                    ? 'Check return windows and avoid impulse repeat buys.'
                    : 'Review the largest receipt and look for repeat items.';
      const tone = category.pct >= 45 ? 'high' : category.pct >= 25 ? 'mid' : 'low';
      return { ...category, advice, tone };
    }) || [];
  const today = new Date();
  const returnWatch = recentReceipts
    .map(receipt => {
      const date = receiptDateValue(receipt);
      const category = receiptCategory(receipt);
      const windowDays = returnWindowDays(category.key);
      if (!date || !windowDays) return null;
      const ageDays = Math.floor((today.getTime() - date.getTime()) / (1000 * 60 * 60 * 24));
      const daysLeft = windowDays - ageDays;
      if (daysLeft < 0 || daysLeft > 30) return null;
      return {
        store: receipt.store || 'Unknown store',
        category: category.label,
        total: n(receipt.total),
        date: date.toLocaleDateString(undefined, { month: 'short', day: 'numeric' }),
        daysLeft,
        windowDays,
      };
    })
    .filter((row): row is { store: string; category: string; total: number; date: string; daysLeft: number; windowDays: number } => !!row)
    .sort((a, b) => a.daysLeft - b.daysLeft)
    .slice(0, 4);
  const marketEdgeItems = items
    .filter(item => item.times_bought >= 2 && (n(item.price_range) > 0 || n(item.volatility_pct) > 0))
    .map(item => {
      const range = Math.max(0, n(item.highest_price) - n(item.lowest_price));
      const avoidGap = Math.max(0, n(item.avoid_above_price) - n(item.good_deal_price));
      const riskScore = range * Math.min(4, item.times_bought) + n(item.volatility_pct) * 0.15 + avoidGap;
      const markerPct = range > 0
        ? Math.min(100, Math.max(0, ((n(item.usual_price) - n(item.lowest_price)) / range) * 100))
        : 50;
      return {
        item,
        riskScore,
        markerPct,
        action: item.recommendation === 'may need soon'
          ? 'Buy only near deal'
          : item.recommendation === 'compare before buying'
            ? 'Compare first'
            : 'Watch normal price',
      };
    })
    .sort((a, b) => b.riskScore - a.riskScore)
    .slice(0, 5);
  const rhythmItems = items
    .filter(item => item.times_bought >= 2 && (item.buy_frequency_days || item.next_expected_date || item.last_bought_date))
    .map(item => {
      const nextDate = item.next_expected_date ? new Date(item.next_expected_date) : null;
      const lastDate = item.last_bought_date ? new Date(item.last_bought_date) : null;
      const hasNext = nextDate && !Number.isNaN(nextDate.getTime());
      const hasLast = lastDate && !Number.isNaN(lastDate.getTime());
      const daysUntil = hasNext ? Math.ceil((nextDate.getTime() - today.getTime()) / (1000 * 60 * 60 * 24)) : null;
      const daysSince = hasLast ? Math.floor((today.getTime() - lastDate.getTime()) / (1000 * 60 * 60 * 24)) : null;
      const frequency = n(item.buy_frequency_days);
      const urgency = daysUntil === null
        ? frequency > 0 && daysSince !== null ? daysSince / frequency : 0
        : daysUntil <= 0 ? 3 : daysUntil <= 7 ? 2 : 1;
      return {
        item,
        daysUntil,
        daysSince,
        frequency,
        urgency,
        label: daysUntil !== null && daysUntil <= 0
          ? 'Likely due'
          : daysUntil !== null && daysUntil <= 7
            ? 'Coming soon'
            : 'Recurring',
      };
    })
    .sort((a, b) => b.urgency - a.urgency || n(b.item.price_range) - n(a.item.price_range))
    .slice(0, 4);
  const noBuyItems = items
    .filter(item => n(item.avoid_above_price) > 0 && (n(item.price_range) >= 3 || n(item.volatility_pct) >= 25))
    .sort((a, b) => n(b.avoid_above_price) - n(a.avoid_above_price))
    .slice(0, 4);
  const receiptAnomalies = recentReceipts
    .map(receipt => {
      const category = receiptCategory(receipt);
      const total = n(receipt.total);
      const categoryAvg = monthly?.categories.find(row => row.key === category.key);
      const avgReceipt = categoryAvg && categoryAvg.receipts ? categoryAvg.total / categoryAvg.receipts : monthly?.average || 0;
      const ratio = avgReceipt > 0 ? total / avgReceipt : 0;
      const date = receiptDateValue(receipt);
      if (ratio < 1.35 && total < 50) return null;
      return {
        store: receipt.store || 'Unknown store',
        category: category.label,
        total,
        ratio,
        date: date ? date.toLocaleDateString(undefined, { month: 'short', day: 'numeric' }) : 'Recent',
        reason: ratio >= 1.35 ? `${Math.round((ratio - 1) * 100)}% above category average` : 'High-value receipt',
      };
    })
    .filter((row): row is { store: string; category: string; total: number; ratio: number; date: string; reason: string } => !!row)
    .sort((a, b) => b.ratio - a.ratio || b.total - a.total)
    .slice(0, 4);
  const basketBuilder = [
    ...rhythmItems.slice(0, 2).map(row => ({
      item_name: row.item.item_name,
      store: row.item.cheapest_store || 'Best known store',
      price: n(row.item.good_deal_price || row.item.usual_price),
      reason: row.label,
    })),
    ...savingsOpportunities.slice(0, 2).map(row => ({
      item_name: row.item.item_name,
      store: row.item.cheapest_store || 'Compare nearby stores',
      price: n(row.item.good_deal_price || row.item.usual_price),
      reason: `Save ${money(row.perBuy)}`,
    })),
  ]
    .filter((row, index, rows) => rows.findIndex(item => normalizeSearchText(item.item_name) === normalizeSearchText(row.item_name)) === index)
    .slice(0, 4);
  const basketTotal = basketBuilder.reduce((sum, row) => sum + row.price, 0);
  const savingsMission = {
    target: Math.max(5, Math.round((totalOpportunity + noBuyItems.reduce((sum, item) => sum + Math.max(0, n(item.avoid_above_price) - n(item.good_deal_price)), 0)) * 100) / 100),
    steps: [
      savingsOpportunities[0] ? `Buy ${savingsOpportunities[0].item.item_name} only near ${money(savingsOpportunities[0].item.good_deal_price)}.` : '',
      noBuyItems[0] ? `Avoid ${noBuyItems[0].item_name} above ${money(noBuyItems[0].avoid_above_price)}.` : '',
      storeTripPlan[0] ? `Start the next trip at ${storeTripPlan[0].store}.` : '',
    ].filter(Boolean).slice(0, 3),
  };
  const aiBrief = items.length ? {
    title: healthScore >= 75
      ? 'Your shopping memory is strong'
      : compareItems > strongItems
        ? 'Compare before the next trip'
        : learningItems > confidentItems
          ? 'Keep building repeat history'
          : 'You have useful buying signals',
    primary: actionCards[0]?.text || priceDoctor.fix,
    secondary: monthly
      ? `${monthly.label}: ${money(monthly.total)} scanned, projected ${money(monthly.projectedTotal)}.`
      : `${items.length} tracked items with ${confidentItems} repeat price histories.`,
    focus: [
      savingsMission.steps[0] || '',
      receiptAnomalies[0] ? `Review ${receiptAnomalies[0].store} receipt for ${money(receiptAnomalies[0].total)}.` : '',
      basketBuilder[0] ? `Next cart starts with ${basketBuilder[0].item_name}.` : '',
    ].filter(Boolean).slice(0, 3),
  } : null;
  const actionScoreboard = [
    { label:'Save target', value:money(savingsMission.target), tone:'good' },
    { label:'Avoid above', value:noBuyItems.length ? money(noBuyItems[0].avoid_above_price) : money(avgAvoid), tone:'bad' },
    { label:'Next basket', value:basketBuilder.length ? money(basketTotal) : money(planTotal), tone:'mid' },
  ];
  const showOverview = activeView === 'more';
  const showMonthly = activeView === 'spending';
  const showShopping = activeView === 'today';
  const showInsights = activeView === 'more';
  const showItems = activeView === 'items';
  const showMore = activeView === 'more';
  const shoppingContentCount = [
    actionCards.length,
    savingsMission.steps.length,
    noBuyItems.length,
    storeTripPlan.length,
    returnWatch.length,
    receiptAnomalies.length,
    rhythmItems.length,
    basketBuilder.length,
    savingsOpportunities.length,
    alerts.length,
  ].filter(Boolean).length;
  const insightContentCount = [
    storeIntelligence.length,
    loyaltySignals.length,
    marketEdgeItems.length,
    learningQueue.length,
    dataQualityFlags.length,
  ].filter(Boolean).length;
  const monthlyContentCount = monthly ? 1 + monthly.categories.length : 0;
  const viewChips: { key: MemoryView; label: string; count: number }[] = [
    { key: 'today', label: 'Today', count: Math.max(1, Math.min(5, shoppingContentCount)) },
    { key: 'spending', label: 'Spending', count: monthlyContentCount },
    { key: 'items', label: 'Items', count: items.length },
    { key: 'more', label: 'More', count: insightContentCount + dataQualityFlags.length + 2 },
  ];
  const tabEmpty = !loading && !error && items.length > 0
    ? activeView === 'spending' && monthlyContentCount === 0
      ? { title:'No monthly snapshot yet', text:'Scan receipts with dates and totals to build monthly spend analysis.' }
      : activeView === 'today' && shoppingContentCount === 0
        ? { title:'No shopping actions yet', text:'Repeat purchases create buy-soon, avoid-above, and basket suggestions.' }
        : activeView === 'more' && insightContentCount === 0
          ? { title:'No advanced insights yet', text:'More repeat items will unlock store loyalty, price radar, and learning signals.' }
          : null
    : null;

  return (
    <View style={s.screen}>
      <KeyboardAvoidingView
        style={s.keyboardWrap}
        behavior={Platform.OS === 'ios' ? 'padding' : 'height'}
        keyboardVerticalOffset={Platform.OS === 'ios' ? 86 : 0}
      >
      <ScrollView
        ref={scrollRef}
        contentContainerStyle={s.content}
        refreshControl={<RefreshControl refreshing={refreshing} onRefresh={() => loadMemory(true)} tintColor={C.accent} />}
        showsVerticalScrollIndicator={false}
        keyboardShouldPersistTaps="handled"
        keyboardDismissMode={Platform.OS === 'ios' ? 'interactive' : 'on-drag'}
      >
        <View style={s.hero}>
          <Text style={s.heroKicker}>See what matters now</Text>
          <Text style={s.heroTitle}>Price Memory</Text>
          <Text style={s.heroSub}>Quick buy, save, and spending signals from your real receipt prices.</Text>
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

        {aiBrief ? (
          <View style={s.briefBox}>
            <Text style={s.briefKicker}>Today</Text>
            <Text style={s.briefTitle}>{aiBrief.title}</Text>
            <Text style={s.briefPrimary}>{aiBrief.primary}</Text>
            <Text style={s.briefSecondary}>{aiBrief.secondary}</Text>
            {aiBrief.focus.length > 0 ? (
              <View style={s.briefFocus}>
                {aiBrief.focus.map((line, index) => (
                  <View key={`${line}-${index}`} style={s.briefFocusRow}>
                    <Text style={s.briefFocusNo}>{index + 1}</Text>
                    <Text style={s.briefFocusText}>{line}</Text>
                  </View>
                ))}
              </View>
            ) : null}
          </View>
        ) : null}

        {false && items.length > 0 ? (
          <View style={s.scoreBox}>
            {actionScoreboard.map(score => (
              <View key={score.label} style={s.scoreItem}>
                <Text style={[
                  s.scoreValue,
                  score.tone === 'good' && { color:C.green },
                  score.tone === 'bad' && { color:C.red },
                  score.tone === 'mid' && { color:C.accent },
                ]}>{score.value}</Text>
                <Text style={s.scoreLabel}>{score.label}</Text>
              </View>
            ))}
          </View>
        ) : null}

        {items.length > 0 ? (
          <ScrollView
            horizontal
            showsHorizontalScrollIndicator={false}
            contentContainerStyle={s.viewRow}
            keyboardShouldPersistTaps="handled"
          >
            {viewChips.map(chip => {
              const selected = activeView === chip.key;
              return (
                <TouchableOpacity
                  key={chip.key}
                  style={[s.viewChip, selected && s.viewChipActive]}
                  onPress={() => setActiveView(chip.key)}
                  activeOpacity={0.82}
                >
                  <Text style={[s.viewTxt, selected && s.viewTxtActive]}>{chip.label}</Text>
                  <Text style={[s.viewCount, selected && s.viewCountActive]}>{chip.count}</Text>
                </TouchableOpacity>
              );
            })}
          </ScrollView>
        ) : null}

        {showOverview && items.length > 0 ? (
          <View style={s.healthBox}>
            <View style={s.healthTop}>
              <View>
                <Text style={s.healthKicker}>Price Health Score</Text>
                <Text style={s.healthTitle}>{healthLabel}</Text>
              </View>
              <Text style={[
                s.healthScore,
                healthScore >= 75 && { color:C.green },
                healthScore < 45 && { color:C.gold },
              ]}>{healthScore}</Text>
            </View>
            <View style={s.healthTrack}>
              <View style={[
                s.healthFill,
                { width: `${healthScore}%` },
                healthScore >= 75 && { backgroundColor:C.green },
                healthScore < 45 && { backgroundColor:C.gold },
              ]} />
            </View>
            <View style={s.healthParts}>
              <Text style={s.healthPart}>Confidence {confidencePct}%</Text>
              <Text style={s.healthPart}>Compare risk {compareRiskPct}%</Text>
              <Text style={s.healthPart}>Opportunity {money(totalOpportunity)}</Text>
            </View>
          </View>
        ) : null}

        {showOverview && items.length > 0 ? (
          <View style={[
            s.doctorBox,
            priceDoctor.tone === 'good' && s.doctorGood,
            priceDoctor.tone === 'warn' && s.doctorWarn,
            priceDoctor.tone === 'mid' && s.doctorMid,
          ]}>
            <Text style={s.doctorKicker}>Price Doctor</Text>
            <Text style={s.doctorTitle}>{priceDoctor.label}</Text>
            <Text style={s.doctorText}>{priceDoctor.text}</Text>
            <Text style={s.doctorFix}>{priceDoctor.fix}</Text>
          </View>
        ) : null}

        {(showOverview || showInsights) && dataQualityFlags.length > 0 ? (
          <View style={s.qualityBox}>
            <View style={s.planHeader}>
              <View>
                <Text style={s.qualityKicker}>Data Quality Flags</Text>
                <Text style={s.planTitle}>Review signals</Text>
              </View>
              <View style={s.qualityPill}>
                <Text style={s.qualityPillTxt}>{dataQualityFlags.length}</Text>
              </View>
            </View>
            {dataQualityFlags.map((flag, index) => (
              <View key={`${flag.label}-${index}`} style={s.qualityRow}>
                <Text style={s.qualityLabel}>{flag.label}</Text>
                <Text style={s.qualityText}>{flag.text}</Text>
              </View>
            ))}
          </View>
        ) : null}

        {showOverview && smartQuestions.length > 0 ? (
          <View style={s.questionsBox}>
            <View style={s.planHeader}>
              <View>
                <Text style={s.questionsKicker}>Smart Questions</Text>
                <Text style={s.planTitle}>Ask the Agent next</Text>
              </View>
            </View>
            <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={s.questionsRow}>
              {smartQuestions.map((question, index) => (
                <TouchableOpacity
                  key={`${question}-${index}`}
                  style={s.questionChip}
                  onPress={() => setCheckItem(question)}
                  activeOpacity={0.82}
                >
                  <Text style={s.questionTxt}>{question}</Text>
                </TouchableOpacity>
              ))}
            </ScrollView>
          </View>
        ) : null}

        {showOverview && items.length > 0 ? (
          <View style={s.confidenceBox}>
            <View style={s.confidenceTop}>
              <View>
                <Text style={s.confidenceKicker}>Price Confidence</Text>
                <Text style={s.confidenceTitle}>
                  {confidencePct >= 60 ? 'Strong memory' : confidencePct >= 30 ? 'Growing memory' : 'Still learning'}
                </Text>
              </View>
              <Text style={s.confidencePct}>{confidencePct}%</Text>
            </View>
            <View style={s.confidenceTrack}>
              <View style={[s.confidenceFill, { width: `${confidencePct}%` }]} />
            </View>
            <View style={s.confidenceStats}>
              <Text style={s.confidenceText}>{confidentItems} repeat item{confidentItems === 1 ? '' : 's'} with price history</Text>
              <Text style={s.confidenceText}>{learningItems} still learning</Text>
            </View>
          </View>
        ) : null}

        {showMonthly && monthly ? (
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

            <View style={s.forecastBox}>
              <View style={s.forecastTop}>
                <View>
                  <Text style={s.forecastKicker}>Month-end forecast</Text>
                  <Text style={s.forecastValue}>{money(monthly.projectedTotal)}</Text>
                </View>
                <View style={s.forecastPill}>
                  <Text style={s.forecastPillTxt}>{monthly.daysRemaining} days left</Text>
                </View>
              </View>
              <View style={s.forecastGrid}>
                <View>
                  <Text style={s.forecastLbl}>Daily pace</Text>
                  <Text style={s.forecastSub}>{money(monthly.dailyPace)}</Text>
                </View>
                <View>
                  <Text style={s.forecastLbl}>Suggested target</Text>
                  <Text style={s.forecastSub}>{money(monthly.suggestedTarget)}</Text>
                </View>
              </View>
              <Text style={s.forecastHint}>
                {monthly.projectedTotal > monthly.suggestedTarget
                  ? `To stay near target, slow the pace by about ${money((monthly.projectedTotal - monthly.suggestedTarget) / Math.max(1, monthly.daysRemaining || 1))} per remaining day.`
                  : 'Current pace is within the suggested monthly target.'}
              </Text>
            </View>

            {receiptCoverage ? (
              <View style={s.coverageBox}>
                <View style={s.coverageTop}>
                  <View>
                    <Text style={s.coverageKicker}>Receipt Coverage</Text>
                    <Text style={s.coverageTitle}>{coverageLabel}</Text>
                  </View>
                  <Text style={[
                    s.coverageScore,
                    receiptCoverage.score >= 75 && { color:C.green },
                    receiptCoverage.score < 40 && { color:C.gold },
                  ]}>{receiptCoverage.score}%</Text>
                </View>
                <View style={s.coverageTrack}>
                  <View style={[
                    s.coverageFill,
                    { width: `${receiptCoverage.score}%` },
                    receiptCoverage.score >= 75 && { backgroundColor:C.green },
                    receiptCoverage.score < 40 && { backgroundColor:C.gold },
                  ]} />
                </View>
                <Text style={s.coverageText}>
                  {monthly.receipts} receipt{monthly.receipts === 1 ? '' : 's'} across {receiptCoverage.elapsedDays} day{receiptCoverage.elapsedDays === 1 ? '' : 's'} this month. Forecast gets better as more purchases are scanned.
                </Text>
              </View>
            ) : null}

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

            <TouchableOpacity style={s.shareReportBtn} onPress={shareMonthlyReport} activeOpacity={0.82}>
              <Text style={s.shareReportTxt}>Share monthly report</Text>
            </TouchableOpacity>

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

        {showMonthly && spendPattern ? (
          <View style={s.patternBox}>
            <View style={s.planHeader}>
              <View>
                <Text style={s.patternKicker}>Spend Pattern</Text>
                <Text style={s.planTitle}>{spendPattern.label}</Text>
              </View>
              <View style={s.patternPill}>
                <Text style={s.patternPillTxt}>{spendPattern.storeConcentration}%</Text>
              </View>
            </View>
            <Text style={s.patternText}>{spendPattern.insight}</Text>
            <View style={s.patternGrid}>
              <View style={s.patternMetric}>
                <Text style={s.patternMetricVal}>{spendPattern.storeConcentration}%</Text>
                <Text style={s.patternMetricLbl}>Top store share</Text>
              </View>
              <View style={s.patternMetric}>
                <Text style={s.patternMetricVal}>{spendPattern.categoryConcentration}%</Text>
                <Text style={s.patternMetricLbl}>Top category share</Text>
              </View>
            </View>
            <View style={s.patternFocus}>
              <Text style={s.patternFocusLbl}>Next focus</Text>
              <Text style={s.patternFocusTxt} numberOfLines={1}>{spendPattern.focus}</Text>
            </View>
          </View>
        ) : null}

        {showMonthly && categoryAdvice.length > 0 ? (
          <View style={s.adviceBox}>
            <View style={s.planHeader}>
              <View>
                <Text style={s.adviceKicker}>Category Advisor</Text>
                <Text style={s.planTitle}>What each category means</Text>
              </View>
              <View style={s.advicePill}>
                <Text style={s.advicePillTxt}>{categoryAdvice.length}</Text>
              </View>
            </View>
            {categoryAdvice.map((category, index) => (
              <View key={`${category.key}-advice-${index}`} style={s.adviceRow}>
                <View style={[s.adviceDot, category.tone === 'high' && { backgroundColor:C.red }, category.tone === 'mid' && { backgroundColor:C.gold }]} />
                <View style={{ flex:1 }}>
                  <View style={s.adviceLine}>
                    <Text style={s.adviceName}>{category.label}</Text>
                    <Text style={s.adviceAmount}>{money(category.total)}</Text>
                  </View>
                  <Text style={s.adviceText}>{category.advice}</Text>
                </View>
              </View>
            ))}
          </View>
        ) : null}

        {showMonthly && budgetGuardrail ? (
          <View style={[
            s.guardrailBox,
            budgetGuardrail.overTarget > 0 && s.guardrailWarn,
          ]}>
            <View style={s.guardrailTop}>
              <View>
                <Text style={s.guardrailKicker}>Budget Guardrail</Text>
                <Text style={s.guardrailTitle}>
                  {budgetGuardrail.overTarget > 0 ? 'Target exceeded' : `${money(budgetGuardrail.remaining)} room left`}
                </Text>
              </View>
              <Text style={[
                s.guardrailValue,
                budgetGuardrail.overTarget > 0 && { color:C.red },
              ]}>
                {budgetGuardrail.overTarget > 0 ? money(budgetGuardrail.overTarget) : money(budgetGuardrail.dailyRoom)}
              </Text>
            </View>
            <View style={s.guardrailTrack}>
              <View style={[
                s.guardrailFill,
                { width: `${budgetGuardrail.progressPct}%` },
                budgetGuardrail.overTarget > 0 && { backgroundColor:C.red },
              ]} />
            </View>
            <Text style={s.guardrailText}>
              {budgetGuardrail.overTarget > 0
                ? `You are over the suggested monthly target by ${money(budgetGuardrail.overTarget)}. Compare non-urgent items before buying.`
                : `About ${money(budgetGuardrail.dailyRoom)} per day remains for the rest of this scanned month.`}
            </Text>
          </View>
        ) : null}

        {showMore && actionCards.length > 0 ? (
          <View style={s.actionBox}>
            <View style={s.planHeader}>
              <View>
                <Text style={s.actionKicker}>This Week Actions</Text>
                <Text style={s.planTitle}>What to do next</Text>
              </View>
              <View style={s.actionCountPill}>
                <Text style={s.actionCountTxt}>{actionCards.length}</Text>
              </View>
            </View>
            {actionCards.map((action, index) => (
              <View key={`${action.label}-${index}`} style={s.actionRow}>
                <View style={[
                  s.actionNumber,
                  action.tone === 'good' && { backgroundColor:'rgba(74,222,128,0.14)', borderColor:'rgba(74,222,128,0.28)' },
                  action.tone === 'warn' && { backgroundColor:'rgba(251,191,36,0.14)', borderColor:'rgba(251,191,36,0.28)' },
                  action.tone === 'bad' && { backgroundColor:'rgba(255,107,107,0.12)', borderColor:'rgba(255,107,107,0.28)' },
                ]}>
                  <Text style={[
                    s.actionNumberTxt,
                    action.tone === 'good' && { color:C.green },
                    action.tone === 'warn' && { color:C.gold },
                    action.tone === 'bad' && { color:C.red },
                  ]}>{index + 1}</Text>
                </View>
                <View style={{ flex:1 }}>
                  <Text style={s.actionLabel}>{action.label}</Text>
                  <Text style={s.actionTitle} numberOfLines={1}>{action.title}</Text>
                  <Text style={s.actionText}>{action.text}</Text>
                </View>
              </View>
            ))}
          </View>
        ) : null}

        {showShopping && savingsMission.steps.length > 0 ? (
          <View style={s.missionBox}>
            <View style={s.planHeader}>
              <View>
                <Text style={s.missionKicker}>Top Saving Move</Text>
                <Text style={s.planTitle}>Do this next</Text>
              </View>
              <View style={s.missionPill}>
                <Text style={s.missionPillTxt}>{money(savingsMission.target)}</Text>
              </View>
            </View>
            {savingsMission.steps.map((step, index) => (
              <View key={`${step}-${index}`} style={s.missionStep}>
                <Text style={s.missionStepNo}>{index + 1}</Text>
                <Text style={s.missionStepText}>{step}</Text>
              </View>
            ))}
          </View>
        ) : null}

        {showMore && noBuyItems.length > 0 ? (
          <View style={s.noBuyBox}>
            <View style={s.planHeader}>
              <View>
                <Text style={s.noBuyKicker}>No-Buy Watchlist</Text>
                <Text style={s.planTitle}>Avoid these prices</Text>
              </View>
              <View style={s.noBuyPill}>
                <Text style={s.noBuyPillTxt}>{noBuyItems.length}</Text>
              </View>
            </View>
            {noBuyItems.map((item, index) => (
              <View key={`${item.item_name}-nobuy-${index}`} style={s.noBuyRow}>
                <View style={{ flex:1 }}>
                  <Text style={s.noBuyName} numberOfLines={1}>{item.item_name}</Text>
                  <Text style={s.noBuyMeta}>
                    Good deal {money(item.good_deal_price)} - highest paid {money(item.highest_price)}
                  </Text>
                </View>
                <View style={s.noBuyRight}>
                  <Text style={s.noBuyPrice}>{money(item.avoid_above_price)}</Text>
                  <Text style={s.noBuyLabel}>avoid above</Text>
                </View>
              </View>
            ))}
          </View>
        ) : null}

        {showShopping && storeTripPlan.length > 0 ? (
          <View style={s.tripBox}>
            <View style={s.planHeader}>
              <View>
                <Text style={s.tripKicker}>Best Store Plan</Text>
                <Text style={s.planTitle}>Where to buy</Text>
              </View>
              <View style={s.tripPill}>
                <Text style={s.tripPillTxt}>{storeTripPlan.length}</Text>
              </View>
            </View>
            {storeTripPlan.map((store, index) => (
              <View key={`${store.store}-${index}`} style={s.tripStore}>
                <View style={s.tripStoreTop}>
                  <View style={{ flex:1 }}>
                    <Text style={s.tripStoreName} numberOfLines={1}>{store.store}</Text>
                    <Text style={s.tripStoreMeta}>
                      {store.items.length} item{store.items.length === 1 ? '' : 's'} · good-deal target {money(store.total)}
                    </Text>
                  </View>
                </View>
                {store.items.slice(0, 3).map((item, itemIndex) => (
                  <View key={`${store.store}-${item.item_name}-${itemIndex}`} style={s.tripItemRow}>
                    <Text style={s.tripItemName} numberOfLines={1}>{item.item_name}</Text>
                    <Text style={s.tripItemPrice}>{money(item.good_deal_price || item.usual_price)}</Text>
                  </View>
                ))}
              </View>
            ))}
          </View>
        ) : null}

        {showMore && (actionCards.length > 0 || storeTripPlan.length > 0 || returnWatch.length > 0) ? (
          <View style={s.householdBox}>
            <View style={s.planHeader}>
              <View style={{ flex:1 }}>
                <Text style={s.householdKicker}>Household Brief</Text>
                <Text style={s.planTitle}>Share the plan</Text>
                <Text style={s.householdText}>
                  Send a clean shopping summary with buy-soon items, best stores, and return reminders.
                </Text>
              </View>
              <TouchableOpacity style={s.householdBtn} onPress={shareHouseholdBrief} activeOpacity={0.82}>
                <Text style={s.householdBtnTxt}>Share</Text>
              </TouchableOpacity>
            </View>
          </View>
        ) : null}

        {showMore && returnWatch.length > 0 ? (
          <View style={s.returnBox}>
            <View style={s.planHeader}>
              <View>
                <Text style={s.returnKicker}>Return & Warranty Watch</Text>
                <Text style={s.planTitle}>Check before it expires</Text>
              </View>
              <View style={s.returnPill}>
                <Text style={s.returnPillTxt}>{returnWatch.length}</Text>
              </View>
            </View>
            {returnWatch.map((row, index) => (
              <View key={`${row.store}-${row.date}-${index}`} style={s.returnRow}>
                <View style={{ flex:1 }}>
                  <Text style={s.returnStore} numberOfLines={1}>{row.store}</Text>
                  <Text style={s.returnMeta}>
                    {row.category} - {row.date} - {row.windowDays}-day window
                  </Text>
                </View>
                <View style={s.returnRight}>
                  <Text style={s.returnTotal}>{money(row.total)}</Text>
                  <Text style={[
                    s.returnDays,
                    row.daysLeft <= 3 && { color:C.red },
                    row.daysLeft > 3 && row.daysLeft <= 10 && { color:C.gold },
                  ]}>
                    {row.daysLeft}d left
                  </Text>
                </View>
              </View>
            ))}
          </View>
        ) : null}

        {showMore && receiptAnomalies.length > 0 ? (
          <View style={s.anomalyBox}>
            <View style={s.planHeader}>
              <View>
                <Text style={s.anomalyKicker}>Receipt Anomaly Watch</Text>
                <Text style={s.planTitle}>Receipts to review</Text>
              </View>
              <View style={s.anomalyPill}>
                <Text style={s.anomalyPillTxt}>{receiptAnomalies.length}</Text>
              </View>
            </View>
            {receiptAnomalies.map((receipt, index) => (
              <View key={`${receipt.store}-${receipt.date}-anomaly-${index}`} style={s.anomalyRow}>
                <View style={{ flex:1 }}>
                  <Text style={s.anomalyStore} numberOfLines={1}>{receipt.store}</Text>
                  <Text style={s.anomalyMeta}>{receipt.category} - {receipt.date}</Text>
                  <Text style={s.anomalyReason}>{receipt.reason}</Text>
                </View>
                <Text style={s.anomalyTotal}>{money(receipt.total)}</Text>
              </View>
            ))}
          </View>
        ) : null}

        {showMore && rhythmItems.length > 0 ? (
          <View style={s.rhythmBox}>
            <View style={s.planHeader}>
              <View>
                <Text style={s.rhythmKicker}>Purchase Rhythm</Text>
                <Text style={s.planTitle}>Likely repeat buys</Text>
              </View>
              <View style={s.rhythmPill}>
                <Text style={s.rhythmPillTxt}>{rhythmItems.length}</Text>
              </View>
            </View>
            {rhythmItems.map(({ item, daysUntil, daysSince, frequency, label }, index) => (
              <View key={`${item.item_name}-rhythm-${index}`} style={s.rhythmRow}>
                <View style={{ flex:1 }}>
                  <View style={s.rhythmNameLine}>
                    <Text style={s.rhythmName} numberOfLines={1}>{item.item_name}</Text>
                    <Text style={[
                      s.rhythmBadge,
                      label === 'Likely due' && { color:C.red, borderColor:'rgba(255,107,107,0.28)', backgroundColor:'rgba(255,107,107,0.08)' },
                      label === 'Coming soon' && { color:C.gold, borderColor:'rgba(251,191,36,0.28)', backgroundColor:'rgba(251,191,36,0.08)' },
                    ]}>{label}</Text>
                  </View>
                  <Text style={s.rhythmMeta}>
                    {frequency ? `Usually every ${Math.round(frequency)} days` : 'Repeat pattern found'}
                    {daysSince !== null ? ` - last bought ${daysSince}d ago` : ''}
                  </Text>
                </View>
                <View style={s.rhythmRight}>
                  <Text style={s.rhythmPrice}>{money(item.good_deal_price)}</Text>
                  <Text style={s.rhythmDue}>
                    {daysUntil === null ? 'watch' : daysUntil <= 0 ? 'due' : `${daysUntil}d`}
                  </Text>
                </View>
              </View>
            ))}
          </View>
        ) : null}

        {showShopping && basketBuilder.length > 0 ? (
          <View style={s.basketBox}>
            <View style={s.planHeader}>
              <View>
                <Text style={s.basketKicker}>Next Cart</Text>
                <Text style={s.planTitle}>Suggested items</Text>
              </View>
              <View style={s.basketPill}>
                <Text style={s.basketPillTxt}>{money(basketTotal)}</Text>
              </View>
            </View>
            {basketBuilder.map((item, index) => (
              <View key={`${item.item_name}-basket-${index}`} style={s.basketRow}>
                <View style={s.basketCheck}>
                  <Text style={s.basketCheckTxt}>{index + 1}</Text>
                </View>
                <View style={{ flex:1 }}>
                  <Text style={s.basketName} numberOfLines={1}>{item.item_name}</Text>
                  <Text style={s.basketMeta} numberOfLines={1}>{item.reason} - {item.store}</Text>
                </View>
                <Text style={s.basketPrice}>{money(item.price)}</Text>
              </View>
            ))}
          </View>
        ) : null}

        {showMore && items.length > 0 ? (
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

        {showShopping && savingsOpportunities.length > 0 ? (
          <View style={s.opportunityBox}>
            <View style={s.planHeader}>
              <View>
                <Text style={s.opportunityKicker}>Savings Opportunities</Text>
                <Text style={s.planTitle}>Best places to save</Text>
              </View>
              <View style={s.opportunityPill}>
                <Text style={s.opportunityPillTxt}>{money(totalOpportunity)}</Text>
              </View>
            </View>
            {savingsOpportunities.map(({ item, perBuy, swing }, index) => (
              <View key={`${item.item_name}-opportunity-${index}`} style={s.opportunityRow}>
                <View style={{ flex:1 }}>
                  <Text style={s.opportunityItem} numberOfLines={1}>{item.item_name}</Text>
                  <Text style={s.opportunityMeta} numberOfLines={1}>
                    Target {money(item.good_deal_price)} · usual {money(item.usual_price)}
                  </Text>
                  {item.cheapest_store ? (
                    <Text style={s.opportunityStore} numberOfLines={1}>Best known store: {item.cheapest_store}</Text>
                  ) : null}
                </View>
                <View style={s.opportunitySave}>
                  <Text style={s.opportunitySaveVal}>{money(perBuy)}</Text>
                  <Text style={s.opportunitySaveLbl}>per buy</Text>
                  {swing > perBuy ? <Text style={s.opportunitySwing}>{money(swing)} swing</Text> : null}
                </View>
              </View>
            ))}
          </View>
        ) : null}

        {showInsights && storeIntelligence.length > 0 ? (
          <View style={s.storeIntelBox}>
            <View style={s.planHeader}>
              <View>
                <Text style={s.storeIntelKicker}>Store Intelligence</Text>
                <Text style={s.planTitle}>Where prices look best</Text>
              </View>
              <View style={s.storeIntelPill}>
                <Text style={s.storeIntelPillTxt}>{storeIntelligence.length}</Text>
              </View>
            </View>
            {storeIntelligence.map((store, index) => (
              <View key={`${store.store}-${index}`} style={s.storeIntelRow}>
                <View style={s.storeRank}>
                  <Text style={s.storeRankTxt}>{index + 1}</Text>
                </View>
                <View style={{ flex:1 }}>
                  <Text style={s.storeIntelName} numberOfLines={1}>{store.store}</Text>
                  <Text style={s.storeIntelMeta}>
                    Cheapest for {store.items} tracked item{store.items === 1 ? '' : 's'}
                  </Text>
                  {store.bestItem ? <Text style={s.storeIntelItem} numberOfLines={1}>Watch: {store.bestItem}</Text> : null}
                </View>
                <View style={s.storeIntelSave}>
                  <Text style={s.storeIntelSaveVal}>{money(store.opportunity)}</Text>
                  <Text style={s.storeIntelSaveLbl}>potential</Text>
                </View>
              </View>
            ))}
          </View>
        ) : null}

        {showInsights && loyaltySignals.length > 0 ? (
          <View style={s.loyaltyBox}>
            <View style={s.planHeader}>
              <View>
                <Text style={s.loyaltyKicker}>Merchant Loyalty</Text>
                <Text style={s.planTitle}>Stores worth trusting</Text>
              </View>
              <View style={s.loyaltyPill}>
                <Text style={s.loyaltyPillTxt}>{loyaltySignals.length}</Text>
              </View>
            </View>
            {loyaltySignals.map((store, index) => (
              <View key={`${store.store}-loyalty-${index}`} style={s.loyaltyRow}>
                <View style={{ flex:1 }}>
                  <View style={s.loyaltyLine}>
                    <Text style={s.loyaltyStore} numberOfLines={1}>{store.store}</Text>
                    <Text style={[
                      s.loyaltyStatus,
                      store.status === 'Good loyalty' && { color:C.green, borderColor:'rgba(74,222,128,0.24)', backgroundColor:'rgba(74,222,128,0.08)' },
                    ]}>{store.status}</Text>
                  </View>
                  <Text style={s.loyaltyAdvice}>{store.advice}</Text>
                </View>
                <View style={s.loyaltyRight}>
                  <Text style={s.loyaltyValue}>{money(store.avgOpportunity)}</Text>
                  <Text style={s.loyaltyLabel}>avg edge</Text>
                </View>
              </View>
            ))}
          </View>
        ) : null}

        {showInsights && marketEdgeItems.length > 0 ? (
          <View style={s.edgeBox}>
            <View style={s.planHeader}>
              <View>
                <Text style={s.edgeKicker}>Market Edge</Text>
                <Text style={s.planTitle}>Price radar</Text>
              </View>
              <View style={s.edgePill}>
                <Text style={s.edgePillTxt}>{marketEdgeItems.length}</Text>
              </View>
            </View>
            {marketEdgeItems.map(({ item, markerPct, action }, index) => (
              <View key={`${item.item_name}-edge-${index}`} style={s.edgeRow}>
                <View style={s.edgeTop}>
                  <View style={{ flex:1 }}>
                    <Text style={s.edgeName} numberOfLines={1}>{item.item_name}</Text>
                    <Text style={s.edgeAction}>{action}</Text>
                  </View>
                  <Text style={s.edgeSwing}>{money(item.price_range)} swing</Text>
                </View>
                <View style={s.edgeScale}>
                  <View style={[s.edgeDealZone, { width:'35%' }]} />
                  <View style={[s.edgeMarker, { left: `${markerPct}%` }]} />
                </View>
                <View style={s.edgeLabels}>
                  <Text style={s.edgeLabel}>Low {money(item.lowest_price)}</Text>
                  <Text style={s.edgeLabel}>Usual {money(item.usual_price)}</Text>
                  <Text style={s.edgeLabel}>High {money(item.highest_price)}</Text>
                </View>
              </View>
            ))}
          </View>
        ) : null}

        {showMore && alerts.length > 0 ? (
          <View style={s.autoAlertBox}>
            <View style={s.autoAlertTop}>
              <View style={{ flex:1 }}>
                <Text style={s.autoAlertKicker}>Smart Alert Automation</Text>
                <Text style={s.autoAlertTitle}>{autoAlertEnabled ? 'Alerts are scheduled' : 'Enable top reminders'}</Text>
                <Text style={s.autoAlertText}>
                  Schedules your highest priority price-swing and may-need-soon reminders on this device.
                </Text>
              </View>
              <TouchableOpacity
                style={[s.autoAlertBtn, autoAlertEnabled && s.autoAlertBtnDone]}
                onPress={scheduleTopAlerts}
                disabled={autoAlertEnabled}
                activeOpacity={0.82}
              >
                <Text style={[s.autoAlertBtnTxt, autoAlertEnabled && s.autoAlertBtnTxtDone]}>
                  {autoAlertEnabled ? 'Enabled' : 'Enable'}
                </Text>
              </TouchableOpacity>
            </View>
          </View>
        ) : null}

        {showInsights && learningQueue.length > 0 ? (
          <View style={s.learningBox}>
            <View style={s.planHeader}>
              <View>
                <Text style={s.learningKicker}>Learning Queue</Text>
                <Text style={s.planTitle}>Needs more history</Text>
              </View>
              <View style={s.learningPill}>
                <Text style={s.learningPillTxt}>{learningQueue.length}</Text>
              </View>
            </View>
            <Text style={s.learningIntro}>
              Scan these again when you buy them so Price Memory can learn a real low, usual, and avoid-above price.
            </Text>
            {learningQueue.map((item, index) => (
              <View key={`${item.item_name}-learning-${index}`} style={s.learningRow}>
                <View style={{ flex:1 }}>
                  <Text style={s.learningName} numberOfLines={1}>{item.item_name}</Text>
                  <Text style={s.learningMeta}>
                    Current signal: {money(item.usual_price)} · {item.times_bought} buy{item.times_bought === 1 ? '' : 's'}
                  </Text>
                </View>
                <Text style={s.learningNeed}>+1 scan</Text>
              </View>
            ))}
          </View>
        ) : null}

        {showMore && alerts.length > 0 ? (
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

        {showShopping && items.length > 0 ? (
          <View style={s.checkBox}>
            <Text style={s.planKicker}>Before You Buy</Text>
            <Text style={s.checkTitle}>Is this a good price?</Text>
            <View style={s.checkInputs}>
              <TextInput
                style={[s.search, { flex: 1.4, marginBottom: 0 }]}
                value={checkItem}
                onChangeText={setCheckItem}
                placeholder="Item name"
                placeholderTextColor={C.text3}
                autoCorrect={false}
                onFocus={keepBeforeBuyVisible}
              />
              <TextInput
                style={[s.search, { flex: 0.8, marginBottom: 0 }]}
                value={checkPrice}
                onChangeText={setCheckPrice}
                placeholder="$ price"
                placeholderTextColor={C.text3}
                keyboardType="decimal-pad"
                onFocus={keepBeforeBuyVisible}
              />
            </View>

            <TouchableOpacity
              style={[s.liveCheckBtn, liveChecking && { opacity:0.55 }]}
              onPress={runLivePriceCheck}
              disabled={liveChecking}
              activeOpacity={0.84}
            >
              <Text style={s.liveCheckBtnTxt}>{liveChecking ? 'Checking...' : 'Compare with receipt memory'}</Text>
            </TouchableOpacity>

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

            {liveCheck?.decision ? (
              <View style={[
                s.liveResultBox,
                liveCheck.decision.verdict === 'Buy' && s.decisionGood,
                liveCheck.decision.verdict === 'Wait or compare' && s.decisionBad,
              ]}>
                <View style={s.decisionTop}>
                  <Text style={s.decisionLabel}>{liveCheck.decision.verdict}</Text>
                  <Text style={s.decisionPrice}>{money(liveCheck.current_price)}</Text>
                </View>
                <Text style={s.decisionText}>{liveCheck.decision.reason}</Text>
                <Text style={s.decisionSub} numberOfLines={3}>
                  Matched: {liveCheck.matched_item} - usual {money(liveCheck.receipt_memory?.usual_price)} - good deal {money(liveCheck.receipt_memory?.good_deal_price)} - avoid above {money(liveCheck.receipt_memory?.avoid_above_price)}
                </Text>
              </View>
            ) : null}
          </View>
        ) : null}

        {tabEmpty ? (
          <View style={s.tabEmptyBox}>
            <Text style={s.tabEmptyTitle}>{tabEmpty.title}</Text>
            <Text style={s.tabEmptyText}>{tabEmpty.text}</Text>
          </View>
        ) : null}

        {showItems && items.length > 0 ? (
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

        {showItems ? (
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
        ) : null}

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
        ) : (showItems || items.length === 0) && shown.length === 0 ? (
          <View style={s.stateBox}>
            <Text style={s.emptyTitle}>No price memory yet</Text>
            <Text style={s.stateText}>Scan receipts with item prices. Repeat purchases become smarter over time.</Text>
          </View>
        ) : showItems ? (
          <View style={s.list}>
            {shown.map((item, index) => {
              const insight = dealInsight(item);
              const confidence = itemConfidence(item);
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

                <View style={s.itemConfidenceRow}>
                  <View style={[
                    s.itemConfidencePill,
                    confidence.tone === 'good' && s.itemConfidenceGood,
                    confidence.tone === 'mid' && s.itemConfidenceMid,
                    confidence.tone === 'low' && s.itemConfidenceLow,
                  ]}>
                    <Text style={[
                      s.itemConfidenceTxt,
                      confidence.tone === 'good' && { color:C.green },
                      confidence.tone === 'mid' && { color:C.gold },
                      confidence.tone === 'low' && { color:C.text3 },
                    ]}>
                      {confidence.label}
                    </Text>
                  </View>
                  <Text style={s.itemConfidenceMeta}>{confidence.text} behind this price signal</Text>
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
        ) : null}

        {showItems && items.length > 0 ? (
          <View style={s.footerNote}>
            <Text style={s.footerText}>Average avoid-above signal: {money(avgAvoid)}. Use this before buying repeat items.</Text>
          </View>
        ) : null}
      </ScrollView>
      </KeyboardAvoidingView>
    </View>
  );
}

const createStyles = (C: typeof DARK_COLORS) => StyleSheet.create({
  screen:{ flex:1, backgroundColor:C.bg },
  keyboardWrap:{ flex:1 },
  content:{ padding:16, paddingBottom:180 },
  hero:{ marginBottom:16 },
  heroKicker:{ color:C.accent, fontSize:11, fontWeight:'700', textTransform:'uppercase', letterSpacing:0.6, marginBottom:6 },
  heroTitle:{ color:C.text, fontSize:30, fontWeight:'900', letterSpacing:0 },
  heroSub:{ color:C.text2, fontSize:13, lineHeight:19, marginTop:6 },
  statsRow:{ flexDirection:'row', gap:10, marginBottom:14 },
  statBox:{ flex:1, backgroundColor:C.card, borderWidth:1, borderColor:C.border, borderRadius:16, padding:12, shadowColor:'#000', shadowOpacity:0.16, shadowRadius:12, shadowOffset:{width:0,height:7}, elevation:3 },
  statVal:{ color:C.accent, fontSize:22, fontWeight:'900' },
  statLbl:{ color:C.text2, fontSize:11, marginTop:2 },
  briefBox:{ backgroundColor:C.card, borderWidth:1, borderColor:C.border, borderRadius:18, padding:15, marginBottom:14, shadowColor:'#000', shadowOpacity:0.20, shadowRadius:16, shadowOffset:{width:0,height:10}, elevation:4 },
  briefKicker:{ color:C.accent, fontSize:10, fontWeight:'900', textTransform:'uppercase', letterSpacing:0.5, marginBottom:4 },
  briefTitle:{ color:C.text, fontSize:20, fontWeight:'900', marginBottom:6 },
  briefPrimary:{ color:C.text, fontSize:13, lineHeight:19, fontWeight:'800' },
  briefSecondary:{ color:C.text2, fontSize:12, lineHeight:17, marginTop:6 },
  briefFocus:{ marginTop:11, borderTopWidth:1, borderTopColor:C.border, paddingTop:8 },
  briefFocusRow:{ flexDirection:'row', gap:9, alignItems:'flex-start', paddingVertical:5 },
  briefFocusNo:{ width:22, height:22, borderRadius:99, overflow:'hidden', textAlign:'center', textAlignVertical:'center', color:C.accent, backgroundColor:'rgba(124,106,255,0.12)', fontSize:11, fontWeight:'900' },
  briefFocusText:{ color:C.text2, fontSize:12, lineHeight:17, flex:1 },
  scoreBox:{ flexDirection:'row', gap:8, marginBottom:14 },
  scoreItem:{ flex:1, backgroundColor:C.surface, borderWidth:1, borderColor:C.border, borderRadius:14, padding:10 },
  scoreValue:{ color:C.text, fontSize:15, fontWeight:'900' },
  scoreLabel:{ color:C.text3, fontSize:10, fontWeight:'800', marginTop:3 },
  viewRow:{ gap:8, paddingBottom:14 },
  viewChip:{ flexDirection:'row', alignItems:'center', gap:7, backgroundColor:C.surface, borderWidth:1, borderColor:C.border, borderRadius:12, paddingHorizontal:13, paddingVertical:9 },
  viewChipActive:{ backgroundColor:'rgba(124,106,255,0.16)', borderColor:'rgba(124,106,255,0.42)' },
  viewTxt:{ color:C.text2, fontSize:12, fontWeight:'900' },
  viewTxtActive:{ color:C.text },
  viewCount:{ color:C.text3, fontSize:11, fontWeight:'900' },
  viewCountActive:{ color:C.accent },
  healthBox:{ backgroundColor:C.card, borderWidth:1, borderColor:C.border, borderRadius:18, padding:15, marginBottom:14, shadowColor:'#000', shadowOpacity:0.18, shadowRadius:14, shadowOffset:{width:0,height:8}, elevation:4 },
  healthTop:{ flexDirection:'row', alignItems:'flex-start', justifyContent:'space-between', gap:12, marginBottom:10 },
  healthKicker:{ color:C.green, fontSize:10, fontWeight:'800', textTransform:'uppercase', letterSpacing:0.5, marginBottom:3 },
  healthTitle:{ color:C.text, fontSize:18, fontWeight:'900' },
  healthScore:{ color:C.accent, fontSize:34, fontWeight:'900' },
  healthTrack:{ height:9, borderRadius:99, backgroundColor:C.surface2, overflow:'hidden', borderWidth:1, borderColor:C.border },
  healthFill:{ height:'100%', borderRadius:99, backgroundColor:C.accent },
  healthParts:{ flexDirection:'row', gap:8, marginTop:9 },
  healthPart:{ flex:1, color:C.text2, fontSize:10, lineHeight:14, fontWeight:'800' },
  doctorBox:{ borderWidth:1, borderRadius:14, padding:14, marginBottom:14 },
  doctorGood:{ backgroundColor:'rgba(74,222,128,0.09)', borderColor:'rgba(74,222,128,0.24)' },
  doctorWarn:{ backgroundColor:'rgba(255,107,107,0.08)', borderColor:'rgba(255,107,107,0.24)' },
  doctorMid:{ backgroundColor:'rgba(251,191,36,0.08)', borderColor:'rgba(251,191,36,0.24)' },
  doctorKicker:{ color:C.text3, fontSize:10, fontWeight:'900', textTransform:'uppercase', letterSpacing:0.5, marginBottom:4 },
  doctorTitle:{ color:C.text, fontSize:17, fontWeight:'900', marginBottom:5 },
  doctorText:{ color:C.text2, fontSize:12, lineHeight:17 },
  doctorFix:{ color:C.text, fontSize:12, lineHeight:17, fontWeight:'900', marginTop:8 },
  qualityBox:{ backgroundColor:C.surface, borderWidth:1, borderColor:C.border, borderRadius:14, padding:14, marginBottom:14 },
  qualityKicker:{ color:C.gold, fontSize:10, fontWeight:'900', textTransform:'uppercase', letterSpacing:0.5, marginBottom:3 },
  qualityPill:{ backgroundColor:'rgba(251,191,36,0.10)', borderWidth:1, borderColor:'rgba(251,191,36,0.24)', borderRadius:12, minWidth:34, paddingHorizontal:10, paddingVertical:7, alignItems:'center' },
  qualityPillTxt:{ color:C.gold, fontWeight:'900', fontSize:13 },
  qualityRow:{ paddingVertical:9, borderTopWidth:1, borderTopColor:C.border },
  qualityLabel:{ color:C.text, fontSize:13, fontWeight:'900', marginBottom:3 },
  qualityText:{ color:C.text2, fontSize:12, lineHeight:17 },
  questionsBox:{ backgroundColor:C.surface, borderWidth:1, borderColor:C.border, borderRadius:14, padding:14, marginBottom:14 },
  questionsKicker:{ color:C.accent, fontSize:10, fontWeight:'800', textTransform:'uppercase', letterSpacing:0.5, marginBottom:3 },
  questionsRow:{ gap:8, paddingRight:4 },
  questionChip:{ maxWidth:230, backgroundColor:C.surface2, borderWidth:1, borderColor:C.border, borderRadius:11, paddingHorizontal:11, paddingVertical:9 },
  questionTxt:{ color:C.text2, fontSize:12, lineHeight:17, fontWeight:'800' },
  confidenceBox:{ backgroundColor:C.surface, borderWidth:1, borderColor:C.border, borderRadius:14, padding:14, marginBottom:14 },
  confidenceTop:{ flexDirection:'row', alignItems:'flex-start', justifyContent:'space-between', gap:12, marginBottom:10 },
  confidenceKicker:{ color:C.accent, fontSize:10, fontWeight:'800', textTransform:'uppercase', letterSpacing:0.5, marginBottom:3 },
  confidenceTitle:{ color:C.text, fontSize:17, fontWeight:'900' },
  confidencePct:{ color:C.green, fontSize:22, fontWeight:'900' },
  confidenceTrack:{ height:8, borderRadius:99, backgroundColor:C.surface2, overflow:'hidden', borderWidth:1, borderColor:C.border },
  confidenceFill:{ height:'100%', borderRadius:99, backgroundColor:C.green },
  confidenceStats:{ flexDirection:'row', justifyContent:'space-between', gap:10, marginTop:8 },
  confidenceText:{ color:C.text2, fontSize:11, lineHeight:16, flex:1 },
  monthBox:{ backgroundColor:C.card, borderWidth:1, borderColor:C.border, borderRadius:18, padding:15, marginBottom:14, shadowColor:'#000', shadowOpacity:0.18, shadowRadius:14, shadowOffset:{width:0,height:8}, elevation:4 },
  monthKicker:{ color:C.accent, fontSize:10, fontWeight:'800', textTransform:'uppercase', letterSpacing:0.5, marginBottom:3 },
  monthTotalPill:{ backgroundColor:'rgba(124,106,255,0.12)', borderWidth:1, borderColor:'rgba(124,106,255,0.26)', borderRadius:12, paddingHorizontal:10, paddingVertical:7 },
  monthTotalTxt:{ color:C.accent, fontWeight:'900', fontSize:13 },
  monthGrid:{ flexDirection:'row', gap:8, marginBottom:12 },
  monthMetric:{ flex:1, backgroundColor:C.surface2, borderWidth:1, borderColor:C.border, borderRadius:14, padding:10 },
  monthMetricVal:{ color:C.text, fontSize:15, fontWeight:'900' },
  monthMetricLbl:{ color:C.text3, fontSize:10, marginTop:3, fontWeight:'700' },
  forecastBox:{ backgroundColor:C.surface2, borderWidth:1, borderColor:C.border, borderRadius:12, padding:12, marginBottom:12 },
  forecastTop:{ flexDirection:'row', alignItems:'flex-start', justifyContent:'space-between', gap:10, marginBottom:10 },
  forecastKicker:{ color:C.text3, fontSize:10, fontWeight:'800', textTransform:'uppercase', letterSpacing:0.5, marginBottom:3 },
  forecastValue:{ color:C.text, fontSize:22, fontWeight:'900' },
  forecastPill:{ backgroundColor:'rgba(124,106,255,0.12)', borderWidth:1, borderColor:'rgba(124,106,255,0.24)', borderRadius:99, paddingHorizontal:9, paddingVertical:5 },
  forecastPillTxt:{ color:C.accent, fontSize:10, fontWeight:'900' },
  forecastGrid:{ flexDirection:'row', justifyContent:'space-between', gap:10, marginBottom:8 },
  forecastLbl:{ color:C.text3, fontSize:10, fontWeight:'700', marginBottom:3 },
  forecastSub:{ color:C.text, fontSize:13, fontWeight:'900' },
  forecastHint:{ color:C.text2, fontSize:11, lineHeight:16 },
  coverageBox:{ backgroundColor:C.surface2, borderWidth:1, borderColor:C.border, borderRadius:12, padding:12, marginBottom:12 },
  coverageTop:{ flexDirection:'row', alignItems:'flex-start', justifyContent:'space-between', gap:12, marginBottom:9 },
  coverageKicker:{ color:C.text3, fontSize:10, fontWeight:'900', textTransform:'uppercase', letterSpacing:0.5, marginBottom:3 },
  coverageTitle:{ color:C.text, fontSize:15, fontWeight:'900' },
  coverageScore:{ color:C.accent, fontSize:18, fontWeight:'900' },
  coverageTrack:{ height:7, borderRadius:99, backgroundColor:C.border, overflow:'hidden' },
  coverageFill:{ height:'100%', borderRadius:99, backgroundColor:C.accent },
  coverageText:{ color:C.text2, fontSize:11, lineHeight:16, marginTop:8 },
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
  shareReportBtn:{ marginTop:10, backgroundColor:C.surface2, borderWidth:1, borderColor:C.border, borderRadius:11, paddingVertical:10, alignItems:'center' },
  shareReportTxt:{ color:C.accent, fontSize:12, fontWeight:'900' },
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
  patternBox:{ backgroundColor:C.surface, borderWidth:1, borderColor:C.border, borderRadius:14, padding:14, marginBottom:14 },
  patternKicker:{ color:C.accent, fontSize:10, fontWeight:'900', textTransform:'uppercase', letterSpacing:0.5, marginBottom:3 },
  patternPill:{ backgroundColor:'rgba(124,106,255,0.12)', borderWidth:1, borderColor:'rgba(124,106,255,0.26)', borderRadius:12, minWidth:44, paddingHorizontal:10, paddingVertical:7, alignItems:'center' },
  patternPillTxt:{ color:C.accent, fontWeight:'900', fontSize:13 },
  patternText:{ color:C.text2, fontSize:12, lineHeight:18, marginBottom:11 },
  patternGrid:{ flexDirection:'row', gap:8, marginBottom:10 },
  patternMetric:{ flex:1, backgroundColor:C.surface2, borderWidth:1, borderColor:C.border, borderRadius:12, padding:10 },
  patternMetricVal:{ color:C.text, fontSize:17, fontWeight:'900' },
  patternMetricLbl:{ color:C.text3, fontSize:10, fontWeight:'800', marginTop:3 },
  patternFocus:{ flexDirection:'row', alignItems:'center', justifyContent:'space-between', gap:10, backgroundColor:C.surface2, borderWidth:1, borderColor:C.border, borderRadius:11, paddingHorizontal:11, paddingVertical:9 },
  patternFocusLbl:{ color:C.text3, fontSize:10, fontWeight:'900', textTransform:'uppercase', letterSpacing:0.5 },
  patternFocusTxt:{ color:C.green, fontSize:12, fontWeight:'900', flex:1, textAlign:'right' },
  adviceBox:{ backgroundColor:C.surface, borderWidth:1, borderColor:C.border, borderRadius:14, padding:14, marginBottom:14 },
  adviceKicker:{ color:C.green, fontSize:10, fontWeight:'900', textTransform:'uppercase', letterSpacing:0.5, marginBottom:3 },
  advicePill:{ backgroundColor:'rgba(74,222,128,0.10)', borderWidth:1, borderColor:'rgba(74,222,128,0.24)', borderRadius:12, minWidth:34, paddingHorizontal:10, paddingVertical:7, alignItems:'center' },
  advicePillTxt:{ color:C.green, fontWeight:'900', fontSize:13 },
  adviceRow:{ flexDirection:'row', alignItems:'flex-start', gap:10, paddingVertical:10, borderTopWidth:1, borderTopColor:C.border },
  adviceDot:{ width:9, height:9, borderRadius:99, backgroundColor:C.green, marginTop:4 },
  adviceLine:{ flexDirection:'row', alignItems:'center', justifyContent:'space-between', gap:10, marginBottom:3 },
  adviceName:{ color:C.text, fontSize:13, fontWeight:'900', flex:1 },
  adviceAmount:{ color:C.accent, fontSize:12, fontWeight:'900' },
  adviceText:{ color:C.text2, fontSize:12, lineHeight:17 },
  guardrailBox:{ backgroundColor:C.surface, borderWidth:1, borderColor:C.border, borderRadius:14, padding:14, marginBottom:14 },
  guardrailWarn:{ borderColor:'rgba(255,107,107,0.28)', backgroundColor:'rgba(255,107,107,0.07)' },
  guardrailTop:{ flexDirection:'row', alignItems:'flex-start', justifyContent:'space-between', gap:12, marginBottom:10 },
  guardrailKicker:{ color:C.gold, fontSize:10, fontWeight:'900', textTransform:'uppercase', letterSpacing:0.5, marginBottom:3 },
  guardrailTitle:{ color:C.text, fontSize:17, fontWeight:'900' },
  guardrailValue:{ color:C.green, fontSize:18, fontWeight:'900' },
  guardrailTrack:{ height:8, borderRadius:99, backgroundColor:C.surface2, overflow:'hidden', borderWidth:1, borderColor:C.border },
  guardrailFill:{ height:'100%', borderRadius:99, backgroundColor:C.green },
  guardrailText:{ color:C.text2, fontSize:12, lineHeight:17, marginTop:8 },
  actionBox:{ backgroundColor:C.surface, borderWidth:1, borderColor:C.border, borderRadius:14, padding:14, marginBottom:14 },
  actionKicker:{ color:C.gold, fontSize:10, fontWeight:'800', textTransform:'uppercase', letterSpacing:0.5, marginBottom:3 },
  actionCountPill:{ backgroundColor:'rgba(251,191,36,0.10)', borderWidth:1, borderColor:'rgba(251,191,36,0.24)', borderRadius:12, minWidth:34, paddingHorizontal:10, paddingVertical:7, alignItems:'center' },
  actionCountTxt:{ color:C.gold, fontWeight:'900', fontSize:13 },
  actionRow:{ flexDirection:'row', gap:10, paddingVertical:10, borderTopWidth:1, borderTopColor:C.border },
  actionNumber:{ width:28, height:28, borderRadius:99, borderWidth:1, alignItems:'center', justifyContent:'center', backgroundColor:C.surface2, borderColor:C.border },
  actionNumberTxt:{ color:C.text, fontSize:12, fontWeight:'900' },
  actionLabel:{ color:C.text3, fontSize:10, fontWeight:'900', textTransform:'uppercase', letterSpacing:0.5, marginBottom:2 },
  actionTitle:{ color:C.text, fontSize:13, fontWeight:'900' },
  actionText:{ color:C.text2, fontSize:12, lineHeight:17, marginTop:3 },
  missionBox:{ backgroundColor:C.surface, borderWidth:1, borderColor:C.border, borderRadius:14, padding:14, marginBottom:14 },
  missionKicker:{ color:C.green, fontSize:10, fontWeight:'900', textTransform:'uppercase', letterSpacing:0.5, marginBottom:3 },
  missionPill:{ backgroundColor:'rgba(74,222,128,0.10)', borderWidth:1, borderColor:'rgba(74,222,128,0.24)', borderRadius:12, paddingHorizontal:10, paddingVertical:7 },
  missionPillTxt:{ color:C.green, fontWeight:'900', fontSize:13 },
  missionStep:{ flexDirection:'row', gap:10, alignItems:'flex-start', paddingVertical:9, borderTopWidth:1, borderTopColor:C.border },
  missionStepNo:{ width:24, height:24, borderRadius:99, overflow:'hidden', textAlign:'center', textAlignVertical:'center', backgroundColor:'rgba(74,222,128,0.12)', color:C.green, fontSize:12, fontWeight:'900' },
  missionStepText:{ color:C.text2, fontSize:12, lineHeight:17, flex:1, fontWeight:'800' },
  noBuyBox:{ backgroundColor:C.surface, borderWidth:1, borderColor:'rgba(255,107,107,0.22)', borderRadius:14, padding:14, marginBottom:14 },
  noBuyKicker:{ color:C.red, fontSize:10, fontWeight:'900', textTransform:'uppercase', letterSpacing:0.5, marginBottom:3 },
  noBuyPill:{ backgroundColor:'rgba(255,107,107,0.10)', borderWidth:1, borderColor:'rgba(255,107,107,0.24)', borderRadius:12, minWidth:34, paddingHorizontal:10, paddingVertical:7, alignItems:'center' },
  noBuyPillTxt:{ color:C.red, fontWeight:'900', fontSize:13 },
  noBuyRow:{ flexDirection:'row', alignItems:'center', gap:10, paddingVertical:10, borderTopWidth:1, borderTopColor:C.border },
  noBuyName:{ color:C.text, fontSize:13, fontWeight:'900' },
  noBuyMeta:{ color:C.text2, fontSize:11, marginTop:3 },
  noBuyRight:{ alignItems:'flex-end', minWidth:82 },
  noBuyPrice:{ color:C.red, fontSize:13, fontWeight:'900' },
  noBuyLabel:{ color:C.text3, fontSize:9, fontWeight:'900', textTransform:'uppercase', marginTop:3 },
  tripBox:{ backgroundColor:C.surface, borderWidth:1, borderColor:C.border, borderRadius:14, padding:14, marginBottom:14 },
  tripKicker:{ color:C.accent, fontSize:10, fontWeight:'800', textTransform:'uppercase', letterSpacing:0.5, marginBottom:3 },
  tripPill:{ backgroundColor:'rgba(124,106,255,0.12)', borderWidth:1, borderColor:'rgba(124,106,255,0.26)', borderRadius:12, minWidth:34, paddingHorizontal:10, paddingVertical:7, alignItems:'center' },
  tripPillTxt:{ color:C.accent, fontWeight:'900', fontSize:13 },
  tripStore:{ paddingVertical:10, borderTopWidth:1, borderTopColor:C.border },
  tripStoreTop:{ flexDirection:'row', justifyContent:'space-between', alignItems:'flex-start', gap:10, marginBottom:8 },
  tripStoreName:{ color:C.text, fontSize:14, fontWeight:'900' },
  tripStoreMeta:{ color:C.text2, fontSize:11, marginTop:3 },
  tripItemRow:{ flexDirection:'row', alignItems:'center', justifyContent:'space-between', gap:10, paddingVertical:4 },
  tripItemName:{ color:C.text2, fontSize:12, flex:1 },
  tripItemPrice:{ color:C.green, fontSize:12, fontWeight:'900' },
  householdBox:{ backgroundColor:C.surface, borderWidth:1, borderColor:C.border, borderRadius:14, padding:14, marginBottom:14 },
  householdKicker:{ color:C.gold, fontSize:10, fontWeight:'900', textTransform:'uppercase', letterSpacing:0.5, marginBottom:3 },
  householdText:{ color:C.text2, fontSize:12, lineHeight:17, marginTop:5 },
  householdBtn:{ backgroundColor:C.accent, borderRadius:11, paddingHorizontal:14, paddingVertical:10, marginTop:2 },
  householdBtnTxt:{ color:'#fff', fontSize:12, fontWeight:'900' },
  returnBox:{ backgroundColor:C.surface, borderWidth:1, borderColor:C.border, borderRadius:14, padding:14, marginBottom:14 },
  returnKicker:{ color:C.green, fontSize:10, fontWeight:'900', textTransform:'uppercase', letterSpacing:0.5, marginBottom:3 },
  returnPill:{ backgroundColor:'rgba(74,222,128,0.10)', borderWidth:1, borderColor:'rgba(74,222,128,0.24)', borderRadius:12, minWidth:34, paddingHorizontal:10, paddingVertical:7, alignItems:'center' },
  returnPillTxt:{ color:C.green, fontWeight:'900', fontSize:13 },
  returnRow:{ flexDirection:'row', alignItems:'center', gap:10, paddingVertical:10, borderTopWidth:1, borderTopColor:C.border },
  returnStore:{ color:C.text, fontSize:13, fontWeight:'900' },
  returnMeta:{ color:C.text2, fontSize:11, marginTop:3 },
  returnRight:{ alignItems:'flex-end', minWidth:72 },
  returnTotal:{ color:C.text, fontSize:12, fontWeight:'900' },
  returnDays:{ color:C.green, fontSize:11, fontWeight:'900', marginTop:3 },
  anomalyBox:{ backgroundColor:C.surface, borderWidth:1, borderColor:C.border, borderRadius:14, padding:14, marginBottom:14 },
  anomalyKicker:{ color:C.gold, fontSize:10, fontWeight:'900', textTransform:'uppercase', letterSpacing:0.5, marginBottom:3 },
  anomalyPill:{ backgroundColor:'rgba(251,191,36,0.10)', borderWidth:1, borderColor:'rgba(251,191,36,0.24)', borderRadius:12, minWidth:34, paddingHorizontal:10, paddingVertical:7, alignItems:'center' },
  anomalyPillTxt:{ color:C.gold, fontWeight:'900', fontSize:13 },
  anomalyRow:{ flexDirection:'row', alignItems:'flex-start', gap:10, paddingVertical:10, borderTopWidth:1, borderTopColor:C.border },
  anomalyStore:{ color:C.text, fontSize:13, fontWeight:'900' },
  anomalyMeta:{ color:C.text2, fontSize:11, marginTop:3 },
  anomalyReason:{ color:C.gold, fontSize:11, fontWeight:'800', marginTop:4 },
  anomalyTotal:{ color:C.text, fontSize:13, fontWeight:'900' },
  rhythmBox:{ backgroundColor:C.surface, borderWidth:1, borderColor:C.border, borderRadius:14, padding:14, marginBottom:14 },
  rhythmKicker:{ color:C.accent, fontSize:10, fontWeight:'900', textTransform:'uppercase', letterSpacing:0.5, marginBottom:3 },
  rhythmPill:{ backgroundColor:'rgba(124,106,255,0.12)', borderWidth:1, borderColor:'rgba(124,106,255,0.26)', borderRadius:12, minWidth:34, paddingHorizontal:10, paddingVertical:7, alignItems:'center' },
  rhythmPillTxt:{ color:C.accent, fontWeight:'900', fontSize:13 },
  rhythmRow:{ flexDirection:'row', alignItems:'center', gap:10, paddingVertical:10, borderTopWidth:1, borderTopColor:C.border },
  rhythmNameLine:{ flexDirection:'row', alignItems:'center', gap:8 },
  rhythmName:{ color:C.text, fontSize:13, fontWeight:'900', flex:1 },
  rhythmBadge:{ color:C.green, fontSize:10, fontWeight:'900', borderWidth:1, borderColor:'rgba(74,222,128,0.24)', backgroundColor:'rgba(74,222,128,0.08)', borderRadius:99, paddingHorizontal:8, paddingVertical:3, overflow:'hidden' },
  rhythmMeta:{ color:C.text2, fontSize:11, lineHeight:16, marginTop:4 },
  rhythmRight:{ alignItems:'flex-end', minWidth:72 },
  rhythmPrice:{ color:C.green, fontSize:13, fontWeight:'900' },
  rhythmDue:{ color:C.text3, fontSize:10, fontWeight:'900', textTransform:'uppercase', marginTop:3 },
  basketBox:{ backgroundColor:C.surface, borderWidth:1, borderColor:C.border, borderRadius:14, padding:14, marginBottom:14 },
  basketKicker:{ color:C.accent, fontSize:10, fontWeight:'900', textTransform:'uppercase', letterSpacing:0.5, marginBottom:3 },
  basketPill:{ backgroundColor:'rgba(124,106,255,0.12)', borderWidth:1, borderColor:'rgba(124,106,255,0.26)', borderRadius:12, paddingHorizontal:10, paddingVertical:7 },
  basketPillTxt:{ color:C.accent, fontWeight:'900', fontSize:13 },
  basketRow:{ flexDirection:'row', alignItems:'center', gap:10, paddingVertical:9, borderTopWidth:1, borderTopColor:C.border },
  basketCheck:{ width:26, height:26, borderRadius:99, backgroundColor:'rgba(124,106,255,0.12)', borderWidth:1, borderColor:'rgba(124,106,255,0.24)', alignItems:'center', justifyContent:'center' },
  basketCheckTxt:{ color:C.accent, fontSize:11, fontWeight:'900' },
  basketName:{ color:C.text, fontSize:13, fontWeight:'900' },
  basketMeta:{ color:C.text2, fontSize:11, marginTop:3 },
  basketPrice:{ color:C.green, fontSize:12, fontWeight:'900' },
  planBox:{ backgroundColor:C.card, borderWidth:1, borderColor:C.border, borderRadius:12, padding:14, marginBottom:14 },
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
  opportunityBox:{ backgroundColor:C.surface, borderWidth:1, borderColor:C.border, borderRadius:14, padding:14, marginBottom:14 },
  opportunityKicker:{ color:C.green, fontSize:10, fontWeight:'800', textTransform:'uppercase', letterSpacing:0.5, marginBottom:3 },
  opportunityPill:{ backgroundColor:'rgba(74,222,128,0.10)', borderWidth:1, borderColor:'rgba(74,222,128,0.24)', borderRadius:12, paddingHorizontal:10, paddingVertical:7 },
  opportunityPillTxt:{ color:C.green, fontWeight:'900', fontSize:13 },
  opportunityRow:{ flexDirection:'row', alignItems:'flex-start', gap:10, paddingVertical:10, borderTopWidth:1, borderTopColor:C.border },
  opportunityItem:{ color:C.text, fontSize:13, fontWeight:'900' },
  opportunityMeta:{ color:C.text2, fontSize:11, marginTop:3 },
  opportunityStore:{ color:C.accent, fontSize:11, fontWeight:'800', marginTop:4 },
  opportunitySave:{ alignItems:'flex-end', minWidth:78 },
  opportunitySaveVal:{ color:C.green, fontSize:15, fontWeight:'900' },
  opportunitySaveLbl:{ color:C.text3, fontSize:9, fontWeight:'800', marginTop:2, textTransform:'uppercase' },
  opportunitySwing:{ color:C.gold, fontSize:10, fontWeight:'800', marginTop:5 },
  storeIntelBox:{ backgroundColor:C.surface, borderWidth:1, borderColor:C.border, borderRadius:14, padding:14, marginBottom:14 },
  storeIntelKicker:{ color:C.accent, fontSize:10, fontWeight:'800', textTransform:'uppercase', letterSpacing:0.5, marginBottom:3 },
  storeIntelPill:{ backgroundColor:'rgba(124,106,255,0.12)', borderWidth:1, borderColor:'rgba(124,106,255,0.26)', borderRadius:12, minWidth:34, paddingHorizontal:10, paddingVertical:7, alignItems:'center' },
  storeIntelPillTxt:{ color:C.accent, fontWeight:'900', fontSize:13 },
  storeIntelRow:{ flexDirection:'row', alignItems:'flex-start', gap:10, paddingVertical:10, borderTopWidth:1, borderTopColor:C.border },
  storeRank:{ width:28, height:28, borderRadius:99, backgroundColor:'rgba(124,106,255,0.12)', borderWidth:1, borderColor:'rgba(124,106,255,0.25)', alignItems:'center', justifyContent:'center' },
  storeRankTxt:{ color:C.accent, fontSize:12, fontWeight:'900' },
  storeIntelName:{ color:C.text, fontSize:13, fontWeight:'900' },
  storeIntelMeta:{ color:C.text2, fontSize:11, marginTop:3 },
  storeIntelItem:{ color:C.gold, fontSize:11, fontWeight:'800', marginTop:4 },
  storeIntelSave:{ alignItems:'flex-end', minWidth:74 },
  storeIntelSaveVal:{ color:C.green, fontSize:14, fontWeight:'900' },
  storeIntelSaveLbl:{ color:C.text3, fontSize:9, fontWeight:'800', marginTop:2, textTransform:'uppercase' },
  loyaltyBox:{ backgroundColor:C.surface, borderWidth:1, borderColor:C.border, borderRadius:14, padding:14, marginBottom:14 },
  loyaltyKicker:{ color:C.green, fontSize:10, fontWeight:'900', textTransform:'uppercase', letterSpacing:0.5, marginBottom:3 },
  loyaltyPill:{ backgroundColor:'rgba(74,222,128,0.10)', borderWidth:1, borderColor:'rgba(74,222,128,0.24)', borderRadius:12, minWidth:34, paddingHorizontal:10, paddingVertical:7, alignItems:'center' },
  loyaltyPillTxt:{ color:C.green, fontWeight:'900', fontSize:13 },
  loyaltyRow:{ flexDirection:'row', alignItems:'flex-start', gap:10, paddingVertical:10, borderTopWidth:1, borderTopColor:C.border },
  loyaltyLine:{ flexDirection:'row', alignItems:'center', gap:8, marginBottom:4 },
  loyaltyStore:{ color:C.text, fontSize:13, fontWeight:'900', flex:1 },
  loyaltyStatus:{ color:C.gold, fontSize:10, fontWeight:'900', borderWidth:1, borderColor:'rgba(251,191,36,0.24)', backgroundColor:'rgba(251,191,36,0.08)', borderRadius:99, paddingHorizontal:8, paddingVertical:3, overflow:'hidden' },
  loyaltyAdvice:{ color:C.text2, fontSize:12, lineHeight:17 },
  loyaltyRight:{ alignItems:'flex-end', minWidth:72 },
  loyaltyValue:{ color:C.green, fontSize:13, fontWeight:'900' },
  loyaltyLabel:{ color:C.text3, fontSize:9, fontWeight:'900', textTransform:'uppercase', marginTop:3 },
  edgeBox:{ backgroundColor:C.surface, borderWidth:1, borderColor:C.border, borderRadius:14, padding:14, marginBottom:14 },
  edgeKicker:{ color:C.gold, fontSize:10, fontWeight:'900', textTransform:'uppercase', letterSpacing:0.5, marginBottom:3 },
  edgePill:{ backgroundColor:'rgba(251,191,36,0.10)', borderWidth:1, borderColor:'rgba(251,191,36,0.24)', borderRadius:12, minWidth:34, paddingHorizontal:10, paddingVertical:7, alignItems:'center' },
  edgePillTxt:{ color:C.gold, fontWeight:'900', fontSize:13 },
  edgeRow:{ paddingVertical:11, borderTopWidth:1, borderTopColor:C.border },
  edgeTop:{ flexDirection:'row', alignItems:'flex-start', justifyContent:'space-between', gap:10, marginBottom:9 },
  edgeName:{ color:C.text, fontSize:13, fontWeight:'900' },
  edgeAction:{ color:C.text2, fontSize:11, fontWeight:'800', marginTop:3 },
  edgeSwing:{ color:C.gold, fontSize:11, fontWeight:'900' },
  edgeScale:{ height:9, borderRadius:99, backgroundColor:C.surface2, borderWidth:1, borderColor:C.border, overflow:'visible', marginHorizontal:2 },
  edgeDealZone:{ height:'100%', borderRadius:99, backgroundColor:'rgba(74,222,128,0.24)' },
  edgeMarker:{ position:'absolute', top:-4, width:5, height:17, borderRadius:99, backgroundColor:C.accent },
  edgeLabels:{ flexDirection:'row', justifyContent:'space-between', gap:6, marginTop:7 },
  edgeLabel:{ color:C.text3, fontSize:10, fontWeight:'700' },
  autoAlertBox:{ backgroundColor:C.surface, borderWidth:1, borderColor:C.border, borderRadius:14, padding:14, marginBottom:14 },
  autoAlertTop:{ flexDirection:'row', alignItems:'center', justifyContent:'space-between', gap:12 },
  autoAlertKicker:{ color:C.gold, fontSize:10, fontWeight:'900', textTransform:'uppercase', letterSpacing:0.5, marginBottom:3 },
  autoAlertTitle:{ color:C.text, fontSize:17, fontWeight:'900', marginBottom:4 },
  autoAlertText:{ color:C.text2, fontSize:12, lineHeight:17 },
  autoAlertBtn:{ backgroundColor:C.accent, borderRadius:11, paddingHorizontal:14, paddingVertical:10 },
  autoAlertBtnDone:{ backgroundColor:'rgba(74,222,128,0.12)', borderWidth:1, borderColor:'rgba(74,222,128,0.26)' },
  autoAlertBtnTxt:{ color:'#fff', fontSize:12, fontWeight:'900' },
  autoAlertBtnTxtDone:{ color:C.green },
  learningBox:{ backgroundColor:C.surface, borderWidth:1, borderColor:C.border, borderRadius:14, padding:14, marginBottom:14 },
  learningKicker:{ color:C.text3, fontSize:10, fontWeight:'800', textTransform:'uppercase', letterSpacing:0.5, marginBottom:3 },
  learningPill:{ backgroundColor:C.surface2, borderWidth:1, borderColor:C.border, borderRadius:12, minWidth:34, paddingHorizontal:10, paddingVertical:7, alignItems:'center' },
  learningPillTxt:{ color:C.text2, fontWeight:'900', fontSize:13 },
  learningIntro:{ color:C.text2, fontSize:12, lineHeight:17, marginBottom:6 },
  learningRow:{ flexDirection:'row', alignItems:'center', gap:10, paddingVertical:9, borderTopWidth:1, borderTopColor:C.border },
  learningName:{ color:C.text, fontSize:13, fontWeight:'900' },
  learningMeta:{ color:C.text2, fontSize:11, marginTop:3 },
  learningNeed:{ color:C.accent, fontSize:11, fontWeight:'900' },
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
  checkBox:{ backgroundColor:C.card, borderWidth:1, borderColor:C.border, borderRadius:12, padding:14, marginBottom:14 },
  checkTitle:{ color:C.text, fontSize:18, fontWeight:'900', marginBottom:10 },
  checkInputs:{ flexDirection:'row', gap:8 },
  liveCheckBtn:{ backgroundColor:C.accent, borderRadius:11, paddingVertical:11, alignItems:'center', marginTop:10 },
  liveCheckBtnTxt:{ color:'#fff', fontSize:12, fontWeight:'900' },
  decisionBox:{ marginTop:12, borderWidth:1, borderRadius:12, padding:12 },
  liveResultBox:{ marginTop:10, borderWidth:1, borderRadius:12, padding:12, backgroundColor:C.surface2, borderColor:C.border },
  decisionGood:{ backgroundColor:'rgba(74,222,128,0.10)', borderColor:'rgba(74,222,128,0.28)' },
  decisionBad:{ backgroundColor:'rgba(255,107,107,0.09)', borderColor:'rgba(255,107,107,0.28)' },
  decisionMid:{ backgroundColor:'rgba(251,191,36,0.09)', borderColor:'rgba(251,191,36,0.28)' },
  decisionTop:{ flexDirection:'row', alignItems:'center', justifyContent:'space-between', gap:10, marginBottom:6 },
  decisionLabel:{ color:C.text, fontSize:18, fontWeight:'900' },
  decisionPrice:{ color:C.accent, fontSize:16, fontWeight:'900' },
  decisionText:{ color:C.text, fontSize:13, lineHeight:18 },
  decisionSub:{ color:C.text2, fontSize:11, marginTop:6, lineHeight:16 },
  noMatchText:{ color:C.text2, fontSize:12, marginTop:10 },
  tabEmptyBox:{ backgroundColor:C.surface, borderWidth:1, borderColor:C.border, borderRadius:14, padding:18, marginBottom:14, alignItems:'center' },
  tabEmptyTitle:{ color:C.text, fontSize:16, fontWeight:'900', marginBottom:5, textAlign:'center' },
  tabEmptyText:{ color:C.text2, fontSize:12, lineHeight:18, textAlign:'center' },
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
  card:{ backgroundColor:C.card, borderWidth:1, borderColor:C.border, borderRadius:12, padding:14 },
  cardHeader:{ flexDirection:'row', alignItems:'flex-start', gap:10, marginBottom:12 },
  itemName:{ color:C.text, fontSize:15, fontWeight:'800', lineHeight:20 },
  itemMeta:{ color:C.text3, fontSize:11, marginTop:4 },
  signalPill:{ backgroundColor:'rgba(124,106,255,0.12)', borderWidth:1, borderColor:'rgba(124,106,255,0.24)', borderRadius:99, paddingHorizontal:9, paddingVertical:4 },
  signalTxt:{ color:C.accent, fontSize:10, fontWeight:'800' },
  itemConfidenceRow:{ flexDirection:'row', alignItems:'center', gap:8, marginBottom:10 },
  itemConfidencePill:{ borderWidth:1, borderRadius:99, paddingHorizontal:8, paddingVertical:3, backgroundColor:C.surface2, borderColor:C.border },
  itemConfidenceGood:{ backgroundColor:'rgba(74,222,128,0.10)', borderColor:'rgba(74,222,128,0.24)' },
  itemConfidenceMid:{ backgroundColor:'rgba(251,191,36,0.10)', borderColor:'rgba(251,191,36,0.24)' },
  itemConfidenceLow:{ backgroundColor:C.surface2, borderColor:C.border },
  itemConfidenceTxt:{ color:C.text2, fontSize:10, fontWeight:'900' },
  itemConfidenceMeta:{ color:C.text3, fontSize:10, fontWeight:'700', flex:1 },
  priceGrid:{ flexDirection:'row', justifyContent:'space-between', backgroundColor:C.surface2, borderRadius:10, padding:12, gap:8 },
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
