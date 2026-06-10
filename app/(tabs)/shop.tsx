import { useEffect, useMemo, useState } from 'react';
import AsyncStorage from '@react-native-async-storage/async-storage';
import { Ionicons } from '@expo/vector-icons';
import { router } from 'expo-router';
import {
  ActivityIndicator,
  Alert,
  KeyboardAvoidingView,
  Platform,
  ScrollView,
  StyleSheet,
  Text,
  TextInput,
  TouchableOpacity,
  View,
} from 'react-native';
import { getGuestSessionId, getUserToken, useAuth } from '../../stores/authStore';
import { useTheme } from '../../stores/themeStore';
import { API } from '../../config/api';
const STORAGE_KEY = 'receiptai_shop_list_v1';

type PriceMatch = {
  item_name?: string;
  lowest_price?: number;
  usual_price?: number;
  avoid_above_price?: number;
  cheapest_store?: string;
  last_bought_date?: string;
  cheapest_receipt_id?: string | number;
  cheapest_line_index?: string | number;
  last_receipt_id?: string | number;
  last_line_index?: string | number;
  recent_events?: {
    receipt_id?: string | number;
    line_index?: string | number;
    store?: string;
    date?: string;
    compare_price?: number;
    unit?: string;
  }[];
};

type ShopItem = {
  id: string;
  name: string;
  checked: boolean;
  loading?: boolean;
  error?: string;
  match?: PriceMatch | null;
};

const n = (value: any) => Number.parseFloat(String(value ?? '')) || 0;
const money = (value: any) => `$${n(value).toFixed(2)}`;

function unitLabel(match?: PriceMatch | null) {
  const unit = (match?.recent_events || []).find(event => event.unit)?.unit;
  if (!unit || unit === 'each') return 'each';
  return `/${unit}`;
}

function compactDate(value?: string) {
  if (!value) return '';
  return value.replace(/^2026-/, '').replace(/^2025-/, '');
}

function cleanItemName(value: string) {
  return value.trim().replace(/\s+/g, ' ');
}

function splitAddedItems(value: string) {
  return value
    .split(/[,;\n]/)
    .map(cleanItemName)
    .filter(Boolean);
}

export default function ShopScreen() {
  const { colors: C } = useTheme();
  const { user } = useAuth();
  const s = useMemo(() => createStyles(C), [C]);
  const [input, setInput] = useState('');
  const [items, setItems] = useState<ShopItem[]>([]);
  const [quickItems, setQuickItems] = useState<string[]>([]);
  const [loadingQuick, setLoadingQuick] = useState(false);

  useEffect(() => {
    loadList();
    loadQuickItems();
    // The loaders intentionally run when the signed-in/guest owner changes.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [user?.id]);

  useEffect(() => {
    AsyncStorage.setItem(STORAGE_KEY, JSON.stringify(items.map(item => ({
      id: item.id,
      name: item.name,
      checked: item.checked,
    })))).catch(() => {});
  }, [items]);

  async function authContext() {
    const token = getUserToken();
    const guestId = getGuestSessionId();
    const isGuest = !!guestId || user?.is_guest || user?.isGuest || token === 'guest';
    const headers: any = {};
    if (!isGuest && token) headers.Authorization = `Bearer ${token}`;
    return { headers, guestId: isGuest ? (guestId || user?.id || '') : '' };
  }

  async function loadList() {
    try {
      const raw = await AsyncStorage.getItem(STORAGE_KEY);
      const saved = raw ? JSON.parse(raw) : [];
      if (!Array.isArray(saved)) return;
      const next = saved
        .filter(item => item?.name)
        .map(item => ({ id: item.id || `${Date.now()}_${Math.random()}`, name: item.name, checked: !!item.checked, loading: true }));
      setItems(next);
      next.forEach(item => refreshItem(item.id, item.name));
    } catch {}
  }

  async function loadQuickItems() {
    if (!user) return;
    setLoadingQuick(true);
    try {
      const { headers, guestId } = await authContext();
      const url = guestId
        ? `${API}/price-memory?session_id=${encodeURIComponent(guestId)}&limit=16`
        : `${API}/price-memory?limit=16`;
      const res = await fetch(url, { headers });
      const data = await res.json();
      if (!res.ok || !data.success) return;
      setQuickItems((data.items || []).map((item: any) => item.item_name).filter(Boolean).slice(0, 12));
    } catch {
      setQuickItems([]);
    } finally {
      setLoadingQuick(false);
    }
  }

  async function lookupItem(name: string): Promise<PriceMatch | null> {
    const { headers, guestId } = await authContext();
    const params = new URLSearchParams({ item: name });
    if (guestId) params.set('session_id', guestId);
    const res = await fetch(`${API}/price-memory/search?${params.toString()}`, { headers });
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || 'Could not check price memory.');
    return (data.matches || [])[0] || null;
  }

  async function refreshItem(id: string, name: string) {
    setItems(prev => prev.map(item => item.id === id ? { ...item, loading: true, error: '', match: item.match ?? null } : item));
    try {
      const match = await lookupItem(name);
      setItems(prev => prev.map(item => item.id === id ? { ...item, loading: false, match, error: '' } : item));
    } catch (e: any) {
      setItems(prev => prev.map(item => item.id === id ? { ...item, loading: false, error: e.message || 'Check failed' } : item));
    }
  }

  function addItems(source = input) {
    const names = splitAddedItems(source);
    if (!names.length) return;
    setInput('');
    const existing = new Set(items.map(item => item.name.toLowerCase()));
    const nextItems = names
      .filter(name => !existing.has(name.toLowerCase()))
      .map(name => ({ id: `${Date.now()}_${Math.random().toString(36).slice(2, 8)}`, name, checked: false, loading: true }));
    if (!nextItems.length) {
      Alert.alert('Already in list', 'That item is already on today\'s list.');
      return;
    }
    setItems(prev => [...nextItems, ...prev]);
    nextItems.forEach(item => refreshItem(item.id, item.name));
  }

  function toggleItem(id: string) {
    setItems(prev => prev.map(item => item.id === id ? { ...item, checked: !item.checked } : item));
  }

  function removeItem(id: string) {
    setItems(prev => prev.filter(item => item.id !== id));
  }

  function clearBought() {
    setItems(prev => prev.filter(item => !item.checked));
  }

  function openReceipt(match?: PriceMatch | null) {
    const receiptId = match?.cheapest_receipt_id || match?.last_receipt_id || (match?.recent_events || []).find(event => event.receipt_id)?.receipt_id;
    if (!receiptId) return;
    router.push({ pathname: '/receipts', params: { receiptId: String(receiptId) } });
  }

  const remaining = items.filter(item => !item.checked).length;
  const known = items.filter(item => item.match).length;

  return (
    <KeyboardAvoidingView style={s.screen} behavior={Platform.OS === 'ios' ? 'padding' : undefined}>
      <ScrollView contentContainerStyle={s.content} keyboardShouldPersistTaps="handled" showsVerticalScrollIndicator={false}>
        <View style={s.hero}>
          <View>
            <Text style={s.kicker}>Before you shop</Text>
            <Text style={s.title}>Today List</Text>
            <Text style={s.sub}>Add items, then buy with your receipt price memory beside you.</Text>
          </View>
          <View style={s.heroPill}>
            <Text style={s.heroPillText}>{remaining} left</Text>
          </View>
        </View>

        <View style={s.inputCard}>
          <View style={s.inputRow}>
            <TextInput
              value={input}
              onChangeText={setInput}
              placeholder="Add cilantro, milk, goat keema..."
              placeholderTextColor={C.text3}
              style={s.input}
              returnKeyType="done"
              onSubmitEditing={() => addItems()}
            />
            <TouchableOpacity style={[s.addBtn, !input.trim() && s.addBtnDisabled]} onPress={() => addItems()} disabled={!input.trim()}>
              <Ionicons name="add" size={22} color="#fff" />
            </TouchableOpacity>
          </View>
          <Text style={s.inputHint}>Tip: separate multiple items with commas.</Text>
        </View>

        <View style={s.summaryRow}>
          <View style={s.summaryTile}>
            <Text style={s.summaryValue}>{items.length}</Text>
            <Text style={s.summaryLabel}>Items</Text>
          </View>
          <View style={s.summaryTile}>
            <Text style={[s.summaryValue, { color: C.accent3 }]}>{known}</Text>
            <Text style={s.summaryLabel}>With history</Text>
          </View>
          <View style={s.summaryTile}>
            <Text style={[s.summaryValue, { color: C.green }]}>{items.length - remaining}</Text>
            <Text style={s.summaryLabel}>Done</Text>
          </View>
        </View>

        {quickItems.length || loadingQuick ? (
          <View style={s.quickBox}>
            <View style={s.sectionHead}>
              <Text style={s.sectionTitle}>Quick add from memory</Text>
              {loadingQuick ? <ActivityIndicator size="small" color={C.accent} /> : null}
            </View>
            <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={s.quickRow}>
              {quickItems.map(name => (
                <TouchableOpacity key={name} style={s.quickChip} onPress={() => addItems(name)} activeOpacity={0.82}>
                  <Text style={s.quickText} numberOfLines={1}>{name}</Text>
                </TouchableOpacity>
              ))}
            </ScrollView>
          </View>
        ) : null}

        <View style={s.listHead}>
          <Text style={s.sectionTitle}>Shopping list</Text>
          {items.some(item => item.checked) ? (
            <TouchableOpacity onPress={clearBought}>
              <Text style={s.clearText}>Clear done</Text>
            </TouchableOpacity>
          ) : null}
        </View>

        {!items.length ? (
          <View style={s.emptyBox}>
            <Ionicons name="basket-outline" size={32} color={C.accent} />
            <Text style={s.emptyTitle}>{"Build today's list"}</Text>
            <Text style={s.emptyText}>Add what you plan to buy. ReceiptAI will show compact price memory for every known item.</Text>
          </View>
        ) : (
          <View style={s.list}>
            {items.map(item => {
              const match = item.match;
              const found = !!match;
              const receiptId = match?.cheapest_receipt_id || match?.last_receipt_id || (match?.recent_events || []).find(event => event.receipt_id)?.receipt_id;
              const label = item.loading ? 'Checking' : found ? 'Best' : 'New';
              const labelColor = item.loading ? C.text3 : found ? C.accent3 : C.gold;
              const unit = unitLabel(match);
              const line = found
                ? `${money(match?.lowest_price)} ${unit} · ${match?.cheapest_store || 'Unknown store'} · avoid > ${money(match?.avoid_above_price)}`
                : item.error || 'No price history yet. Scan after buying to start memory.';
              const detail = found
                ? `last ${compactDate(match?.last_bought_date)} · usual ${money(match?.usual_price)}`
                : 'New item';
              return (
                <View key={item.id} style={[s.row, item.checked && s.rowDone]}>
                  <TouchableOpacity style={[s.check, item.checked && s.checkOn]} onPress={() => toggleItem(item.id)} activeOpacity={0.85}>
                    {item.checked ? <Ionicons name="checkmark" size={16} color="#06110A" /> : null}
                  </TouchableOpacity>
                  <View style={s.rowMain}>
                    <View style={s.rowTop}>
                      <Text style={[s.itemName, item.checked && s.itemDone]} numberOfLines={1}>{item.name}</Text>
                      <View style={[s.statusPill, { borderColor: labelColor, backgroundColor: `${labelColor}18` }]}>
                        <Text style={[s.statusText, { color: labelColor }]}>{label}</Text>
                      </View>
                    </View>
                    <Text style={s.priceLine} numberOfLines={1}>{line}</Text>
                    <Text style={s.detailLine} numberOfLines={1}>{detail}</Text>
                  </View>
                  <View style={s.rowActions}>
                    {item.loading ? <ActivityIndicator size="small" color={C.accent} /> : receiptId ? (
                      <TouchableOpacity style={s.iconBtn} onPress={() => openReceipt(match)}>
                        <Ionicons name="open-outline" size={16} color={C.accent} />
                      </TouchableOpacity>
                    ) : (
                      <TouchableOpacity style={s.iconBtn} onPress={() => refreshItem(item.id, item.name)}>
                        <Ionicons name="refresh-outline" size={16} color={C.text2} />
                      </TouchableOpacity>
                    )}
                    <TouchableOpacity style={s.iconBtn} onPress={() => removeItem(item.id)}>
                      <Ionicons name="close" size={16} color={C.text3} />
                    </TouchableOpacity>
                  </View>
                </View>
              );
            })}
          </View>
        )}
      </ScrollView>
    </KeyboardAvoidingView>
  );
}

const createStyles = (C: any) => StyleSheet.create({
  screen:{ flex:1, backgroundColor:C.bg },
  content:{ padding:16, paddingBottom:42 },
  hero:{ flexDirection:'row', justifyContent:'space-between', alignItems:'flex-start', gap:14, marginBottom:14 },
  kicker:{ color:C.accent3, fontSize:10, fontWeight:'900', textTransform:'uppercase', letterSpacing:0.8, marginBottom:5 },
  title:{ color:C.text, fontSize:28, lineHeight:33, fontWeight:'900', letterSpacing:0 },
  sub:{ color:C.text2, fontSize:13, lineHeight:19, marginTop:5, maxWidth:260 },
  heroPill:{ backgroundColor:'rgba(82,230,200,0.10)', borderWidth:1, borderColor:'rgba(82,230,200,0.24)', borderRadius:99, paddingHorizontal:12, paddingVertical:7 },
  heroPillText:{ color:C.accent3, fontSize:12, fontWeight:'900' },
  inputCard:{ backgroundColor:C.card, borderWidth:1, borderColor:C.border, borderRadius:18, padding:13, marginBottom:12, shadowColor:'#000', shadowOpacity:0.18, shadowRadius:14, shadowOffset:{width:0,height:8}, elevation:4 },
  inputRow:{ flexDirection:'row', alignItems:'center', gap:9 },
  input:{ flex:1, minHeight:46, backgroundColor:C.surface2, borderWidth:1, borderColor:C.border, borderRadius:14, color:C.text, paddingHorizontal:13, fontSize:14 },
  addBtn:{ width:46, height:46, borderRadius:15, backgroundColor:C.accent, alignItems:'center', justifyContent:'center', shadowColor:C.accent, shadowOpacity:0.3, shadowRadius:10, shadowOffset:{width:0,height:6}, elevation:3 },
  addBtnDisabled:{ opacity:0.38 },
  inputHint:{ color:C.text3, fontSize:11, marginTop:9 },
  summaryRow:{ flexDirection:'row', gap:9, marginBottom:12 },
  summaryTile:{ flex:1, backgroundColor:C.card, borderWidth:1, borderColor:C.border, borderRadius:14, padding:11 },
  summaryValue:{ color:C.text, fontSize:20, fontWeight:'900' },
  summaryLabel:{ color:C.text3, fontSize:10, marginTop:3, fontWeight:'800' },
  quickBox:{ backgroundColor:C.card, borderWidth:1, borderColor:C.border, borderRadius:16, padding:12, marginBottom:14 },
  sectionHead:{ flexDirection:'row', alignItems:'center', justifyContent:'space-between', marginBottom:8 },
  sectionTitle:{ color:C.text3, fontSize:10, fontWeight:'900', textTransform:'uppercase', letterSpacing:0.7 },
  quickRow:{ gap:8, paddingRight:4 },
  quickChip:{ backgroundColor:C.surface2, borderWidth:1, borderColor:C.border, borderRadius:99, paddingHorizontal:12, paddingVertical:8, maxWidth:180 },
  quickText:{ color:C.text2, fontSize:12, fontWeight:'800' },
  listHead:{ flexDirection:'row', alignItems:'center', justifyContent:'space-between', marginBottom:8 },
  clearText:{ color:C.accent, fontSize:12, fontWeight:'900' },
  list:{ backgroundColor:C.card, borderWidth:1, borderColor:C.border, borderRadius:18, overflow:'hidden', shadowColor:'#000', shadowOpacity:0.18, shadowRadius:14, shadowOffset:{width:0,height:8}, elevation:4 },
  row:{ flexDirection:'row', alignItems:'center', gap:10, paddingHorizontal:12, paddingVertical:11, borderBottomWidth:1, borderBottomColor:C.border },
  rowDone:{ opacity:0.58 },
  check:{ width:24, height:24, borderRadius:8, borderWidth:1, borderColor:C.border, backgroundColor:C.surface2, alignItems:'center', justifyContent:'center' },
  checkOn:{ backgroundColor:C.green, borderColor:C.green },
  rowMain:{ flex:1, minWidth:0 },
  rowTop:{ flexDirection:'row', alignItems:'center', gap:8, marginBottom:3 },
  itemName:{ flex:1, color:C.text, fontSize:14, fontWeight:'900' },
  itemDone:{ textDecorationLine:'line-through', color:C.text2 },
  statusPill:{ borderWidth:1, borderRadius:99, paddingHorizontal:8, paddingVertical:3 },
  statusText:{ fontSize:9, fontWeight:'900', textTransform:'uppercase' },
  priceLine:{ color:C.text2, fontSize:11, lineHeight:15, fontWeight:'700' },
  detailLine:{ color:C.text3, fontSize:10, lineHeight:14, marginTop:1 },
  rowActions:{ flexDirection:'row', alignItems:'center', gap:5 },
  iconBtn:{ width:30, height:30, borderRadius:10, backgroundColor:C.surface2, borderWidth:1, borderColor:C.border, alignItems:'center', justifyContent:'center' },
  emptyBox:{ backgroundColor:C.card, borderWidth:1, borderColor:C.border, borderRadius:18, padding:22, alignItems:'center', gap:8 },
  emptyTitle:{ color:C.text, fontSize:17, fontWeight:'900' },
  emptyText:{ color:C.text2, fontSize:12, lineHeight:18, textAlign:'center' },
});
