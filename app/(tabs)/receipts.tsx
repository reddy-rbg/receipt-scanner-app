import { useTheme } from '../../stores/themeStore';
import { useAuth, getUserToken, getGuestSessionId } from '../../stores/authStore';
import { DARK_COLORS } from '../../stores/themeStore';
import { useState, useEffect, useCallback } from 'react';
import {
  View, Text, ScrollView, TouchableOpacity, StyleSheet,
  ActivityIndicator, Modal, FlatList, TextInput, RefreshControl,
} from 'react-native';

const API = 'https://web-production-3605f4.up.railway.app';


const n = (v:any) => parseFloat(v)||0;

type Receipt = {
  id:number; store:string; date?:string; time?:string;
  address?:string; total?:number; total_savings?:number;
  items?:any[]; subtotal?:number; discount?:number;
  tax?:number; payment_method?:string; created_at?:string;
};

type ReceiptCategory = {
  key: string;
  label: string;
  icon: string;
};

const FILTER_TABS = [
  { key:'all',   label:'All' },
  { key:'store', label:'By Store' },
  { key:'category', label:'Category' },
  { key:'id',    label:'By ID' },
  { key:'month', label:'By Month' },
  { key:'year',  label:'By Year' },
  { key:'date',  label:'Date Range' },
  { key:'sort',  label:'Sort' },
];

const CATEGORIES: ReceiptCategory[] = [
  { key:'food',       label:'Food & Grocery',       icon:'🛒' },
  { key:'restaurant', label:'Restaurants',          icon:'🍽️' },
  { key:'garden',     label:'Gardening & Hardware', icon:'🌿' },
  { key:'medical',    label:'Hospital & Medical',   icon:'🏥' },
  { key:'pharmacy',   label:'Pharmacy & Health',    icon:'💊' },
  { key:'bank',       label:'Bank & Finance',       icon:'🏦' },
  { key:'fuel',       label:'Fuel & Auto',          icon:'⛽' },
  { key:'home',       label:'Home & Household',     icon:'🏠' },
  { key:'shopping',   label:'Retail Shopping',      icon:'🛍️' },
  { key:'other',      label:'Other',                icon:'🧾' },
];

function receiptSearchText(receipt: Receipt) {
  const itemText = (receipt.items || [])
    .map((item:any) => [item?.name, item?.item, item?.code].filter(Boolean).join(' '))
    .join(' ');

  return [
    receipt.store,
    receipt.address,
    receipt.payment_method,
    itemText,
  ].filter(Boolean).join(' ').toLowerCase();
}

function matchAny(text: string, words: string[]) {
  return words.some(word => text.includes(word));
}

function getReceiptCategory(receipt: Receipt): ReceiptCategory {
  const text = receiptSearchText(receipt);

  if (matchAny(text, ['bank', 'atm', 'withdrawal', 'deposit', 'credit union', 'chase', 'wells fargo', 'bank of america', 'capital one', 'payment receipt'])) {
    return CATEGORIES.find(c => c.key === 'bank')!;
  }
  if (matchAny(text, ['hospital', 'clinic', 'medical center', 'urgent care', 'doctor', 'dental', 'dentist', 'labcorp', 'quest diagnostics', 'patient'])) {
    return CATEGORIES.find(c => c.key === 'medical')!;
  }
  if (matchAny(text, ['cvs', 'walgreens', 'pharmacy', 'rx ', 'medicine', 'vitamin', 'health'])) {
    return CATEGORIES.find(c => c.key === 'pharmacy')!;
  }
  if (matchAny(text, ['lowe', 'home depot', 'tractor supply', 'garden', 'mulch', 'soil', 'plant', 'rose', 'fertilizer', 'hardware', 'paint', 'lumber'])) {
    return CATEGORIES.find(c => c.key === 'garden')!;
  }
  if (matchAny(text, ['restaurant', 'cafe', 'pizza', 'burger', 'taco', 'mcdonald', 'starbucks', 'subway', 'doordash', 'uber eats', 'grubhub'])) {
    return CATEGORIES.find(c => c.key === 'restaurant')!;
  }
  if (matchAny(text, ['walmart', 'kroger', 'aldi', 'costco', 'sam club', 'target grocery', 'supermarket', 'market', 'grocery', 'food', 'seafood', 'milk', 'bread', 'egg'])) {
    return CATEGORIES.find(c => c.key === 'food')!;
  }
  if (matchAny(text, ['shell', 'exxon', 'chevron', 'bp ', 'circle k', 'speedway', 'gas', 'fuel', 'auto', 'oil change', 'tire'])) {
    return CATEGORIES.find(c => c.key === 'fuel')!;
  }
  if (matchAny(text, ['ikea', 'bed bath', 'household', 'cleaner', 'detergent', 'furniture', 'kitchen'])) {
    return CATEGORIES.find(c => c.key === 'home')!;
  }
  if (matchAny(text, ['amazon', 'best buy', 'tj maxx', 'marshalls', 'mall', 'clothing', 'shoes', 'apparel', 'electronics'])) {
    return CATEGORIES.find(c => c.key === 'shopping')!;
  }

  return CATEGORIES.find(c => c.key === 'other')!;
}

const MONTHS = [
  {label:'January',val:'01'},{label:'February',val:'02'},{label:'March',val:'03'},
  {label:'April',val:'04'},{label:'May',val:'05'},{label:'June',val:'06'},
  {label:'July',val:'07'},{label:'August',val:'08'},{label:'September',val:'09'},
  {label:'October',val:'10'},{label:'November',val:'11'},{label:'December',val:'12'},
];

const YEARS = ['2026','2025','2024','2023'];

const SORTS = [
  {label:'Newest first',val:'newest'},
  {label:'Oldest first',val:'oldest'},
  {label:'Highest total',val:'highest'},
  {label:'Lowest total',val:'lowest'},
  {label:'Store A–Z',val:'store'},
  {label:'Most savings',val:'savings'},
];

export default function ReceiptsScreen() {
  const { colors: C } = useTheme();
  const s = createStyles(C);
  const { user } = useAuth(); // reactive theme updates
  const [all, setAll]         = useState<Receipt[]>([]);
  const [shown, setShown]     = useState<Receipt[]>([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [activeTab, setActiveTab]   = useState('all');
  const [filterInfo, setFilterInfo] = useState('');

  // Filter inputs
  const [storeQ,  setStoreQ]  = useState('');
  const [idQ,     setIdQ]     = useState('');
  const [month,   setMonth]   = useState('01');
  const [monthY,  setMonthY]  = useState('2026');
  const [year,    setYear]    = useState('2026');
  const [fromD,   setFromD]   = useState('');
  const [toD,     setToD]     = useState('');
  const [sortVal, setSortVal] = useState('newest');
  const [category, setCategory] = useState('food');

  // Modal
  const [selected,    setSelected]    = useState<Receipt|null>(null);
  const [deleteMode,  setDeleteMode]  = useState(false);
  const [deleted,     setDeleted]     = useState(false);

  useEffect(() => { load(); }, [user?.id, user?.guest_session_id]);

  async function load() {
    try {
      if (!user) {
        setAll([]);
        setShown([]);
        setLoading(false);
        setRefreshing(false);
        return;
      }
      const guestId = getGuestSessionId();
      const isGuestMode = !!guestId || user?.isGuest || user?.is_guest || user?.token === 'guest';
      const url = isGuestMode
        ? `${API}/guest/receipts?session_id=${encodeURIComponent(guestId || user?.id || 'guest')}`
        : `${API}/receipts`;
      const headers:any = {};
      const token = getUserToken();
      if (!isGuestMode && token) headers['Authorization'] = `Bearer ${token}`;
      const res  = await fetch(url, { headers });
      const data = await res.json();
      const recs = data.receipts || [];
      setAll(recs);
      applySort(recs, 'newest');
      setFilterInfo('');
    } catch {}
    finally { setLoading(false); setRefreshing(false); }
  }

  const onRefresh = useCallback(() => { setRefreshing(true); load(); }, []);

  // ── FILTER FUNCTIONS ──
  function applySort(recs: Receipt[], s: string) {
    const r = [...recs];
    switch (s) {
      case 'newest':  r.sort((a,b) => new Date(b.created_at||0).getTime() - new Date(a.created_at||0).getTime()); break;
      case 'oldest':  r.sort((a,b) => new Date(a.created_at||0).getTime() - new Date(b.created_at||0).getTime()); break;
      case 'highest': r.sort((a,b) => (b.total||0) - (a.total||0)); break;
      case 'lowest':  r.sort((a,b) => (a.total||0) - (b.total||0)); break;
      case 'store':   r.sort((a,b) => (a.store||'').localeCompare(b.store||'')); break;
      case 'savings': r.sort((a,b) => (b.total_savings||0) - (a.total_savings||0)); break;
    }
    return r;
  }

  function showResults(recs: Receipt[], label: string) {
    const sorted = applySort(recs, 'newest');
    setShown(sorted);
    setFilterInfo(label);
  }

  function filterByStore() {
    if (!storeQ.trim()) { load(); return; }
    const q = storeQ.trim().toLowerCase();
    const r = all.filter(x => receiptSearchText(x).includes(q) || String(x.id).includes(q) || getReceiptCategory(x).label.toLowerCase().includes(q));
    showResults(r, `Search: "${storeQ.trim()}"`);
  }

  function filterByCategory(value = category) {
    const selectedCategory = CATEGORIES.find(c => c.key === value) || CATEGORIES[CATEGORIES.length - 1];
    const r = all.filter(x => getReceiptCategory(x).key === selectedCategory.key);
    showResults(r, `${selectedCategory.icon} ${selectedCategory.label}`);
  }

  function filterById() {
    const id = parseInt(idQ.trim());
    if (!id) { load(); return; }
    const r = all.filter(x => x.id === id);
    showResults(r, `Receipt #${id}`);
  }

  function filterByMonth() {
    const r = all.filter(x => {
      if (!x.created_at) return false;
      const d = new Date(x.created_at);
      return String(d.getMonth()+1).padStart(2,'0') === month && String(d.getFullYear()) === monthY;
    });
    const mName = MONTHS.find(m => m.val === month)?.label || month;
    showResults(r, `${mName} ${monthY}`);
  }

  function filterByYear() {
    const r = all.filter(x => x.created_at && String(new Date(x.created_at).getFullYear()) === year);
    showResults(r, `Year ${year}`);
  }

  async function filterByDateRange() {
    if (!fromD || !toD) return;
    try {
      const res  = await fetch(`${API}/receipts/date?from_date=${fromD}&to_date=${toD}T23:59:59`);
      const data = await res.json();
      showResults(data.receipts || [], `${fromD} → ${toD}`);
    } catch {}
  }

  function doSort() {
    const sorted = applySort(all, sortVal);
    const label  = SORTS.find(s => s.val === sortVal)?.label || sortVal;
    setShown(sorted);
    setFilterInfo(`Sorted: ${label}`);
  }

  function applyFilter() {
    switch (activeTab) {
      case 'store': filterByStore(); break;
      case 'category': filterByCategory(); break;
      case 'id':    filterById();    break;
      case 'month': filterByMonth(); break;
      case 'year':  filterByYear();  break;
      case 'date':  filterByDateRange(); break;
      case 'sort':  doSort();        break;
      default:      load();
    }
  }

  async function deleteReceipt() {
    if (!selected) return;
    try {
      await fetch(`${API}/receipts/${selected.id}`, { method:'DELETE' });
      setDeleted(true);
      setAll(prev => prev.filter(r => r.id !== selected.id));
      setShown(prev => prev.filter(r => r.id !== selected.id));
      setTimeout(() => { setSelected(null); setDeleted(false); setDeleteMode(false); }, 1600);
    } catch {}
  }

  // ── FILTER PANEL CONTENT ──
  function renderFilterPanel() {
    switch (activeTab) {
      case 'store':
        return (
          <View style={s.filterRow}>
            <TextInput style={s.filterInput} placeholder="Search store, item, category..." placeholderTextColor={C.text3} value={storeQ} onChangeText={setStoreQ} onSubmitEditing={applyFilter} returnKeyType="search" autoCorrect={false}/>
            <TouchableOpacity style={s.filterBtn} onPress={applyFilter}><Text style={s.filterBtnTxt}>Search</Text></TouchableOpacity>
          </View>
        );
      case 'category':
        return (
          <View>
            <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={{gap:6,paddingBottom:8}}>
              {CATEGORIES.map(cat => (
                <TouchableOpacity
                  key={cat.key}
                  style={[s.selectChip, category===cat.key && s.selectChipActive]}
                  onPress={() => {
                    setCategory(cat.key);
                    filterByCategory(cat.key);
                  }}
                  activeOpacity={0.8}
                >
                  <Text style={[s.selectChipTxt, category===cat.key && s.selectChipTxtActive]}>{cat.icon} {cat.label}</Text>
                </TouchableOpacity>
              ))}
            </ScrollView>
            <Text style={s.filterHint}>Categories are detected from store names and scanned receipt items.</Text>
          </View>
        );
      case 'id':
        return (
          <View style={s.filterRow}>
            <TextInput style={s.filterInput} placeholder="Enter receipt ID..." placeholderTextColor={C.text3} value={idQ} onChangeText={setIdQ} onSubmitEditing={applyFilter} keyboardType="numeric" returnKeyType="search" autoCorrect={false}/>
            <TouchableOpacity style={s.filterBtn} onPress={applyFilter}><Text style={s.filterBtnTxt}>Find</Text></TouchableOpacity>
          </View>
        );
      case 'month':
        return (
          <View>
            <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={{gap:6,paddingBottom:8}}>
              {MONTHS.map(m => (
                <TouchableOpacity key={m.val} style={[s.selectChip, month===m.val && s.selectChipActive]} onPress={() => setMonth(m.val)}>
                  <Text style={[s.selectChipTxt, month===m.val && s.selectChipTxtActive]}>{m.label}</Text>
                </TouchableOpacity>
              ))}
            </ScrollView>
            <View style={s.filterRow}>
              <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={{gap:6}}>
                {YEARS.map(y => (
                  <TouchableOpacity key={y} style={[s.selectChip, monthY===y && s.selectChipActive]} onPress={() => setMonthY(y)}>
                    <Text style={[s.selectChipTxt, monthY===y && s.selectChipTxtActive]}>{y}</Text>
                  </TouchableOpacity>
                ))}
              </ScrollView>
              <TouchableOpacity style={s.filterBtn} onPress={applyFilter}><Text style={s.filterBtnTxt}>Filter</Text></TouchableOpacity>
            </View>
          </View>
        );
      case 'year':
        return (
          <View style={s.filterRow}>
            <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={{gap:6}}>
              {YEARS.map(y => (
                <TouchableOpacity key={y} style={[s.selectChip, year===y && s.selectChipActive]} onPress={() => setYear(y)}>
                  <Text style={[s.selectChipTxt, year===y && s.selectChipTxtActive]}>{y}</Text>
                </TouchableOpacity>
              ))}
            </ScrollView>
            <TouchableOpacity style={s.filterBtn} onPress={applyFilter}><Text style={s.filterBtnTxt}>Filter</Text></TouchableOpacity>
          </View>
        );
      case 'date':
        return (
          <View>
            <View style={s.filterRow}>
              <Text style={s.filterLabel}>From</Text>
              <TextInput style={s.filterInput} placeholder="YYYY-MM-DD" placeholderTextColor={C.text3} value={fromD} onChangeText={setFromD} autoCorrect={false}/>
            </View>
            <View style={s.filterRow}>
              <Text style={s.filterLabel}>To</Text>
              <TextInput style={s.filterInput} placeholder="YYYY-MM-DD" placeholderTextColor={C.text3} value={toD} onChangeText={setToD} autoCorrect={false}/>
              <TouchableOpacity style={s.filterBtn} onPress={applyFilter}><Text style={s.filterBtnTxt}>Filter</Text></TouchableOpacity>
            </View>
          </View>
        );
      case 'sort':
        return (
          <View>
            <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={{gap:6,paddingBottom:8}}>
              {SORTS.map(so => (
                <TouchableOpacity key={so.val} style={[s.selectChip, sortVal===so.val && s.selectChipActive]} onPress={() => setSortVal(so.val)}>
                  <Text style={[s.selectChipTxt, sortVal===so.val && s.selectChipTxtActive]}>{so.label}</Text>
                </TouchableOpacity>
              ))}
            </ScrollView>
            <TouchableOpacity style={[s.filterBtn,{alignSelf:'flex-start'}]} onPress={applyFilter}><Text style={s.filterBtnTxt}>Apply Sort</Text></TouchableOpacity>
          </View>
        );
      default:
        return (
          <TouchableOpacity style={[s.filterBtn,{alignSelf:'flex-start'}]} onPress={load}>
            <Text style={s.filterBtnTxt}>↻  Refresh</Text>
          </TouchableOpacity>
        );
    }
  }

  return (
    <View style={s.screen}>

      {/* ── TOP SECTION (fixed) ── */}
      <View style={s.top}>

        {/* Filter Tabs */}
        <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={s.tabsRow}>
          {FILTER_TABS.map(tab => (
            <TouchableOpacity
              key={tab.key}
              style={[s.tab, activeTab===tab.key && s.tabActive]}
              onPress={() => {
                setActiveTab(tab.key);
                if (tab.key === 'all') load();
              }}
            >
              <Text style={[s.tabTxt, activeTab===tab.key && s.tabTxtActive]}>{tab.label}</Text>
            </TouchableOpacity>
          ))}
        </ScrollView>

        {/* Filter Panel */}
        <View style={s.filterPanel}>
          {renderFilterPanel()}
        </View>

        {/* Results info */}
        {filterInfo !== '' && (
          <View style={s.infoRow}>
            <Text style={s.infoTxt}><Text style={{color:C.text,fontWeight:'600'}}>{shown.length}</Text> receipt{shown.length!==1?'s':''} · {filterInfo}</Text>
            <TouchableOpacity onPress={load}><Text style={s.clearTxt}>Clear</Text></TouchableOpacity>
          </View>
        )}

        <Text style={s.countLbl}>{shown.length} receipt{shown.length!==1?'s':''}</Text>
      </View>

      {/* ── LIST (fills remaining space) ── */}
      {loading ? (
        <View style={s.loadingWrap}>
          <ActivityIndicator color={C.accent} size="large"/>
        </View>
      ) : (
        <FlatList
          data={shown}
          keyExtractor={r => String(r.id)}
          style={s.list}
          contentContainerStyle={s.listContent}
          refreshControl={<RefreshControl refreshing={refreshing} onRefresh={onRefresh} tintColor={C.accent}/>}
          renderItem={({item:r}) => (
            <TouchableOpacity
              style={s.card}
              onPress={() => { setSelected(r); setDeleted(false); setDeleteMode(false); }}
              activeOpacity={0.8}
            >
              <View style={{flex:1}}>
                <View style={s.cardTopLine}>
                  <Text style={s.idBadge}>#{r.id}</Text>
                  <View style={s.categoryBadge}>
                    <Text style={s.categoryBadgeTxt}>{getReceiptCategory(r).icon} {getReceiptCategory(r).label}</Text>
                  </View>
                </View>
                <Text style={s.storeName}>{r.store}</Text>
                <Text style={s.meta} numberOfLines={2}>
                  {[r.date, r.time, r.address].filter(Boolean).join(' · ')}
                </Text>
              </View>
              <View style={{alignItems:'flex-end',flexShrink:0}}>
                <Text style={s.total}>${n(r.total).toFixed(2)}</Text>
                {n(r.total_savings)>0 && (
                  <View style={s.pill}>
                    <Text style={s.pillTxt}>Saved ${r.total_savings!.toFixed(2)}</Text>
                  </View>
                )}
              </View>
              <Text style={s.arrow}>›</Text>
            </TouchableOpacity>
          )}
          ListEmptyComponent={
            <View style={s.empty}>
              <Text style={s.emptyEmoji}>🔍</Text>
              <Text style={s.emptyTxt}>{filterInfo ? 'No receipts match this filter.' : 'No receipts yet. Scan your first!'}</Text>
              {filterInfo !== '' && <TouchableOpacity onPress={load}><Text style={s.clearTxt}>Clear filter</Text></TouchableOpacity>}
            </View>
          }
        />
      )}

      {/* ── DETAIL MODAL ── */}
      <Modal visible={!!selected} animationType="slide" presentationStyle="pageSheet" onRequestClose={() => setSelected(null)}>
        <View style={s.modal}>
          <View style={s.modalHeader}>
            <View style={{flex:1}}>
              <Text style={s.modalStore}>{selected?.store||'Unknown Store'}</Text>
              {selected ? (
                <View style={[s.categoryBadge, { alignSelf:'flex-start', marginBottom:8 }]}>
                  <Text style={s.categoryBadgeTxt}>{getReceiptCategory(selected).icon} {getReceiptCategory(selected).label}</Text>
                </View>
              ) : null}
              <Text style={s.modalMeta}>
                {[selected?.id&&`#${selected.id}`, selected?.date, selected?.time, selected?.address].filter(Boolean).join('  ·  ')}
              </Text>
            </View>
            <TouchableOpacity onPress={() => setSelected(null)} style={s.closeBtn}>
              <Text style={s.closeBtnTxt}>✕</Text>
            </TouchableOpacity>
          </View>

          {deleted ? (
            <View style={s.deletedBox}>
              <Text style={{fontSize:48,marginBottom:14}}>🗑</Text>
              <Text style={s.deletedTitle}>Receipt Deleted</Text>
              <Text style={s.deletedSub}>Permanently removed.</Text>
            </View>
          ) : (
            <ScrollView contentContainerStyle={s.modalBody}>
              {deleteMode && (
                <View style={s.deleteConfirm}>
                  <Text style={s.deleteConfirmTxt}>Delete this receipt? This cannot be undone.</Text>
                  <View style={{flexDirection:'row',gap:10,marginTop:10}}>
                    <TouchableOpacity style={s.btnYes} onPress={deleteReceipt}>
                      <Text style={{color:'#fff',fontWeight:'600',fontSize:13}}>Yes, Delete</Text>
                    </TouchableOpacity>
                    <TouchableOpacity style={s.btnNo} onPress={() => setDeleteMode(false)}>
                      <Text style={{color:C.text2,fontSize:13}}>Cancel</Text>
                    </TouchableOpacity>
                  </View>
                </View>
              )}

              <Text style={s.sectionTitle}>Items Purchased</Text>
              {(selected?.items||[]).map((item:any,i:number) => {
                const neg = item.price < 0;
                const ps  = neg ? `-$${Math.abs(item.price).toFixed(2)}` : `$${n(item.price).toFixed(2)}`;
                return (
                  <View key={i} style={s.mItem}>
                    <View style={{flex:1}}>
                      {item.code ? <Text style={s.mCode}>{item.code}</Text> : null}
                      <Text style={s.mName}>{item.name}</Text>
                      {item.quantity>1&&item.unit_price ? <Text style={s.mDetail}>{item.quantity} × ${n(item.unit_price).toFixed(2)}</Text> : null}
                    </View>
                    <Text style={[s.mPrice,{color:neg?C.green:C.text}]}>{ps}</Text>
                  </View>
                );
              })}

              <Text style={[s.sectionTitle,{marginTop:20}]}>Summary</Text>
              <View style={s.totalsBox}>
                {n(selected?.subtotal)>0 && <View style={s.tRow}><Text style={s.tLbl}>Subtotal</Text><Text style={s.tVal}>${n(selected?.subtotal).toFixed(2)}</Text></View>}
                {n(selected?.discount)>0 && <View style={s.tRow}><Text style={s.tLbl}>Discount</Text><Text style={[s.tVal,{color:C.green}]}>-${n(selected?.discount).toFixed(2)}</Text></View>}
                {n(selected?.tax)>0      && <View style={s.tRow}><Text style={s.tLbl}>Tax</Text><Text style={s.tVal}>${n(selected?.tax).toFixed(2)}</Text></View>}
                <View style={[s.tRow,s.tFinal]}>
                  <Text style={s.tFinalLbl}>Total Paid</Text>
                  <Text style={s.tFinalAmt}>${n(selected?.total).toFixed(2)}</Text>
                </View>
              </View>

              {n(selected?.total_savings)>0 && (
                <View style={s.savingsBanner}>
                  <Text style={s.savingsBannerTxt}>🎉  You saved ${selected!.total_savings!.toFixed(2)} on this trip!</Text>
                </View>
              )}
              {selected?.payment_method ? <Text style={s.payment}>Paid with {selected.payment_method}</Text> : null}

              {!deleteMode && (
                <TouchableOpacity style={s.deleteBtn} onPress={() => setDeleteMode(true)}>
                  <Text style={s.deleteBtnTxt}>🗑  Delete Receipt</Text>
                </TouchableOpacity>
              )}
            </ScrollView>
          )}
        </View>
      </Modal>
    </View>
  );
}

const createStyles = (C: typeof DARK_COLORS) => StyleSheet.create({
  screen:{ flex:1, backgroundColor:C.bg },

  top:{ backgroundColor:C.bg, paddingTop:8 },

  // Filter tabs
  tabsRow:{ flexDirection:'row', gap:6, paddingHorizontal:16, paddingVertical:6 },
  tab:{ backgroundColor:C.surface2, borderWidth:1, borderColor:C.border, borderRadius:99, paddingHorizontal:14, paddingVertical:7, flexShrink:0 },
  tabActive:{ backgroundColor:'rgba(124,106,255,0.15)', borderColor:'rgba(124,106,255,0.4)' },
  tabTxt:{ color:C.text2, fontSize:12, fontWeight:'500' },
  tabTxtActive:{ color:C.accent },

  // Filter panel
  filterPanel:{ paddingHorizontal:16, paddingVertical:10 },
  filterRow:{ flexDirection:'row', gap:8, alignItems:'center', marginBottom:6 },
  filterLabel:{ color:C.text3, fontSize:12, minWidth:36 },
  filterInput:{ flex:1, backgroundColor:C.surface2, borderWidth:1, borderColor:C.border, borderRadius:11, padding:10, paddingHorizontal:14, color:C.text, fontSize:13 },
  filterBtn:{ backgroundColor:C.accent, borderRadius:11, paddingHorizontal:16, paddingVertical:10 },
  filterBtnTxt:{ color:'#fff', fontWeight:'600', fontSize:13 },
  filterHint:{ color:C.text3, fontSize:11, lineHeight:15, marginTop:2 },

  // Select chips (month/year/sort)
  selectChip:{ backgroundColor:C.surface2, borderWidth:1, borderColor:C.border, borderRadius:99, paddingHorizontal:14, paddingVertical:6, flexShrink:0 },
  selectChipActive:{ backgroundColor:'rgba(124,106,255,0.15)', borderColor:'rgba(124,106,255,0.4)' },
  selectChipTxt:{ color:C.text2, fontSize:12 },
  selectChipTxtActive:{ color:C.accent },

  // Results info bar
  infoRow:{ flexDirection:'row', justifyContent:'space-between', alignItems:'center', paddingHorizontal:16, paddingVertical:6, backgroundColor:'rgba(124,106,255,0.06)', borderTopWidth:1, borderTopColor:'rgba(124,106,255,0.15)', borderBottomWidth:1, borderBottomColor:'rgba(124,106,255,0.15)' },
  infoTxt:{ color:C.text2, fontSize:12, flex:1 },
  clearTxt:{ color:C.accent, fontSize:12, textDecorationLine:'underline', paddingLeft:8 },
  countLbl:{ color:C.text3, fontSize:11, paddingHorizontal:16, paddingBottom:4, letterSpacing:0.4 },

  // List
  list:{ flex:1 },
  listContent:{ padding:16, paddingTop:4, paddingBottom:40 },
  loadingWrap:{ flex:1, alignItems:'center', justifyContent:'center' },

  // Receipt cards
  card:{ backgroundColor:C.surface, borderWidth:1, borderColor:C.border, borderRadius:16, padding:16, marginBottom:10, flexDirection:'row', alignItems:'center', gap:10 },
  cardTopLine:{ flexDirection:'row', alignItems:'center', gap:6, flexWrap:'wrap', marginBottom:4 },
  idBadge:{ color:C.text3, fontSize:9, fontFamily:'monospace', letterSpacing:0.5, marginBottom:3 },
  categoryBadge:{ backgroundColor:'rgba(124,106,255,0.10)', borderWidth:1, borderColor:'rgba(124,106,255,0.22)', borderRadius:99, paddingHorizontal:8, paddingVertical:2 },
  categoryBadgeTxt:{ color:C.accent, fontSize:10, fontWeight:'600' },
  storeName:{ color:C.text, fontSize:14, fontWeight:'700', marginBottom:3 },
  meta:{ color:C.text2, fontSize:11 },
  total:{ color:C.text, fontSize:18, fontWeight:'800', letterSpacing:-0.5 },
  pill:{ backgroundColor:'rgba(74,222,128,0.1)', borderWidth:1, borderColor:'rgba(74,222,128,0.2)', borderRadius:99, paddingHorizontal:8, paddingVertical:2, marginTop:4 },
  pillTxt:{ color:C.green, fontSize:10 },
  arrow:{ color:C.text3, fontSize:22, marginLeft:2 },

  empty:{ alignItems:'center', paddingTop:60, gap:10 },
  emptyEmoji:{ fontSize:36 },
  emptyTxt:{ color:C.text3, fontSize:13, textAlign:'center' },

  // Modal
  modal:{ flex:1, backgroundColor:C.bg },
  modalHeader:{ flexDirection:'row', alignItems:'flex-start', padding:20, borderBottomWidth:1, borderBottomColor:C.border, backgroundColor:C.surface },
  modalStore:{ color:C.text, fontSize:20, fontWeight:'800', marginBottom:4 },
  modalMeta:{ color:C.text2, fontSize:12 },
  closeBtn:{ backgroundColor:C.surface2, borderWidth:1, borderColor:C.border, borderRadius:99, width:32, height:32, alignItems:'center', justifyContent:'center' },
  closeBtnTxt:{ color:C.text2, fontSize:15 },
  modalBody:{ padding:20, paddingBottom:40 },
  sectionTitle:{ color:C.text3, fontSize:10, fontWeight:'600', letterSpacing:1, textTransform:'uppercase', marginBottom:10 },
  mItem:{ flexDirection:'row', justifyContent:'space-between', alignItems:'flex-start', paddingVertical:9, borderBottomWidth:1, borderBottomColor:C.border, gap:10 },
  mCode:{ color:C.text3, fontSize:9, fontFamily:'monospace', marginBottom:2 },
  mName:{ color:C.text, fontSize:13 },
  mDetail:{ color:C.text2, fontSize:10, marginTop:3 },
  mPrice:{ fontSize:13, fontWeight:'600' },
  totalsBox:{ backgroundColor:C.surface2, borderRadius:12, padding:14 },
  tRow:{ flexDirection:'row', justifyContent:'space-between', paddingVertical:4 },
  tLbl:{ color:C.text2, fontSize:13 },
  tVal:{ color:C.text, fontSize:13, fontWeight:'500' },
  tFinal:{ borderTopWidth:1, borderTopColor:C.border, marginTop:6, paddingTop:10 },
  tFinalLbl:{ color:C.text, fontSize:15, fontWeight:'700' },
  tFinalAmt:{ color:C.accent, fontSize:15, fontWeight:'800' },
  savingsBanner:{ marginTop:12, padding:10, backgroundColor:'rgba(74,222,128,0.1)', borderWidth:1, borderColor:'rgba(74,222,128,0.25)', borderRadius:10 },
  savingsBannerTxt:{ color:C.green, fontWeight:'600', fontSize:13, textAlign:'center' },
  payment:{ color:C.text3, fontSize:11, textAlign:'center', marginTop:10 },
  deleteBtn:{ marginTop:20, padding:14, backgroundColor:'rgba(255,107,107,0.08)', borderWidth:1, borderColor:'rgba(255,107,107,0.2)', borderRadius:12, alignItems:'center' },
  deleteBtnTxt:{ color:C.red, fontSize:14, fontWeight:'500' },
  deleteConfirm:{ backgroundColor:'rgba(255,107,107,0.07)', borderWidth:1, borderColor:'rgba(255,107,107,0.22)', borderRadius:12, padding:14, marginBottom:16 },
  deleteConfirmTxt:{ color:C.text, fontSize:13 },
  btnYes:{ flex:1, padding:10, backgroundColor:C.red, borderRadius:10, alignItems:'center' },
  btnNo:{ flex:1, padding:10, backgroundColor:C.surface2, borderWidth:1, borderColor:C.border, borderRadius:10, alignItems:'center' },
  deletedBox:{ flex:1, alignItems:'center', justifyContent:'center', padding:40 },
  deletedTitle:{ color:C.text, fontSize:20, fontWeight:'700', marginBottom:6 },
  deletedSub:{ color:C.text2, fontSize:13 },
});
