import * as ImagePicker from 'expo-image-picker';
import * as ImageManipulator from 'expo-image-manipulator';
import * as DocumentPicker from 'expo-document-picker';
import * as FileSystem from 'expo-file-system/legacy';
import { getGuestSessionId, getUserToken, useAuth } from '../../stores/authStore';
import { useTheme } from '../../stores/themeStore';
import { API } from '../../config/api';
import { appLogger } from '../../utils/logger';
import { useState, useEffect, useCallback } from 'react';
import { router, useFocusEffect } from 'expo-router';
import { Ionicons } from '@expo/vector-icons';
import {
  ActivityIndicator, Alert, Modal,
  Image,
  ScrollView,
  StyleSheet,
  Text,
  TextInput,
  TouchableOpacity,
  View,
  Platform,
} from 'react-native';

function getDisplayName(user: any) {
  if (!user) return 'Guest';
  if (user.is_guest) return 'Guest';
  return user.name || user.email?.split('@')[0] || 'User';
}

function getInitial(user: any) {
  if (!user) return 'G';
  if (user.is_guest) return 'G';
  const value = user.name || user.email || 'User';
  return value.trim().charAt(0).toUpperCase();
}

// Claude's 5 MB limit is after base64 encoding, so keep raw images well below it.
const MAX_UPLOAD_BYTES = 3.5 * 1024 * 1024;
const MAX_SCAN_IMAGE_PAGES = 8;
const MAX_COMPARISON_ITEMS = 10;
const INVOICE_ITEM_PAGE_SIZE = 25;
const FALLBACK_COLORS = {
  bg:'#06070D',surface:'#0D0F18',surface2:'#151824',card:'#10131F',
  border:'rgba(238,242,255,0.10)',
  accent:'#7C6DFF',accent2:'#E85D97',accent3:'#52E6C8',
  text:'#F5F3FF',text2:'#AAAEC3',text3:'#71768C',
  green:'#42D987',red:'#FF6378',
};

function getMime(uri:string, isPDF:boolean=false){
  if(isPDF) return 'application/pdf';
  const e=uri.split('.').pop()?.toLowerCase();
  if(e==='png')  return 'image/png';
  if(e==='webp') return 'image/webp';
  return 'image/jpeg';
}
function isHeicImage(uri: string) {
  const ext = uri.split('?')[0].split('.').pop()?.toLowerCase();
  return ext === 'heic' || ext === 'heif';
}
function uploadFileName(uri: string, fallback: string) {
  const name = uri.split('?')[0].split('/').pop() || fallback;
  return isHeicImage(name) ? name.replace(/\.(heic|heif)$/i, '.jpg') : name;
}

async function appendUploadFile(
  formData: FormData,
  field: string,
  uri: string,
  name: string,
  type: string,
) {
  if (Platform.OS === 'web') {
    const response = await fetch(uri);
    if (!response.ok) throw new Error('Could not read the selected receipt image.');
    const sourceBlob = await response.blob();
    const blob = sourceBlob.type === type
      ? sourceBlob
      : sourceBlob.slice(0, sourceBlob.size, type);
    formData.append(field, blob, name);
    return;
  }
  formData.append(field, { uri, name, type } as any);
}
const n=(v:any)=>parseFloat(v)||0;
const money=(v:any)=>`$${n(v).toFixed(2)}`;
const hasVisibleMoney=(v:any)=>v !== null && v !== undefined && v !== '' && n(v) > 0;
const INDIAN_GROCERY_TERMS = [
  'india mart', 'bharath bazaar', 'bharat bazaar', 'nwa bharath', 'nwa bharat',
  'asian amigo', 'indian grocery', 'desi', 'methi', 'amla', 'okra', 'bhindi',
  'goat', 'mutton', 'lamb', 'keema', 'kheema', 'qeema', 'dal', 'dhal', 'atta',
  'rice', 'masala', 'paneer', 'ghee', 'curry', 'squash', 'chana', 'garbanzo',
  'brinjal', 'eggplant', 'cilantro', 'coriander', 'dahi', 'curd', 'naan',
];
function scanCategory(receipt:any) {
  const itemText = (receipt?.items || []).map((item:any) => [item?.name, item?.item, item?.code].filter(Boolean).join(' ')).join(' ');
  const text = [receipt?.store, receipt?.address, receipt?.payment_method, itemText].filter(Boolean).join(' ').toLowerCase();
  if (['wholesale', 'invoice', 'sold to', 'ship to', 'tobacco license', 'vape', 'nicotine', 'e-liquid', 'eliquid', 'gummies', 'smoke shop', 'warehouse'].some(w => text.includes(w))) return 'Wholesale Inventory';
  if (['bank', 'atm', 'withdrawal', 'deposit', 'credit union', 'chase', 'wells fargo', 'bank of america', 'capital one'].some(w => text.includes(w))) return 'Bank & Finance';
  if (['hospital', 'clinic', 'urgent care', 'doctor', 'dental', 'patient', 'medical'].some(w => text.includes(w))) return 'Hospital & Medical';
  if (['cvs', 'walgreens', 'pharmacy', 'rx ', 'medicine', 'vitamin'].some(w => text.includes(w))) return 'Pharmacy & Health';
  if (['lowe', 'home depot', 'tractor supply', 'garden', 'mulch', 'soil', 'plant', 'fertilizer', 'hardware', 'paint', 'lumber'].some(w => text.includes(w))) return 'Gardening & Hardware';
  if (['restaurant', 'cafe', 'pizza', 'burger', 'taco', 'starbucks', 'subway'].some(w => text.includes(w))) return 'Restaurants';
  if (['walmart', 'wal mart', 'wal*mart', 'kroger', 'aldi', 'costco', 'supermarket', 'market', 'grocery', 'food', 'milk', 'bread', 'egg', ...INDIAN_GROCERY_TERMS].some(w => text.includes(w))) return 'Food & Grocery';
  if (['shell', 'exxon', 'chevron', 'bp ', 'gas', 'fuel', 'auto', 'tire'].some(w => text.includes(w))) return 'Fuel & Auto';
  return 'Other';
}

async function fileSize(uri: string) {
  try {
    if (Platform.OS === 'web') {
      const response = await fetch(uri);
      return response.ok ? (await response.blob()).size : 0;
    }
    const info = await FileSystem.getInfoAsync(uri);
    return info.exists && typeof info.size === 'number' ? info.size : 0;
  } catch {
    return 0;
  }
}

async function compressReceiptImage(uri: string) {
  let currentUri = uri;
  let currentSize = await fileSize(currentUri);

  // Preserve ordinary browser file/blob URIs. The backend performs the final
  // Claude-specific crop, resize, compression, and visual-token optimization.
  if (Platform.OS === 'web' && currentSize > 0 && currentSize <= MAX_UPLOAD_BYTES) {
    return { uri: currentUri, compressed: false, size: currentSize };
  }

  try {
    const manipulated = await ImageManipulator.manipulateAsync(
      currentUri,
      [],
      { compress: 0.82, format: ImageManipulator.SaveFormat.JPEG }
    );
    currentUri = manipulated.uri;
    currentSize = await fileSize(currentUri);
  } catch {
    if (isHeicImage(currentUri)) throw new Error('Could not convert this HEIC image. Please choose a JPEG/PNG export or retake the photo.');
  }

  if (!currentSize || currentSize <= MAX_UPLOAD_BYTES) {
    return { uri: currentUri, compressed: currentUri !== uri, size: currentSize };
  }

  const attempts = [
    { width: 1800, compress: 0.72 },
    { width: 1500, compress: 0.62 },
    { width: 1200, compress: 0.52 },
    { width: 1000, compress: 0.45 },
    { width: 800, compress: 0.35 },
    { width: 650, compress: 0.3 },
  ];

  for (const attempt of attempts) {
    const manipulated = await ImageManipulator.manipulateAsync(
      currentUri,
      [{ resize: { width: attempt.width } }],
      { compress: attempt.compress, format: ImageManipulator.SaveFormat.JPEG }
    );
    currentUri = manipulated.uri;
    currentSize = await fileSize(currentUri);
    if (!currentSize || currentSize <= MAX_UPLOAD_BYTES) break;
  }

  return { uri: currentUri, compressed: currentUri !== uri, size: currentSize };
}

function itemAmountForCompare(item: any) {
  const unit = String(item?.unit || 'each').toLowerCase().trim();
  const qty = n(item?.quantity) || 1;
  const unitPrice = n(item?.unit_price);
  if ((unit && unit !== 'each' && unitPrice > 0) || (qty > 1 && unitPrice > 0)) return unitPrice;
  return n(item?.price);
}

function isWeightedUnit(unit: any) {
  const value = String(unit || '').toLowerCase().trim();
  return Boolean(value && value !== 'each');
}

function eventAmountForCompare(event: any, currentItem?: any) {
  const direct = n(event?.compare_price);
  if (direct > 0) return direct;
  const eventUnit = String(event?.unit || '').toLowerCase().trim();
  const currentUnit = String(currentItem?.unit || '').toLowerCase().trim();
  const qty = n(event?.quantity);
  const currentQty = n(currentItem?.quantity) || 1;
  const currentIsWeighted = isWeightedUnit(currentUnit);
  const currentNeedsUnitPrice = currentIsWeighted || currentQty > 1;
  const unitPrice = n(event?.unit_price);
  if (unitPrice > 0 && (isWeightedUnit(eventUnit) || currentNeedsUnitPrice || qty > 1)) return unitPrice;
  const line = n(event?.price);
  if (line > 0 && qty > 0 && (isWeightedUnit(eventUnit) || currentIsWeighted || currentQty > 1)) return line / qty;
  if (currentNeedsUnitPrice) return 0;
  return line;
}

function itemUnitLabel(item: any) {
  const unit = String(item?.unit || 'each').toLowerCase().trim();
  const qty = n(item?.quantity) || 1;
  if (qty > 1 && (!unit || unit === 'each')) return ' each';
  return unit && unit !== 'each' ? `/${unit}` : '';
}

function itemMeaningTokens(value: any) {
  const stopwords = new Set(['each', 'ea', 'item', 'items', 'fresh', 'large', 'small', 'medium', 'food', 'non', 'the', 'and', 'with', 'good', 'price', 'current', 'buy', 'now', 'for', 'this', 'that', 'should']);
  return String(value || '')
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, ' ')
    .split(/\s+/)
    .filter(token => token.length > 2 && !/^\d+(\.\d+)?$/.test(token) && !stopwords.has(token));
}

function eventTimeValue(event: any) {
  const raw = event?.date || event?.purchase_date || event?.created_at || event?.receipt_created_at || '';
  const parsed = Date.parse(String(raw));
  return Number.isNaN(parsed) ? 0 : parsed;
}

function shouldMergeContinuationLine(previous: any, current: any, following?: any) {
  const previousUnit = String(previous?.unit || 'each').toLowerCase().trim();
  if (previousUnit && previousUnit !== 'each') return false;
  const prevTokens = itemMeaningTokens(previous?.name || previous?.item);
  const currentTokens = itemMeaningTokens(current?.name || current?.item);
  if (prevTokens.length < 2 || currentTokens.length === 0 || currentTokens.length > 3) return false;
  const continuationTerms = new Set([
    'icecream', 'ice', 'cream', 'badam', 'kulfi', 'cake', 'candy',
    'biscuit', 'biscuits', 'cookie', 'cookies',
  ]);
  const hasDescriptor = currentTokens.some(token => continuationTerms.has(token) || /^\d+$/.test(token));
  if (!hasDescriptor) return false;
  const currentPrice = n(current?.price);
  const followingPrice = n(following?.price);
  return currentPrice <= 0 || (followingPrice > 0 && Math.abs(currentPrice - followingPrice) < 0.01) || currentTokens.length <= 2;
}

function normalizeScannedReceipt(receipt: any) {
  const sourceItems = receipt?.items || [];
  const items:any[] = [];
  for (let i = 0; i < sourceItems.length; i += 1) {
    const current = { ...sourceItems[i] };
    const next = sourceItems[i + 1];
    const following = sourceItems[i + 2];
    const currentName = String(current.name || current.item || '');
    const weightedUnit = String(current.unit || 'each').toLowerCase().trim();
    const badamTail = currentName.match(/^(.*?)(\bVL\s+Badam\s+Carnival.*)$/i);
    if (badamTail && weightedUnit && weightedUnit !== 'each' && next && /ice\s*cream|icecream/i.test(String(next.name || next.item || ''))) {
      current.name = badamTail[1].trim();
      current.normalized_name = String(current.name).toLowerCase();
      items.push(current);
      const mergedIceCream = {
        ...next,
        name: `${badamTail[2].trim()} ${next.name || next.item || ''}`.trim(),
        normalized_name: `${badamTail[2].trim()} ${next.name || next.item || ''}`.trim().toLowerCase(),
        merged_from_split_lines: true,
      };
      items.push(mergedIceCream);
      i += 1;
      continue;
    }
    if (/^VL\s+Badam\s+Carnival$/i.test(currentName.trim()) && next && /ice\s*cream|icecream/i.test(String(next.name || next.item || ''))) {
      const mergedIceCream = {
        ...current,
        name: `${currentName.trim()} ${next.name || next.item || ''}`.trim(),
        normalized_name: `${currentName.trim()} ${next.name || next.item || ''}`.trim().toLowerCase(),
        price: n(current.price) > 0 ? current.price : next.price,
        quantity: n(current.quantity) > 0 ? current.quantity : next.quantity,
        unit: current.unit || next.unit || 'each',
        unit_price: n(current.unit_price) > 0 ? current.unit_price : next.unit_price,
        merged_from_split_lines: true,
      };
      items.push(mergedIceCream);
      i += 1;
      continue;
    }
    if (next && shouldMergeContinuationLine(current, next, following)) {
      current.name = `${current.name || current.item || ''} ${next.name || next.item || ''}`.trim();
      current.normalized_name = String(current.name).toLowerCase();
      current.merged_from_split_lines = true;
      i += 1;
    }
    items.push(current);
  }
  return { ...receipt, items };
}

function isWeakFragmentMatch(scannedName: any, matchedName: any) {
  const scanned = itemMeaningTokens(scannedName);
  const matched = itemMeaningTokens(matchedName);
  if (!scanned.length || !matched.length) return true;
  const overlap = scanned.filter(token => matched.includes(token)).length;
  if (scanned.length === 1) return overlap < 1;
  if (scanned.length === 2) return overlap < 2;
  return overlap < 2 || overlap / scanned.length < 0.6;
}

function itemPageCount(items: any[] = []) {
  return Math.max(1, Math.ceil(items.length / INVOICE_ITEM_PAGE_SIZE));
}

function itemPageItems(items: any[] = [], page: number) {
  const start = page * INVOICE_ITEM_PAGE_SIZE;
  return items.slice(start, start + INVOICE_ITEM_PAGE_SIZE);
}

export default function ScanScreen(){
  const { colors: C } = useTheme();
  const s = createStyles(C);
  const [uri,setUri]             = useState<string|null>(null);
  const [imageUris,setImageUris] = useState<string[]>([]);
  const [isPDF,setIsPDF]         = useState(false);
  const [loading,setLoading]     = useState(false);
  const [result,setResult]       = useState<any>(null);
  const [priceInsights,setPriceInsights] = useState<any[]>([]);
  const [priceLoading,setPriceLoading] = useState(false);
  const [fileStatus,setFileStatus] = useState('');
  const [scanError,setScanError] = useState('');
  const [duplicate,setDuplicate] = useState('');
  const [duplicateReceiptId,setDuplicateReceiptId] = useState<string | number | null>(null);
  const [stats,setStats]         = useState({receipts:0,spent:0,saved:0});
  const [resultItemPage,setResultItemPage] = useState(0);
  const [previousReceipt,setPreviousReceipt] = useState<any>(null);
  const [previousReceiptItem,setPreviousReceiptItem] = useState<any>(null);
  const [previousReceiptLoading,setPreviousReceiptLoading] = useState(false);
  const [reviewModalVisible, setReviewModalVisible] = useState(false);
  const [reviewSavedId, setReviewSavedId] = useState<string | number | null>(null);
  const [reviewItems, setReviewItems] = useState<any[]>([]);
  const [reviewEdits, setReviewEdits] = useState<Record<number, string>>({});
  const [reviewSaving, setReviewSaving] = useState(false);

  // Re-check login every time this screen is focused
  // This fixes the issue where sign out doesn't update the scan screen
  const [isLoggedIn, setIsLoggedIn] = useState(false);

  const { user } = useAuth();
  const displayName = getDisplayName(user);
  const profileInitial = getInitial(user);

  useFocusEffect(
    useCallback(() => {
      // Allow access if logged in OR guest
      const isAuth = user !== null;
      setIsLoggedIn(isAuth);
      if (isAuth) loadStats();
    }, [user])
  );

  useEffect(()=>{ loadStats(); },[]);

  async function loadStats(){
    try{
      const token = await getUserToken();
      const headers:any = {'Content-Type':'application/json'};
      const guestId = getGuestSessionId();
      if(!guestId && token && token !== 'guest') headers['Authorization'] = `Bearer ${token}`;
      const summaryUrl = guestId ? `${API}/summary?session_id=${encodeURIComponent(guestId)}` : `${API}/summary`;
      const res=await fetch(summaryUrl,{headers});
      const d=await res.json();
      setStats({
        receipts: d.total_receipts||0,
        spent:    d.total_spent||0,
        saved:    d.total_saved||0,
      });
    }catch{}
  }

  async function comparisonHeaders() {
    const token = await getUserToken();
    const headers:any = {'Content-Type':'application/json'};
    if(user && !user.is_guest && token && token !== 'guest') {
      headers.Authorization = `Bearer ${token}`;
    }
    return headers;
  }

  async function loadOwnerReceipts() {
    const headers = await comparisonHeaders();
    const guestSessionId = user?.is_guest || user?.token === 'guest' ? (user.guest_session_id || user.id) : '';
    const url = guestSessionId
      ? `${API}/guest/receipts?session_id=${encodeURIComponent(guestSessionId)}`
      : `${API}/receipts`;
    const res = await fetch(url, { headers });
    if (!res.ok) throw new Error('Could not load previous receipt.');
    const data = await res.json();
    return data.receipts || [];
  }

  async function openPreviousReceipt(row:any) {
    if (!row?.previousReceiptId) {
      Alert.alert('Previous receipt', 'No previous receipt link was returned for this comparison.');
      return;
    }
    setPreviousReceiptLoading(true);
    try {
      const receipts = await loadOwnerReceipts();
      const receipt = receipts.find((r:any) => String(r.id) === String(row.previousReceiptId));
      if (!receipt) {
        Alert.alert('Previous receipt', 'I could not find that previous receipt in your saved receipts.');
        return;
      }
      setPreviousReceipt(receipt);
      const itemByLine = (receipt.items || [])[Number(row.previousLineIndex)];
      const itemByName = (receipt.items || []).find((item:any) => !isWeakFragmentMatch(row.item, item?.name || item?.item));
      setPreviousReceiptItem(itemByLine || itemByName || null);
    } catch(e:any) {
      Alert.alert('Previous receipt', e.message || 'Could not open previous receipt.');
    } finally {
      setPreviousReceiptLoading(false);
    }
  }

  async function loadPriceInsights(receipt:any, savedId:any) {
    const normalizedReceipt = normalizeScannedReceipt(receipt);
    const items = (normalizedReceipt?.items || [])
      .filter((item:any) => item && n(item.price) > 0 && String(item.name || '').trim() && !String(item.name || '').toLowerCase().includes('discount'))
      .slice(0, MAX_COMPARISON_ITEMS);

    if (!items.length || !user) {
      setPriceInsights([]);
      return;
    }

    setPriceLoading(true);
    try {
      const headers = await comparisonHeaders();
      const guestSessionId = user?.is_guest || user?.token === 'guest' ? (user.guest_session_id || user.id) : '';
      const rows = await Promise.all(items.map(async (item:any) => {
        const params = new URLSearchParams({ item: item.name || item.item || '' });
        if (guestSessionId) params.set('session_id', guestSessionId);
        const res = await fetch(`${API}/price-memory/search?${params.toString()}`, { headers });
        if (!res.ok) return null;
        const data = await res.json();
        const match = (data.matches || [])[0];
        const current = itemAmountForCompare(item);
        if (!match || current <= 0 || isWeakFragmentMatch(item.name || item.item, match.item_name)) {
          return {
            item: item.name || item.item,
            current,
            unitLabel: itemUnitLabel(item),
            status: 'new',
            message: 'No previous price found yet.',
          };
        }

        const allMatchedEvents = match.price_events || match.recent_events || [];
        const previousEvents = savedId
          ? allMatchedEvents.filter((event:any) => String(event.receipt_id || '') !== String(savedId || ''))
          : allMatchedEvents.length <= 1
            ? []
            : allMatchedEvents;
        const comparablePreviousEvents = previousEvents
          .map((event:any) => ({ ...event, compareAmount: eventAmountForCompare(event, item) }))
          .filter((event:any) => event.compareAmount > 0);
        if (!comparablePreviousEvents.length) {
          return {
            item: item.name || item.item,
            current,
            unitLabel: itemUnitLabel(item),
            status: 'new',
            matched: match.item_name,
            message: 'First saved price for this item.',
          };
        }

        const previousBuyEvent = comparablePreviousEvents.reduce((latest:any, event:any) => {
          const latestTime = eventTimeValue(latest);
          const eventTime = eventTimeValue(event);
          return eventTime >= latestTime ? event : latest;
        });
        const previousBuy = previousBuyEvent.compareAmount;
        const previousLow = Math.min(...comparablePreviousEvents.map((event:any) => event.compareAmount));
        const previousHigh = Math.max(...comparablePreviousEvents.map((event:any) => event.compareAmount));
        const diff = current - previousBuy;
        const status = Math.abs(diff) < 0.01 ? 'same' : diff < 0 ? 'lower' : 'higher';
        return {
          item: item.name || item.item,
          current,
          unitLabel: itemUnitLabel(item),
          matched: match.item_name,
          previousBuy,
          previousLow,
          previousHigh,
          diff,
          status,
          previousStore: previousBuyEvent.store,
          previousReceiptId: previousBuyEvent.receipt_id,
          previousLineIndex: previousBuyEvent.line_index,
        };
      }));
      setPriceInsights(rows.filter(Boolean));
    } catch {
      setPriceInsights([]);
    } finally {
      setPriceLoading(false);
    }
  }

  async function pickImage(){
    const p=await ImagePicker.requestMediaLibraryPermissionsAsync();
    if(!p.granted){Alert.alert('Permission needed','Allow photo access.');return;}
    const r=await ImagePicker.launchImageLibraryAsync({
      mediaTypes:['images'],
      quality:0.85,
      allowsMultipleSelection:true,
      selectionLimit:MAX_SCAN_IMAGE_PAGES,
    });
    if(!r.canceled&&r.assets?.length){
      setFileStatus('');
      setScanError('');
      const prepared = await Promise.all(r.assets.slice(0, MAX_SCAN_IMAGE_PAGES).map(asset => compressReceiptImage(asset.uri)));
      const preparedUris = prepared.map(item => item.uri);
      setUri(preparedUris[0]);
      setImageUris(preparedUris);
      setIsPDF(false);
      setResult(null);
      setResultItemPage(0);
      setPriceInsights([]);
      setDuplicate('');
      const compressedCount = prepared.filter(item => item.compressed).length;
      const pageText = preparedUris.length > 1 ? `${preparedUris.length} pages selected. They will be scanned together.` : '1 page selected.';
      setFileStatus(compressedCount ? `${pageText} ${compressedCount} image(s) compressed for scanning.` : pageText);
    }
  }

  async function takePhoto(){
    if (imageUris.length >= MAX_SCAN_IMAGE_PAGES) {
      Alert.alert('Page limit reached', `You can scan up to ${MAX_SCAN_IMAGE_PAGES} photo pages at one time.`);
      return;
    }
    const p=await ImagePicker.requestCameraPermissionsAsync();
    if(!p.granted){Alert.alert('Permission needed','Allow camera access.');return;}
    const r=await ImagePicker.launchCameraAsync({quality:0.85});
    if(!r.canceled&&r.assets[0]){
      setFileStatus('');
      setScanError('');
      const prepared = await compressReceiptImage(r.assets[0].uri);
      setUri(prepared.uri);
      const nextUris = [...imageUris, prepared.uri].slice(0, MAX_SCAN_IMAGE_PAGES);
      setImageUris(nextUris);
      setIsPDF(false);
      setResult(null);
      setResultItemPage(0);
      setPriceInsights([]);
      setDuplicate('');
      const pageText = nextUris.length > 1 ? `${nextUris.length} pages ready. Take another page or scan all pages together.` : '1 page ready. Take another photo if this receipt has more pages.';
      setFileStatus(prepared.compressed ? `${pageText} Image compressed to ${(prepared.size / (1024 * 1024)).toFixed(1)} MB.` : pageText);
    }
  }

  async function pickPDF(){
    const result = await DocumentPicker.getDocumentAsync({
      type: 'application/pdf',
      copyToCacheDirectory: true,
      multiple: false,
    });
    if (result.canceled || !result.assets?.[0]) return;
    const asset = result.assets[0];
    setScanError('');
    setFileStatus(asset.size ? `PDF selected: ${(asset.size / (1024 * 1024)).toFixed(1)} MB. Multi-page invoices will be scanned together.` : 'PDF selected. Multi-page invoices will be scanned together.');
    setUri(asset.uri);
    setImageUris([]);
    setIsPDF(true);
    setResult(null);
    setResultItemPage(0);
    setPriceInsights([]);
    setDuplicate('');
    setScanError('');
    setDuplicateReceiptId(null);
  }

  async function scan(){
    if(!uri) return;

    if(!user){
      Alert.alert('Authentication required', 'Please sign in or start a guest trial first.');
      return;
    }

    setLoading(true);
    setResult(null);
    setResultItemPage(0);
    setPriceInsights([]);
    setDuplicate('');
    setScanError('');

    try{
      const token = await getUserToken();
      const sourceImageUris = !isPDF ? (imageUris.length ? imageUris : [uri]).filter(Boolean) as string[] : [];
      const isMultiImageScan = !isPDF && sourceImageUris.length > 1;
      const prepared = isPDF
        ? { uri, compressed: false, size: 0 }
        : isMultiImageScan
          ? { uri, compressed: false, size: 0 }
          : await compressReceiptImage(uri);
      if (prepared.compressed) {
        setUri(prepared.uri);
        setFileStatus(`Image compressed to ${(prepared.size / (1024 * 1024)).toFixed(1)} MB for scanning.`);
      }
      if (prepared.size && prepared.size > MAX_UPLOAD_BYTES) {
        const message = 'Please crop the receipt closer and try again. The image is still above 5 MB after compression.';
        setScanError(message);
        Alert.alert('Image too large', message);
        return;
      }

      const fd = new FormData();
      let endpoint = isMultiImageScan ? `${API}/scan-receipt-pages` : `${API}/scan-receipt`;
      const headers:any = {};

      if(user?.is_guest || user?.token === 'guest'){
        const guestSessionId = user.guest_session_id || user.id;

        if(!guestSessionId){
          Alert.alert('Authentication required', 'Guest session is missing. Please sign out and start guest trial again.');
          return;
        }

        endpoint = isMultiImageScan
          ? `${API}/guest/scan-receipt-pages?session_id=${encodeURIComponent(guestSessionId)}`
          : `${API}/guest/scan-receipt?session_id=${encodeURIComponent(guestSessionId)}`;
      } else {
        if(!token || token === 'guest'){
          Alert.alert('Authentication required', 'Your session token is missing. Please sign out and sign in again.');
          return;
        }

        headers.Authorization = `Bearer ${token}`;
      }

      if (isMultiImageScan) {
        const preparedPages = await Promise.all(sourceImageUris.map(pageUri => compressReceiptImage(pageUri)));
        const oversizedPage = preparedPages.find(page => page.size && page.size > MAX_UPLOAD_BYTES);
        if (oversizedPage) {
          const message = 'One receipt page is still above 5 MB after compression. Please crop it closer and try again.';
          setScanError(message);
          Alert.alert('Image too large', message);
          return;
        }
        if (preparedPages.some(page => page.compressed)) {
          setFileStatus(`${preparedPages.length} pages prepared for scanning.`);
        }
        for (let index = 0; index < preparedPages.length; index += 1) {
          const page = preparedPages[index];
          const name = uploadFileName(page.uri, `receipt-page-${index + 1}.jpg`);
          await appendUploadFile(fd, 'files', page.uri, name, getMime(page.uri, false));
        }
      } else {
        const fname = uploadFileName(prepared.uri, isPDF ? 'receipt.pdf' : 'receipt.jpg');
        await appendUploadFile(fd, 'file', prepared.uri, fname, getMime(prepared.uri, isPDF));
      }

      const res = await fetch(endpoint, {
        method: 'POST',
        body: fd,
        headers,
      });

      const data = await res.json();

      if(!res.ok){
        const rawMessage = String(data.detail || data.message || `Error ${res.status}`);
        appLogger.error(
          'Receipt scan request failed',
          new Error(rawMessage),
          {
            screen: 'Scan',
            action: 'scan_receipt',
            requestId: res.headers.get('X-Request-ID'),
            metadata: {
              statusCode: res.status,
              fileType: isPDF ? 'pdf' : 'image',
              pageCount: isPDF ? 1 : Math.max(1, sourceImageUris.length),
              guest: Boolean(user?.is_guest || user?.token === 'guest'),
            },
          },
        );
        const lowerMessage = rawMessage.toLowerCase();
        const friendlyMessage = rawMessage.includes('image exceeds 5 MB')
          ? 'The receipt image is still too large for AI scanning. Please crop closer to the receipt or retake the photo from a shorter distance.'
          : lowerMessage.includes('cannot read receipt') || lowerMessage.includes('not readable') || lowerMessage.includes('not legible') || lowerMessage.includes('too small') || lowerMessage.includes('far away')
            ? 'Cannot read the receipt clearly. Retake the photo closer, keep the full receipt visible, and make sure the text is sharp.'
          : rawMessage;
        const responseRequestId = res.headers.get('X-Request-ID');
        setScanError(`${friendlyMessage}${responseRequestId ? ` Request ID: ${responseRequestId}` : ''}`);
        Alert.alert('Scan Failed', friendlyMessage);
        return;
      }

      if(data.duplicate) {
        setDuplicate(data.message || 'This receipt was already scanned.');
        setDuplicateReceiptId(data.saved_id || data.receipt?.id || null);
      }

      if (!data.receipt) {
        throw new Error('The scanner completed without returning receipt data. Please try again.');
      }
      const normalizedReceipt = normalizeScannedReceipt(data.receipt);
      setResult(normalizedReceipt);
      setResultItemPage(0);
      if (!data.duplicate) {
        await loadPriceInsights(normalizedReceipt, data.saved_id);
        await loadStats();
        // Show item review sheet so user can fix OCR errors before they pollute price memory
        const scannedItems: any[] = normalizedReceipt?.items || [];
        if (scannedItems.length > 0 && data.saved_id) {
          setReviewSavedId(data.saved_id);
          setReviewItems(scannedItems);
          setReviewEdits({});
          setReviewModalVisible(true);
        }
      } else {
        setPriceInsights([]);
      }
    }catch(e:any){
      const visibleMessage = e?.message || 'Could not connect. Try again.';
      setScanError(visibleMessage);
      appLogger.error('Receipt scan failed before completion', e, {
        screen: 'Scan',
        action: 'scan_receipt',
        metadata: {
          fileType: isPDF ? 'pdf' : 'image',
          pageCount: isPDF ? 1 : Math.max(1, imageUris.length),
          guest: Boolean(user?.is_guest || user?.token === 'guest'),
        },
      });
      Alert.alert('Error', visibleMessage);
    }finally{
      setLoading(false);
    }
  }

  function resetScan(){
    setResult(null);
    setResultItemPage(0);
    setUri(null);
    setImageUris([]);
    setPriceInsights([]);
    setFileStatus('');
    setScanError('');
    setDuplicate('');
    setDuplicateReceiptId(null);
    setIsPDF(false);
  }

  async function saveReviewCorrections() {
    const token = getUserToken();
    const entries = Object.entries(reviewEdits).filter(([, v]) => v.trim());
    if (!entries.length || !reviewSavedId) {
      setReviewModalVisible(false);
      return;
    }
    setReviewSaving(true);
    const headers: any = { 'Content-Type': 'application/json' };
    if (token) headers['Authorization'] = `Bearer ${token}`;
    const guestId = useAuth.getState().user?.guest_session_id;

    for (const [idxStr, newName] of entries) {
      const idx = Number(idxStr);
      try {
        await fetch(`${API}/receipts/${reviewSavedId}/items/${idx}`, {
          method: 'PATCH',
          headers,
          body: JSON.stringify({
            name: newName.trim(),
            session_id: guestId || undefined,
          }),
        });
      } catch {
        // silent — best-effort
      }
    }
    setReviewSaving(false);
    setReviewModalVisible(false);
    Alert.alert('Corrections saved', 'Item names updated in your price memory.');
  }

  function renderReviewModal() {
    if (!reviewModalVisible) return null;
    const C2 = C || FALLBACK_COLORS;
    return (
      <Modal visible={reviewModalVisible} animationType="slide" transparent onRequestClose={() => setReviewModalVisible(false)}>
        <View style={[rs.overlay]}>
          <View style={[rs.sheet, { backgroundColor: C2.surface }]}>
            <View style={[rs.header, { borderBottomColor: C2.border }]}>
              <View>
                <Text style={[rs.title, { color: C2.text }]}>Review scanned items</Text>
                <Text style={[rs.subtitle, { color: C2.text3 }]}>Fix any OCR errors before they affect your price memory</Text>
              </View>
              <TouchableOpacity onPress={() => setReviewModalVisible(false)} hitSlop={{ top: 10, bottom: 10, left: 10, right: 10 }}>
                <Ionicons name="close" size={22} color={C2.text2} />
              </TouchableOpacity>
            </View>

            <ScrollView style={rs.list} showsVerticalScrollIndicator={false}>
              {reviewItems.map((item: any, idx: number) => {
                const originalName: string = item?.name || item?.item || '';
                const editedName: string = reviewEdits[idx] ?? originalName;
                const changed = editedName.trim() !== originalName.trim();
                return (
                  <View key={idx} style={[rs.itemRow, { borderBottomColor: C2.border }]}>
                    <View style={{ flex: 1 }}>
                      <TextInput
                        style={[rs.itemInput, { color: C2.text, borderColor: changed ? C2.accent : C2.border, backgroundColor: C2.surface2 }]}
                        value={editedName}
                        onChangeText={(v) => setReviewEdits(prev => ({ ...prev, [idx]: v }))}
                        placeholder="Item name"
                        placeholderTextColor={C2.text3}
                        returnKeyType="done"
                      />
                      {changed && (
                        <Text style={[rs.originalTxt, { color: C2.text3 }]} numberOfLines={1}>
                          Original: {originalName}
                        </Text>
                      )}
                    </View>
                    <Text style={[rs.itemPrice, { color: C2.text2 }]}>
                      {item?.price != null ? `$${n(item.price).toFixed(2)}` : ''}
                    </Text>
                  </View>
                );
              })}
            </ScrollView>

            <View style={[rs.footer, { borderTopColor: C2.border }]}>
              <TouchableOpacity
                style={[rs.skipBtn, { borderColor: C2.border }]}
                onPress={() => setReviewModalVisible(false)}
                activeOpacity={0.8}
              >
                <Text style={[rs.skipTxt, { color: C2.text2 }]}>Skip</Text>
              </TouchableOpacity>
              <TouchableOpacity
                style={[rs.saveBtn, { backgroundColor: C2.accent }, reviewSaving && { opacity: 0.5 }]}
                onPress={saveReviewCorrections}
                disabled={reviewSaving}
                activeOpacity={0.85}
              >
                {reviewSaving
                  ? <ActivityIndicator size="small" color="#fff" />
                  : <Text style={rs.saveTxt}>Save corrections</Text>}
              </TouchableOpacity>
            </View>
          </View>
        </View>
      </Modal>
    );
  }

  const displayResult = result ? normalizeScannedReceipt(result) : null;

  return(
    <>
    {renderReviewModal()}
    <ScrollView style={s.scroll} contentContainerStyle={s.container} showsVerticalScrollIndicator={false}>

      <View style={s.heroCard}>
        <View style={s.heroTop}>
          <View style={s.heroMark}>
            <Ionicons name="receipt-outline" size={22} color={C.accent} />
          </View>
          <View style={{ flex: 1 }}>
            <Text style={s.heroKicker}>ReceiptAI</Text>
            <Text style={s.heroTitle}>Scan receipt</Text>
          </View>
          <View style={s.heroBadge}>
            <Text style={s.heroBadgeText}>Ready</Text>
          </View>
        </View>
      </View>

      {/* PROFILE BADGE */}
      {user && (
        <View style={s.profileBadge}>
          <View style={s.profileCircle}>
            <Text style={s.profileInitial}>{profileInitial}</Text>
          </View>
          <View style={{ flex: 1 }}>
            <Text style={s.profileName} numberOfLines={1}>{displayName}</Text>
            <Text style={s.profileMode}>{user.is_guest ? 'Guest Trial' : 'Signed In'}</Text>
          </View>
        </View>
      )}

      {/* STATS */}
      <View style={s.statsRow}>
        <View style={[s.statBox,{borderBottomColor:C.accent}]}>
          <Text style={s.statLabel}>Receipts</Text>
          <Text style={[s.statVal,{color:C.accent}]}>{stats.receipts}</Text>
        </View>
        <View style={[s.statBox,{borderBottomColor:C.accent2}]}>
          <Text style={s.statLabel}>Spent</Text>
          <Text style={[s.statVal,{color:C.accent2}]}>${n(stats.spent).toFixed(0)}</Text>
        </View>
        <View style={[s.statBox,{borderBottomColor:C.accent3}]}>
          <Text style={s.statLabel}>Saved</Text>
          <Text style={[s.statVal,{color:C.accent3}]}>${n(stats.saved).toFixed(0)}</Text>
        </View>
      </View>

      {/* SCAN CARD */}
      <View style={s.card}>
        <View style={s.cardRow}>
          <View style={s.cardIconClean}>
            <Ionicons name="scan-outline" size={17} color={C.accent} />
          </View>
          <Text style={s.cardTitle}>Scan Receipt</Text>
        </View>

        {/*  LOGIN GATE  */}
        {!isLoggedIn ? (
          <View style={s.loginGate}>
            <Text style={s.loginGateEmoji}></Text>
            <Text style={s.loginGateTitle}>Sign in to scan receipts</Text>
            <Text style={s.loginGateDesc}>
              Create a free account or start a 24-hour trial to scan receipts, track prices and save money.
            </Text>
            <TouchableOpacity
              style={[s.btn,s.btnPri]}
              onPress={()=>Alert.alert('Sign In Required','Go to the Profile tab to sign in or start your free 24-hour trial.')}
              activeOpacity={0.85}
            >
              <Text style={s.btnPriTxt}>Go to Profile  Sign In</Text>
            </TouchableOpacity>
          </View>
        ) : (
          /*  SCANNER  */
          <>
            <TouchableOpacity style={s.uploadZone} onPress={pickImage} activeOpacity={0.8}>
              <View style={s.uploadIcon}>
                <Ionicons name="document-text-outline" size={34} color={C.text} />
              </View>
              <Text style={s.uploadTitle}>Tap to select a receipt</Text>
              <Text style={s.uploadSub}>JPG / PNG / WEBP / HEIC / PDF</Text>
              <View style={s.fmtRow}>
                {['JPG','PNG','WEBP','HEIC','PDF'].map(f=>(
                  <View key={f} style={s.fmtPill}><Text style={s.fmtText}>{f}</Text></View>
                ))}
              </View>
            </TouchableOpacity>

            {uri && !isPDF && imageUris.length <= 1 && <Image source={{uri}} style={s.preview} resizeMode="contain"/>}
            {uri && !isPDF && imageUris.length > 1 && (
              <View style={s.multiPreview}>
                <View style={s.multiPreviewHead}>
                  <Text style={s.multiPreviewTitle}>{imageUris.length} pages selected</Text>
                  <Text style={s.multiPreviewSub}>Scans as one receipt or invoice</Text>
                </View>
                <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={s.pageStrip}>
                  {imageUris.map((pageUri, index) => (
                    <View key={`${pageUri}-${index}`} style={s.pageThumbWrap}>
                      <Image source={{uri: pageUri}} style={s.pageThumb} resizeMode="cover" />
                      <Text style={s.pageThumbLabel}>Page {index + 1}</Text>
                    </View>
                  ))}
                </ScrollView>
              </View>
            )}
            {uri && isPDF && (
              <View style={s.pdfPreview}>
                <Text style={s.pdfPreviewText}>  {uri.split('/').pop()}</Text>
                <Text style={s.pdfPreviewSub}>PDF ready to scan</Text>
              </View>
            )}
            {fileStatus ? (
              <View style={s.fileNote}>
                <Ionicons name="checkmark-circle-outline" size={15} color={C.accent3} />
                <Text style={s.fileNoteText}>{fileStatus}</Text>
              </View>
            ) : null}
            {scanError ? (
              <View style={s.scanError}>
                <Ionicons name="alert-circle-outline" size={17} color={C.red} />
                <Text style={s.scanErrorText}>{scanError}</Text>
              </View>
            ) : null}

            <View style={s.btnRow}>
              <TouchableOpacity style={[s.btn,s.btnSec,{flex:1}]} onPress={pickImage} activeOpacity={0.8}>
                <Ionicons name="images-outline" size={18} color={C.text} />
                <Text style={s.btnSecTxt}>Gallery</Text>
              </TouchableOpacity>
              <TouchableOpacity style={[s.btn,s.btnSec,{flex:1}]} onPress={takePhoto} activeOpacity={0.8}>
                <Ionicons name="camera-outline" size={18} color={C.text} />
                <Text style={s.btnSecTxt}>{imageUris.length ? 'Add Page' : 'Camera'}</Text>
              </TouchableOpacity>
              <TouchableOpacity style={[s.btn,s.btnSec,{flex:1}]} onPress={pickPDF} activeOpacity={0.8}>
                <Ionicons name="document-outline" size={18} color={C.text} />
                <Text style={s.btnSecTxt}>PDF</Text>
              </TouchableOpacity>
            </View>

            {uri&&(
              <TouchableOpacity
                style={[s.btn,s.btnPri,loading&&{opacity:0.5}]}
                onPress={scan}
                disabled={loading}
                activeOpacity={0.85}
              >
                {loading
                  ?<ActivityIndicator color="#fff" size="small"/>
                  :<Text style={s.btnPriTxt}>{!isPDF && imageUris.length > 1 ? `Scan ${imageUris.length} Pages` : 'Scan Receipt'}</Text>
                }
              </TouchableOpacity>
            )}
          </>
        )}
      </View>

      {/* DUPLICATE WARNING */}
      {duplicate!==''&&(
        <View style={s.warnBox}>
          <View style={{ flex: 1 }}>
            <Text style={s.warnTitle}>Already scanned</Text>
            <Text style={s.warnText}>{duplicate}</Text>
          </View>
          {duplicateReceiptId ? (
            <TouchableOpacity
              style={s.warnAction}
              onPress={() => router.push({ pathname: '/receipts', params: { receiptId: String(duplicateReceiptId) } })}
              activeOpacity={0.82}
            >
              <Ionicons name="open-outline" size={14} color={C.accent} />
              <Text style={s.warnActionText}>Open</Text>
            </TouchableOpacity>
          ) : null}
        </View>
      )}

      {/* RESULT */}
      {displayResult&&(
        <View style={s.resultCard}>
          <View style={s.resultHeader}>
            <Text style={s.resultKicker}>Scan complete</Text>
            <Text style={s.resultStore}>{displayResult.store||'Unknown Store'}</Text>
            <Text style={s.resultMeta}>
              {[displayResult.date&&` ${displayResult.date}${displayResult.time?' '+displayResult.time:''}`,displayResult.address&&` ${displayResult.address}`].filter(Boolean).join('    ')}
            </Text>
          </View>

          <View style={s.resultSummary}>
            <View style={s.summaryTile}>
              <Text style={s.summaryLabel}>Category</Text>
              <Text style={s.summaryValue} numberOfLines={1}>{scanCategory(displayResult)}</Text>
            </View>
            <View style={s.summaryTile}>
              <Text style={s.summaryLabel}>Items</Text>
              <Text style={s.summaryValue}>{(displayResult.items||[]).length}</Text>
            </View>
            <View style={s.summaryTile}>
              <Text style={s.summaryLabel}>Total</Text>
              <Text style={[s.summaryValue,{color:C.accent}]}>{hasVisibleMoney(displayResult.total) ? `$${n(displayResult.total).toFixed(2)}` : 'Not visible'}</Text>
            </View>
          </View>

          <View style={s.resultActionNote}>
            <Text style={s.resultActionTitle}>Ready for AI Memory</Text>
            <Text style={s.resultActionText}>Saved for price history, spending analysis, and before-you-buy checks.</Text>
          </View>

          {(() => {
            const items = displayResult.items || [];
            const totalPages = itemPageCount(items);
            const page = Math.min(resultItemPage, totalPages - 1);
            const start = page * INVOICE_ITEM_PAGE_SIZE + 1;
            const end = Math.min(items.length, (page + 1) * INVOICE_ITEM_PAGE_SIZE);
            if (items.length <= INVOICE_ITEM_PAGE_SIZE) return null;
            return (
              <View style={s.invoicePager}>
                <View>
                  <Text style={s.invoicePagerTitle}>Large invoice view</Text>
                  <Text style={s.invoicePagerText}>Showing {start}-{end} of {items.length} scanned lines</Text>
                </View>
                <View style={s.pageControls}>
                  <TouchableOpacity
                    style={[s.pageBtn, page === 0 && s.pageBtnDisabled]}
                    onPress={() => setResultItemPage(Math.max(0, page - 1))}
                    disabled={page === 0}
                  >
                    <Text style={s.pageBtnText}>Prev</Text>
                  </TouchableOpacity>
                  <Text style={s.pageCount}>{page + 1}/{totalPages}</Text>
                  <TouchableOpacity
                    style={[s.pageBtn, page >= totalPages - 1 && s.pageBtnDisabled]}
                    onPress={() => setResultItemPage(Math.min(totalPages - 1, page + 1))}
                    disabled={page >= totalPages - 1}
                  >
                    <Text style={s.pageBtnText}>Next</Text>
                  </TouchableOpacity>
                </View>
              </View>
            );
          })()}

          <View style={s.items}>
            {itemPageItems(displayResult.items||[], resultItemPage).map((item:any,i:number)=>{
              const neg  = item.price<0;
              const ps   = neg?`-$${Math.abs(item.price).toFixed(2)}`:`$${n(item.price).toFixed(2)}`;
              const unit = (item.unit||'').toLowerCase().trim();
              const qty  = n(item.quantity)||1;
              const up   = n(item.unit_price);
              const productSize = item.product_size || '';
              const savedUnitLabel = item.unit_label || '';
              const UNITS=['lb','lbs','oz','kg','g','mg','ml','l','liter','liters','fl oz','fl','gal','gallon','pt','pint','qt','quart','ct','count'];
              const isWeighted=UNITS.includes(unit);
              let qtyLabel='',unitLabel='';
              if(isWeighted&&unit&&unit!=='each'){
                qtyLabel=`${qty} ${unit}`;
                if(up>0) unitLabel=`@ $${up.toFixed(2)}/${unit}`;
              }else if(qty>1){
                qtyLabel=`${qty}`;
                if(up>0) unitLabel=`@ $${up.toFixed(2)} each`;
              }
              if(productSize && !unitLabel) unitLabel=`Size: ${productSize}`;
              if(savedUnitLabel && savedUnitLabel !== 'each' && !unitLabel) unitLabel=savedUnitLabel;
              return(
                <View key={i} style={s.itemRow}>
                  <View style={{flex:1}}>
                    {item.code?<Text style={s.itemCode}>{item.code}</Text>:null}
                    <View style={{flexDirection:'row',alignItems:'center',flexWrap:'wrap',gap:4}}>
                      <Text style={s.itemName}>{item.name}</Text>
                      {qtyLabel?<Text style={s.itemQty}>{qtyLabel}</Text>:null}
                    </View>
                    {unitLabel?<Text style={s.itemUnit}>{unitLabel}</Text>:null}
                  </View>
                  <Text style={[s.itemPrice,{color:neg?C.green:C.text}]}>{ps}</Text>
                </View>
              );
            })}
          </View>

          <View style={s.compareBox}>
            <View style={s.compareHead}>
              <View>
                <Text style={s.compareKicker}>Instant price check</Text>
                <Text style={s.compareTitle}>Compared with your receipt history</Text>
              </View>
              {priceLoading ? <ActivityIndicator color={C.accent} size="small" /> : null}
            </View>

            {!priceLoading && priceInsights.length === 0 ? (
              <Text style={s.compareEmpty}>Scan more receipts to compare these prices automatically.</Text>
            ) : null}

            {priceInsights.map((row:any, i:number) => {
              const isLower = row.status === 'lower';
              const isHigher = row.status === 'higher';
              const tone = isLower ? C.green : isHigher ? C.red : C.text2;
              const label = row.status === 'new'
                ? 'New'
                : row.status === 'same'
                  ? 'Same'
                  : isLower
                    ? 'Lower'
                    : 'Higher';
              const detail = row.status === 'new'
                ? row.message
                : `${money(row.current)}${row.unitLabel || ''} now · previous buy ${money(row.previousBuy ?? row.previousLow)}${row.unitLabel || ''}`;
              const delta = row.status === 'new' || row.status === 'same'
                ? ''
                : `${isLower ? 'Save' : 'Up'} ${money(Math.abs(row.diff))}${row.unitLabel || ''}`;

              return (
                <View key={`${row.item}-${i}`} style={s.compareRow}>
                  <View style={s.compareLeft}>
                    <Text style={s.compareItem} numberOfLines={1}>{row.item}</Text>
                    <Text style={s.compareDetail}>{detail}</Text>
                    {row.previousStore ? <Text style={s.compareStore}>Previous store: {row.previousStore}</Text> : null}
                  </View>
                  <TouchableOpacity
                    style={[s.comparePill,{borderColor:tone}, row.previousReceiptId && s.comparePillTap]}
                    onPress={() => openPreviousReceipt(row)}
                    disabled={!row.previousReceiptId}
                    activeOpacity={0.75}
                  >
                    <Text style={[s.comparePillText,{color:tone}]}>{label}</Text>
                    {delta ? <Text style={[s.compareDelta,{color:tone}]}>{delta}</Text> : null}
                    {row.previousReceiptId ? <Text style={s.compareViewReceipt}>Receipt</Text> : null}
                  </TouchableOpacity>
                </View>
              );
            })}
          </View>

          <View style={s.totals}>
            {n(displayResult.subtotal)>0&&<View style={s.tRow}><Text style={s.tLbl}>Subtotal</Text><Text style={s.tVal}>${n(displayResult.subtotal).toFixed(2)}</Text></View>}
            {n(displayResult.discount)>0&&<View style={s.tRow}><Text style={s.tLbl}>Discount</Text><Text style={[s.tVal,{color:C.green}]}>-${n(displayResult.discount).toFixed(2)}</Text></View>}
            {n(displayResult.tax)>0&&<View style={s.tRow}><Text style={s.tLbl}>Tax</Text><Text style={s.tVal}>${n(displayResult.tax).toFixed(2)}</Text></View>}
            <View style={[s.tRow,s.tFinal]}>
              <Text style={s.tFinalLbl}>Total Paid</Text>
              <Text style={s.tFinalAmt}>{hasVisibleMoney(displayResult.total) ? `$${n(displayResult.total).toFixed(2)}` : 'Not visible'}</Text>
            </View>
            {!hasVisibleMoney(displayResult.total) ? (
              <Text style={s.totalNote}>The final invoice total was not visible in this image. Scan the remaining page to capture the full total.</Text>
            ) : null}
          </View>

          {n(displayResult.total_savings)>0&&(
            <View style={s.savingsBanner}>
              <Text style={s.savingsText}>  You saved ${n(displayResult.total_savings).toFixed(2)} on this trip!</Text>
            </View>
          )}

          <TouchableOpacity style={[s.btn,s.btnSec,{margin:16,marginTop:12}]} onPress={resetScan}>
            <Text style={s.btnSecTxt}>  Scan Another Receipt</Text>
          </TouchableOpacity>
        </View>
      )}

      <Modal
        visible={previousReceiptLoading || !!previousReceipt}
        animationType="slide"
        transparent
        onRequestClose={() => {
          setPreviousReceipt(null);
          setPreviousReceiptItem(null);
        }}
      >
        <View style={s.receiptModalShade}>
          <View style={s.receiptModal}>
            {previousReceiptLoading ? (
              <View style={s.receiptModalLoading}>
                <ActivityIndicator color={C.accent} />
                <Text style={s.receiptModalSub}>Opening previous receipt...</Text>
              </View>
            ) : (
              <>
                <View style={s.receiptModalHead}>
                  <View style={{flex:1}}>
                    <Text style={s.receiptModalKicker}>Previous receipt</Text>
                    <Text style={s.receiptModalTitle}>{previousReceipt?.store || 'Unknown Store'}</Text>
                    <Text style={s.receiptModalSub}>
                      {[previousReceipt?.date, previousReceipt?.time, previousReceipt?.address].filter(Boolean).join('  ')}
                    </Text>
                  </View>
                  <TouchableOpacity
                    style={s.receiptModalClose}
                    onPress={() => {
                      setPreviousReceipt(null);
                      setPreviousReceiptItem(null);
                    }}
                  >
                    <Ionicons name="close" size={18} color={C.text} />
                  </TouchableOpacity>
                </View>

                {previousReceiptItem ? (
                  <View style={s.receiptMatchedItem}>
                    <Text style={s.receiptMatchedLabel}>Matched item</Text>
                    <View style={s.receiptItemLine}>
                      <Text style={s.receiptItemName}>{previousReceiptItem.name || previousReceiptItem.item}</Text>
                      <Text style={s.receiptItemPrice}>{money(previousReceiptItem.price)}</Text>
                    </View>
                  </View>
                ) : null}

                <ScrollView style={s.receiptItemsList} showsVerticalScrollIndicator={false}>
                  {(previousReceipt?.items || []).slice(0, 40).map((item:any, index:number) => {
                    const matched = previousReceiptItem && item === previousReceiptItem;
                    return (
                      <View key={`${item?.name || item?.item}-${index}`} style={[s.receiptItemLine, matched && s.receiptItemLineActive]}>
                        <Text style={[s.receiptItemName, matched && s.receiptItemNameActive]}>{item?.name || item?.item || 'Item'}</Text>
                        <Text style={s.receiptItemPrice}>{money(item?.price)}</Text>
                      </View>
                    );
                  })}
                </ScrollView>

                <View style={s.receiptModalTotals}>
                  <Text style={s.receiptModalSub}>Total</Text>
                  <Text style={s.receiptModalTotal}>{hasVisibleMoney(previousReceipt?.total) ? money(previousReceipt?.total) : 'Not visible'}</Text>
                </View>
              </>
            )}
          </View>
        </View>
      </Modal>
    </ScrollView>
    </>
  );
}

const createStyles = (C: typeof FALLBACK_COLORS) => StyleSheet.create({
  heroCard:{
    backgroundColor:C.card,
    borderRadius:18,
    borderWidth:1,
    borderColor:C.border,
    padding:18,
    marginBottom:14,
    shadowColor:'#000',
    shadowOpacity:0.24,
    shadowRadius:18,
    shadowOffset:{width:0,height:10},
    elevation:5,
  },
  heroTop:{ flexDirection:'row', alignItems:'center', gap:12 },
  heroMark:{
    width:44,
    height:44,
    borderRadius:14,
    backgroundColor:'rgba(124,109,255,0.13)',
    borderWidth:1,
    borderColor:'rgba(124,106,255,0.38)',
    alignItems:'center',
    justifyContent:'center',
  },
  heroMarkText:{ color:C.accent, fontSize:14, fontWeight:'900', letterSpacing:0 },
  heroKicker:{ color:C.accent3, fontSize:10, fontWeight:'900', textTransform:'uppercase', letterSpacing:0.8, marginBottom:4 },
  heroTitle:{ color:C.text, fontSize:24, lineHeight:29, fontWeight:'900', letterSpacing:0 },
  heroBadge:{ backgroundColor:'rgba(66,217,135,0.10)', borderWidth:1, borderColor:'rgba(66,217,135,0.24)', borderRadius:99, paddingHorizontal:11, paddingVertical:5 },
  heroBadgeText:{ color:C.green, fontSize:11, fontWeight:'900' },
  profileBadge:{
    flexDirection:'row',
    alignItems:'center',
    alignSelf:'flex-end',
    gap:8,
    maxWidth:170,
    paddingVertical:7,
    paddingHorizontal:10,
    borderRadius:999,
    backgroundColor:'rgba(255,255,255,0.045)',
    borderWidth:1,
    borderColor:'rgba(124,106,255,0.35)',
    marginBottom:12,
  },
  profileCircle:{
    width:32,
    height:32,
    borderRadius:16,
    alignItems:'center',
    justifyContent:'center',
    backgroundColor:C.accent,
  },
  profileInitial:{
    color:'#fff',
    fontSize:14,
    fontWeight:'800',
  },
  profileName:{
    color:C.text,
    fontSize:12,
    fontWeight:'800',
    maxWidth:110,
  },
  profileMode:{
    color:C.text2,
    fontSize:10,
    marginTop:1,
  },
  scroll:{flex:1,backgroundColor:C.bg},
  container:{padding:16,paddingBottom:40},
  statsRow:{flexDirection:'row',gap:10,marginBottom:16},
  statBox:{flex:1,backgroundColor:C.card,borderRadius:16,padding:14,borderWidth:1,borderColor:C.border,borderBottomWidth:2,shadowColor:'#000',shadowOpacity:0.16,shadowRadius:10,shadowOffset:{width:0,height:6},elevation:3},
  statLabel:{fontSize:10,color:C.text3,textTransform:'uppercase',letterSpacing:0.6,marginBottom:4},
  statVal:{fontSize:22,fontWeight:'900',letterSpacing:0},
  card:{backgroundColor:C.card,borderRadius:18,borderWidth:1,borderColor:C.border,padding:18,marginBottom:16,shadowColor:'#000',shadowOpacity:0.20,shadowRadius:16,shadowOffset:{width:0,height:10},elevation:4},
  cardRow:{flexDirection:'row',alignItems:'center',gap:10,marginBottom:16},
  cardIcon:{display:'none'},
  cardIconClean:{width:30,height:30,borderRadius:9,alignItems:'center',justifyContent:'center',backgroundColor:'rgba(124,106,255,0.18)'},
  cardTitle:{color:C.text,fontSize:15,fontWeight:'700'},
  loginGate:{alignItems:'center',padding:20,gap:12},
  loginGateEmoji:{fontSize:48},
  loginGateTitle:{color:C.text,fontSize:18,fontWeight:'700',textAlign:'center'},
  loginGateDesc:{color:C.text2,fontSize:13,textAlign:'center',lineHeight:20},
  uploadZone:{borderWidth:1.5,borderColor:'rgba(124,109,255,0.30)',borderStyle:'dashed',borderRadius:16,padding:28,alignItems:'center',backgroundColor:'rgba(124,109,255,0.045)'},
  uploadEmoji:{display:'none'},
  uploadIcon:{width:54,height:54,borderRadius:16,alignItems:'center',justifyContent:'center',backgroundColor:'rgba(255,255,255,0.04)',borderWidth:1,borderColor:C.border,marginBottom:12},
  uploadTitle:{color:C.text,fontSize:14,fontWeight:'600',marginBottom:4},
  uploadSub:{color:C.text2,fontSize:12,marginBottom:10},
  fmtRow:{flexDirection:'row',gap:6},
  fmtPill:{backgroundColor:C.surface2,borderWidth:1,borderColor:C.border,borderRadius:99,paddingHorizontal:8,paddingVertical:2},
  fmtText:{color:C.text3,fontSize:10},
  preview:{width:'100%',height:200,borderRadius:12,marginTop:14,borderWidth:1,borderColor:C.border},
  multiPreview:{marginTop:14,backgroundColor:'rgba(124,106,255,0.06)',borderWidth:1,borderColor:'rgba(124,106,255,0.18)',borderRadius:12,padding:12},
  multiPreviewHead:{marginBottom:10},
  multiPreviewTitle:{color:C.text,fontSize:13,fontWeight:'900'},
  multiPreviewSub:{color:C.text2,fontSize:11,marginTop:2},
  pageStrip:{gap:10,paddingRight:4},
  pageThumbWrap:{width:88},
  pageThumb:{width:88,height:112,borderRadius:10,borderWidth:1,borderColor:C.border,backgroundColor:C.surface},
  pageThumbLabel:{color:C.text2,fontSize:10,fontWeight:'800',textAlign:'center',marginTop:5},
  fileNote:{marginTop:10,flexDirection:'row',alignItems:'center',gap:7,backgroundColor:'rgba(106,255,212,0.07)',borderWidth:1,borderColor:'rgba(106,255,212,0.18)',borderRadius:10,padding:10},
  fileNoteText:{color:C.text2,fontSize:11,flex:1},
  scanError:{marginTop:10,flexDirection:'row',alignItems:'flex-start',gap:8,backgroundColor:'rgba(255,99,120,0.10)',borderWidth:1,borderColor:'rgba(255,99,120,0.35)',borderRadius:12,padding:12},
  scanErrorText:{color:C.red,fontSize:12,flex:1,lineHeight:17,fontWeight:'700'},
  pdfPreview:{backgroundColor:'rgba(124,106,255,0.08)',borderWidth:1,borderColor:'rgba(124,106,255,0.2)',borderRadius:12,padding:16,marginTop:14,alignItems:'center'},
  pdfPreviewText:{color:C.accent,fontSize:13,fontWeight:'600'},
  pdfPreviewSub:{color:C.text3,fontSize:11,marginTop:4},
  btnRow:{flexDirection:'row',gap:8,marginTop:12},
  btn:{borderRadius:14,padding:14,alignItems:'center',marginTop:10},
  btnPri:{backgroundColor:C.accent,shadowColor:C.accent,shadowOpacity:0.34,shadowRadius:14,shadowOffset:{width:0,height:8},elevation:4},
  btnPriTxt:{color:'#fff',fontSize:15,fontWeight:'600'},
  btnSec:{backgroundColor:C.surface2,borderWidth:1,borderColor:C.border,flexDirection:'row',alignItems:'center',justifyContent:'center',gap:7},
  btnSecTxt:{color:C.text,fontSize:12,fontWeight:'700'},
  warnBox:{backgroundColor:'rgba(243,199,92,0.08)',borderWidth:1,borderColor:'rgba(243,199,92,0.25)',borderRadius:16,padding:14,marginBottom:12,flexDirection:'row',alignItems:'center',gap:12},
  warnTitle:{color:'#fbbf24',fontSize:13,fontWeight:'900',marginBottom:3},
  warnText:{color:'#fbbf24',fontSize:12,lineHeight:17},
  warnAction:{flexDirection:'row',alignItems:'center',gap:5,borderWidth:1,borderColor:'rgba(128,111,255,0.38)',backgroundColor:'rgba(128,111,255,0.12)',borderRadius:10,paddingHorizontal:10,paddingVertical:8},
  warnActionText:{color:C.accent,fontSize:11,fontWeight:'900'},
  resultCard:{backgroundColor:C.card,borderRadius:18,overflow:'hidden',borderWidth:1,borderColor:'rgba(82,230,200,0.22)',marginBottom:16,shadowColor:'#000',shadowOpacity:0.24,shadowRadius:18,shadowOffset:{width:0,height:12},elevation:5},
  resultHeader:{padding:16,backgroundColor:'rgba(106,255,212,0.05)',borderBottomWidth:1,borderBottomColor:'rgba(106,255,212,0.15)'},
  resultKicker:{color:C.accent3,fontSize:10,fontWeight:'900',textTransform:'uppercase',letterSpacing:0.6,marginBottom:5},
  resultStore:{color:C.text,fontSize:18,fontWeight:'900',letterSpacing:0},
  resultMeta:{color:C.text2,fontSize:11,marginTop:3},
  resultSummary:{flexDirection:'row',gap:8,padding:16,paddingBottom:8},
  summaryTile:{flex:1,backgroundColor:C.surface2,borderWidth:1,borderColor:C.border,borderRadius:14,padding:10,minHeight:62},
  summaryLabel:{color:C.text3,fontSize:9,fontWeight:'800',textTransform:'uppercase',letterSpacing:0.5,marginBottom:5},
  summaryValue:{color:C.text,fontSize:13,fontWeight:'900'},
  resultActionNote:{marginHorizontal:16,marginBottom:4,backgroundColor:'rgba(124,109,255,0.08)',borderWidth:1,borderColor:'rgba(124,109,255,0.22)',borderRadius:14,padding:12},
  resultActionTitle:{color:C.text,fontSize:13,fontWeight:'900',marginBottom:3},
  resultActionText:{color:C.text2,fontSize:12,lineHeight:17},
  voicePagination:{flexDirection:'row',gap:8,marginTop:12},
  invoicePager:{marginHorizontal:16,marginTop:12,backgroundColor:'rgba(124,106,255,0.08)',borderWidth:1,borderColor:'rgba(124,106,255,0.2)',borderRadius:12,padding:12,flexDirection:'row',alignItems:'center',justifyContent:'space-between',gap:10},
  invoicePagerTitle:{color:C.text,fontSize:13,fontWeight:'900'},
  invoicePagerText:{color:C.text2,fontSize:11,marginTop:2},
  pageControls:{flexDirection:'row',alignItems:'center',gap:6},
  pageBtn:{backgroundColor:C.surface2,borderWidth:1,borderColor:C.border,borderRadius:9,paddingHorizontal:9,paddingVertical:6},
  pageBtnDisabled:{opacity:0.35},
  pageBtnText:{color:C.accent,fontSize:11,fontWeight:'900'},
  pageCount:{color:C.text2,fontSize:11,fontWeight:'800',minWidth:34,textAlign:'center'},
  items:{padding:16},
  itemRow:{flexDirection:'row',justifyContent:'space-between',alignItems:'flex-start',paddingVertical:10,borderBottomWidth:1,borderBottomColor:C.border,gap:10},
  itemCode:{color:C.text3,fontSize:9,fontFamily:'monospace'},
  itemName:{color:C.text,fontSize:13,fontWeight:'700'},
  itemQty:{color:C.accent,fontSize:11},
  itemUnit:{color:C.text2,fontSize:11,marginTop:2},
  itemPrice:{fontSize:13,fontWeight:'600'},
  compareBox:{marginHorizontal:16,marginBottom:12,backgroundColor:C.surface,borderWidth:1,borderColor:C.border,borderRadius:16,padding:14},
  compareHead:{flexDirection:'row',justifyContent:'space-between',alignItems:'center',gap:10,marginBottom:8},
  compareKicker:{color:C.accent3,fontSize:9,fontWeight:'900',textTransform:'uppercase',letterSpacing:0.6,marginBottom:3},
  compareTitle:{color:C.text,fontSize:14,fontWeight:'900'},
  compareEmpty:{color:C.text2,fontSize:12,lineHeight:18},
  compareRow:{flexDirection:'row',alignItems:'center',justifyContent:'space-between',gap:10,paddingVertical:9,borderTopWidth:1,borderTopColor:C.border},
  compareLeft:{flex:1},
  compareItem:{color:C.text,fontSize:12,fontWeight:'800'},
  compareDetail:{color:C.text2,fontSize:11,marginTop:2},
  compareStore:{color:C.accent,fontSize:10,marginTop:2,fontWeight:'700'},
  comparePill:{minWidth:78,borderWidth:1,borderRadius:10,paddingHorizontal:9,paddingVertical:7,alignItems:'center'},
  comparePillTap:{backgroundColor:'rgba(124,106,255,0.08)'},
  comparePillText:{fontSize:11,fontWeight:'900'},
  compareDelta:{fontSize:9,fontWeight:'800',marginTop:2},
  compareViewReceipt:{color:C.accent,fontSize:9,fontWeight:'900',marginTop:3},
  totals:{backgroundColor:C.surface,margin:16,borderRadius:16,padding:14,borderWidth:1,borderColor:C.border},
  tRow:{flexDirection:'row',justifyContent:'space-between',paddingVertical:4},
  tLbl:{color:C.text2,fontSize:13},
  tVal:{color:C.text,fontSize:13,fontWeight:'500'},
  tFinal:{borderTopWidth:1,borderTopColor:C.border,marginTop:6,paddingTop:10},
  tFinalLbl:{color:C.text,fontSize:15,fontWeight:'700'},
  tFinalAmt:{color:C.accent,fontSize:15,fontWeight:'800'},
  totalNote:{color:C.text2,fontSize:11,lineHeight:16,marginTop:8},
  savingsBanner:{marginHorizontal:16,marginBottom:8,padding:10,backgroundColor:'rgba(74,222,128,0.1)',borderWidth:1,borderColor:'rgba(74,222,128,0.25)',borderRadius:10},
  savingsText:{color:C.green,fontWeight:'600',fontSize:13,textAlign:'center'},
  receiptModalShade:{flex:1,backgroundColor:'rgba(0,0,0,0.62)',justifyContent:'flex-end'},
  receiptModal:{maxHeight:'78%',backgroundColor:C.surface,borderTopLeftRadius:18,borderTopRightRadius:18,borderWidth:1,borderColor:C.border,padding:16},
  receiptModalLoading:{minHeight:180,alignItems:'center',justifyContent:'center',gap:10},
  receiptModalHead:{flexDirection:'row',alignItems:'flex-start',gap:12,marginBottom:12},
  receiptModalKicker:{color:C.accent3,fontSize:10,fontWeight:'900',textTransform:'uppercase',letterSpacing:0.6},
  receiptModalTitle:{color:C.text,fontSize:20,fontWeight:'900',marginTop:3},
  receiptModalSub:{color:C.text2,fontSize:12,lineHeight:17,marginTop:3},
  receiptModalClose:{width:34,height:34,borderRadius:17,alignItems:'center',justifyContent:'center',backgroundColor:C.surface2,borderWidth:1,borderColor:C.border},
  receiptMatchedItem:{borderWidth:1,borderColor:C.accent,borderRadius:12,padding:10,backgroundColor:'rgba(124,106,255,0.10)',marginBottom:10},
  receiptMatchedLabel:{color:C.accent3,fontSize:10,fontWeight:'900',textTransform:'uppercase',letterSpacing:0.6,marginBottom:4},
  receiptItemsList:{maxHeight:330,borderTopWidth:1,borderTopColor:C.border},
  receiptItemLine:{flexDirection:'row',alignItems:'flex-start',justifyContent:'space-between',gap:10,paddingVertical:9,borderBottomWidth:1,borderBottomColor:C.border},
  receiptItemLineActive:{backgroundColor:'rgba(124,106,255,0.10)',borderRadius:8,paddingHorizontal:8},
  receiptItemName:{flex:1,color:C.text,fontSize:13},
  receiptItemNameActive:{fontWeight:'900',color:C.accent3},
  receiptItemPrice:{color:C.text,fontSize:13,fontWeight:'800'},
  receiptModalTotals:{flexDirection:'row',justifyContent:'space-between',alignItems:'center',paddingTop:12,marginTop:4},
  receiptModalTotal:{color:C.accent,fontSize:17,fontWeight:'900'},
});

const rs = StyleSheet.create({
  overlay:   { flex: 1, backgroundColor: 'rgba(0,0,0,0.55)', justifyContent: 'flex-end' },
  sheet:     { borderTopLeftRadius: 24, borderTopRightRadius: 24, paddingBottom: 34, maxHeight: '85%' },
  header:    { flexDirection: 'row', alignItems: 'flex-start', justifyContent: 'space-between', padding: 18, borderBottomWidth: 1 },
  title:     { fontSize: 17, fontWeight: '900' },
  subtitle:  { fontSize: 12, marginTop: 3, lineHeight: 17 },
  list:      { paddingHorizontal: 16, paddingTop: 8 },
  itemRow:   { flexDirection: 'row', alignItems: 'center', gap: 10, paddingVertical: 10, borderBottomWidth: 1 },
  itemInput: { flex: 1, borderWidth: 1, borderRadius: 10, paddingHorizontal: 11, paddingVertical: 8, fontSize: 13 },
  originalTxt:{ fontSize: 10, marginTop: 3 },
  itemPrice: { fontSize: 13, fontWeight: '700', minWidth: 52, textAlign: 'right' },
  footer:    { flexDirection: 'row', gap: 10, padding: 16, borderTopWidth: 1 },
  skipBtn:   { flex: 1, borderWidth: 1, borderRadius: 14, alignItems: 'center', justifyContent: 'center', paddingVertical: 13 },
  skipTxt:   { fontSize: 14, fontWeight: '700' },
  saveBtn:   { flex: 2, borderRadius: 14, alignItems: 'center', justifyContent: 'center', paddingVertical: 13 },
  saveTxt:   { color: '#fff', fontSize: 14, fontWeight: '900' },
});
