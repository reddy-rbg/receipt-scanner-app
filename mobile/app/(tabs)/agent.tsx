import { useEffect, useRef, useState, useCallback } from 'react';
import AsyncStorage from '@react-native-async-storage/async-storage';
import { useTheme } from '../../stores/themeStore';
import { getUserToken, getGuestSessionId, getUser } from '../../stores/authStore';
import { router, useFocusEffect } from 'expo-router';
import { Ionicons } from '@expo/vector-icons';
import Constants from 'expo-constants';
import * as Clipboard from 'expo-clipboard';
import { API } from '../../config/api';
import {
  View, Text, ScrollView, TouchableOpacity, TextInput,
  StyleSheet, ActivityIndicator, KeyboardAvoidingView,
  Platform, Alert, Linking,
} from 'react-native';
declare const require: any;
let VoiceModule: any = null;
let VoiceModuleChecked = false;

function getVoiceModule() {
  if (VoiceModuleChecked) return VoiceModule;
  VoiceModuleChecked = true;
  if (Constants.appOwnership === 'expo') {
    VoiceModule = null;
    return VoiceModule;
  }
  try {
    VoiceModule = require('expo-speech-recognition').ExpoSpeechRecognitionModule;
  } catch {
    VoiceModule = null;
  }
  return VoiceModule;
}

function friendlyAgentError(message: string) {
  if (!message) return 'I had trouble answering that. Please try again.';
  const lower = message.toLowerCase();
  if (lower.includes('network request failed') || lower.includes('failed to fetch') || lower.includes('could not connect')) {
    return 'ReceiptAI backend is not reachable right now. Please try again after the server redeploy finishes.';
  }
  if (lower.includes('column') || lower.includes('receipts.') || lower.includes('sql') || lower.includes('supabase')) {
    return 'I had trouble reading your receipt data. Please try again in a moment.';
  }
  return message;
}

function formatAgentText(text: string) {
  const chartChars = /[█▇▆▅▄▃▂▁■□#]{3,}/g;
  return text
    .replace(/\*\*(.+?)\*\*/g, '$1')
    .replace(/^### (.+)$/gm, '$1:')
    .replace(/^## (.+)$/gm, '$1')
    .replace(/^# (.+)$/gm, '$1')
    .split('\n')
    .filter(line => !/^\s*\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)+\|?\s*$/.test(line))
    .map(line => line
      .replace(/^\s*\|\s*/, '')
      .replace(/\s*\|\s*$/, '')
      .replace(/\s*\|\s*/g, '   ')
      .replace(chartChars, '')
      .replace(/\s{3,}/g, '  ')
      .trimEnd()
    )
    .filter(line => !/^\s*[-=]{8,}\s*$/.test(line))
    .join('\n')
    .replace(/\n{3,}/g, '\n\n')
    .trim();
}

function parsePrice(value: unknown) {
  if (value == null) return null;
  if (typeof value === 'number') return Number.isFinite(value) ? value : null;
  const cleaned = String(value).replace(/[^0-9.-]/g, '');
  if (!cleaned) return null;
  const parsed = Number(cleaned);
  return Number.isFinite(parsed) ? parsed : null;
}

function displayPrice(value: unknown, fallback = '') {
  if (typeof value === 'string') {
    const trimmed = value.trim();
    if (!trimmed || /^n\/?a$/i.test(trimmed) || /not found/i.test(trimmed)) return trimmed || fallback;
    if (trimmed.startsWith('$') || /price not shown/i.test(trimmed)) return trimmed;
  }
  const parsed = parsePrice(value);
  return parsed == null ? fallback : `$${parsed.toFixed(2)}`;
}

function traceRowItem(row: RagTraceRow) {
  return row.item || row.item_original || row.item_name_original || 'Receipt item';
}

type RagTraceRow = {
  item?: string;
  item_original?: string;
  item_name_original?: string;
  store?: string;
  date?: string;
  purchase_date?: string;
  price?: string | number;
  receipt_id?: string | number;
  line_index?: string | number;
  match_score?: number;
};

type RagTrace = {
  intent?: string;
  retrieval?: string;
  evidence_count?: number;
  matched_event_count?: number;
  evidence_is_complete?: boolean;
  retrieval_pipeline?: {
    embedding_model?: string;
    contextual_embeddings?: boolean;
    vector_boost_matches?: number;
    reranker?: string;
  };
  evidence?: RagTraceRow[];
  note?: string;
};

type Msg = {
  role: 'user' | 'agent';
  text: string;
  tools?: string[];
  loading?: boolean;
  answerCard?: AgentAnswerCard | null;
  ragTrace?: RagTrace | null;
  feedbackSent?: boolean;
  traceExpanded?: boolean;
};

type VoiceMode = 'dictate' | 'wake' | null;

type AgentAnswerRow = {
  item?: string;
  price?: string;
  store?: string;
  date?: string;
  receipt_id?: string | number;
  line_index?: string | number;
  detail?: string;
};

type AgentAnswerCard = {
  type?: string;
  title?: string;
  item?: string;
  price?: string;
  store?: string;
  date?: string;
  quantity?: number;
  unit?: string;
  line_total?: string;
  receipt_id?: string | number;
  line_index?: string | number;
  detail?: string;
  note?: string;
  rows?: AgentAnswerRow[];
};

const PRISM_STARTERS = [
  { icon: 'sparkles-outline' as const, label: 'Summarize this month', prompt: 'Summarize my spending this month and explain the biggest change.' },
  { icon: 'search-outline' as const, label: 'Find an item', prompt: 'Help me find an item from my saved receipts.' },
  { icon: 'git-compare-outline' as const, label: 'Compare stores', prompt: 'Compare the stores I use and show where I usually save most.' },
];

export default function AgentScreen() {
  const { colors: C } = useTheme();
  const [msgs, setMsgs]         = useState<Msg[]>([
    {
      role: 'agent',
      text: 'Ready. Ask about your receipts, prices, stores, spending, or what to buy from your purchase history.',
    }
  ]);
  const [input, setInput]       = useState('');
  const [loading, setLoading]   = useState(false);
  const [voiceMode, setVoiceMode] = useState<VoiceMode>(null);
  const [voiceText, setVoiceText] = useState('');
  const [sessionId, setSessionId] = useState('');
  const scrollRef               = useRef<ScrollView>(null);
  const voiceModeRef            = useRef<VoiceMode>(null);
  const wakeRestartRef          = useRef<any>(null);

  useEffect(() => {
    let active = true;
    async function restoreSession() {
      const ownerId = getUser()?.id || getGuestSessionId() || 'anonymous';
      const key = `receiptai:agent-session:${ownerId}`;
      const stored = await AsyncStorage.getItem(key).catch(() => null);
      const value = stored || `session_${Date.now()}_${Math.random().toString(36).slice(2, 8)}`;
      if (!stored) await AsyncStorage.setItem(key, value).catch(() => {});
      if (!active) return;
      setSessionId(value);
      try {
        const guestId = getGuestSessionId();
        const token = getUserToken();
        const params = new URLSearchParams({ session_id: value });
        if (guestId) params.set('guest_session_id', guestId);
        const headers:any = {};
        if (!guestId && token && token !== 'guest') headers.Authorization = `Bearer ${token}`;
        const response = await fetch(`${API}/agent/history?${params.toString()}`, { headers });
        if (!response.ok) return;
        const data = await response.json();
        const restored: Msg[] = (data.messages || []).map((row:any) => ({
          role: row.role === 'user' ? 'user' : 'agent',
          text: String(row.content || ''),
        })).filter((row:Msg) => row.text);
        if (active && restored.length) setMsgs(restored);
      } catch {}
    }
    restoreSession();
    return () => { active = false; };
  }, []);

  useFocusEffect(useCallback(() => {}, []));

  function scrollToBottom() {
    setTimeout(() => scrollRef.current?.scrollToEnd({ animated: true }), 100);
  }

  function cleanWakeCommand(text: string) {
    return text
      .replace(/hey\s+receipt\s*ai/ig, '')
      .replace(/hey\s+receiptai/ig, '')
      .replace(/receipt\s*ai/ig, '')
      .trim();
  }

  function voiceUnavailable() {
    const isExpoGo = Constants.appOwnership === 'expo';
    Alert.alert(
      isExpoGo ? 'Voice build required' : 'Voice recognition unavailable',
      isExpoGo
        ? 'Voice recognition is not supported inside Expo Go. Install and open the ReceiptAI APK instead.'
        : 'This installation does not contain the current voice recognition module. Install the latest ReceiptAI APK and try again.'
    );
  }

  function voicePermissionDenied(canAskAgain: boolean) {
    Alert.alert(
      'Microphone permission needed',
      canAskAgain
        ? 'Allow microphone access to ask ReceiptAI questions by voice.'
        : 'Microphone access is disabled. Open Android settings and allow it for ReceiptAI.',
      canAskAgain
        ? [{ text: 'OK' }]
        : [{ text: 'Cancel', style: 'cancel' }, { text: 'Open settings', onPress: () => Linking.openSettings() }]
    );
  }

  function voiceRecognitionError(code?: string, message?: string) {
    if (code === 'aborted') return;
    if (code === 'not-allowed') {
      voicePermissionDenied(false);
      return;
    }
    if (code === 'no-speech' || code === 'speech-timeout') {
      Alert.alert('No speech heard', 'Please tap the microphone and speak again.');
      return;
    }
    if (code === 'network') {
      Alert.alert('Voice network error', 'Speech recognition could not reach its service. Check your connection and try again.');
      return;
    }
    if (code === 'busy') {
      Alert.alert('Voice is busy', 'Wait a moment, then tap the microphone again.');
      return;
    }
    if (code === 'service-not-allowed' || code === 'language-not-supported') {
      Alert.alert(
        'Speech service unavailable',
        'Enable Google voice typing or the device speech recognition service in Android settings, then try again.',
        [{ text: 'Cancel', style: 'cancel' }, { text: 'Open settings', onPress: () => Linking.openSettings() }]
      );
      return;
    }
    Alert.alert('Voice error', message || 'Voice recognition could not start. Please try again.');
  }

  async function stopVoice() {
    const Voice = getVoiceModule();
    if (wakeRestartRef.current) clearTimeout(wakeRestartRef.current);
    wakeRestartRef.current = null;
    voiceModeRef.current = null;
    setVoiceMode(null);
    setVoiceText('');
    if (!Voice) return;
    try { Voice.abort(); } catch {}
  }

  async function startVoice(mode: Exclude<VoiceMode, null>) {
    if (loading) return;
    try {
      const Voice = getVoiceModule();
      if (!Voice) {
        voiceUnavailable();
        return;
      }
      const permission = await Voice.requestPermissionsAsync();
      if (!permission.granted) {
        voicePermissionDenied(permission.canAskAgain !== false);
        return;
      }
      const available = Voice.isRecognitionAvailable();
      if (!available) {
        voiceRecognitionError('service-not-allowed');
        return;
      }
      if (voiceModeRef.current) {
        const currentMode = voiceModeRef.current;
        await stopVoice();
        if (currentMode === mode) return;
      }
      voiceModeRef.current = mode;
      setVoiceMode(mode);
      setVoiceText(mode === 'wake' ? 'Say "Hey ReceiptAI" then your question.' : 'Listening...');
      Voice.start({ lang: 'en-US', interimResults: true, continuous: mode === 'wake', maxAlternatives: 3 });
    } catch (e: any) {
      setVoiceMode(null);
      voiceModeRef.current = null;
      const message = String(e?.message || e);
      if (message.toLowerCase().includes('native') || message.toLowerCase().includes('module')) voiceUnavailable();
      else voiceRecognitionError(undefined, message);
    }
  }

  async function restartWakeListening() {
    const Voice = getVoiceModule();
    if (voiceModeRef.current !== 'wake') return;
    if (!Voice) {
      voiceModeRef.current = null;
      setVoiceMode(null);
      return;
    }
    try {
      Voice.start({ lang: 'en-US', interimResults: true, continuous: true, maxAlternatives: 3 });
    } catch {
      voiceModeRef.current = null;
      setVoiceMode(null);
    }
  }

  function handleSpeechText(text: string, isFinal = false) {
    const spoken = text.trim();
    if (!spoken) return;
    setVoiceText(spoken);

    if (voiceModeRef.current === 'wake') {
      const lower = spoken.toLowerCase();
      const heardWake = lower.includes('hey receiptai') || lower.includes('hey receipt ai') || lower.includes('receipt ai');
      if (!heardWake) return;
      const command = cleanWakeCommand(spoken);
      if (command) {
        stopVoice();
        sendMessage(command);
      } else {
        setVoiceText('Wake word heard. Ask your question now.');
      }
      return;
    }

    setInput(spoken);
    if (isFinal) stopVoice();
  }

  useEffect(() => {
    const Voice = getVoiceModule();
    if (!Voice) return;
    const resultSubscription = Voice.addListener('result', (e: any) => {
      handleSpeechText(e.results?.[0]?.transcript || '', Boolean(e.isFinal));
    });
    const errorSubscription = Voice.addListener('error', (e: any) => {
      if (e.error === 'aborted') return;
      if (voiceModeRef.current === 'wake') {
        wakeRestartRef.current = setTimeout(restartWakeListening, 700);
      } else {
        stopVoice();
        voiceRecognitionError(e.error, e.message);
      }
    });
    const endSubscription = Voice.addListener('end', () => {
      if (voiceModeRef.current === 'wake') {
        wakeRestartRef.current = setTimeout(restartWakeListening, 700);
      }
    });
    return () => {
      if (wakeRestartRef.current) clearTimeout(wakeRestartRef.current);
      resultSubscription.remove();
      errorSubscription.remove();
      endSubscription.remove();
      try { Voice.abort(); } catch {}
    };
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  async function sendMessage(text: string) {
    const message = text.trim();
    if (!message || loading || !sessionId) return;

    setInput('');
    const userMsg: Msg = { role: 'user', text: message };
    const loadingMsg: Msg = { role: 'agent', text: '', loading: true };

    setMsgs(prev => [...prev, userMsg, loadingMsg]);
    setLoading(true);
    scrollToBottom();

    try {
      const controller = new AbortController();
      const timeout = setTimeout(() => controller.abort(), 45000);
      const token = getUserToken();
      const headers: any = { 'Content-Type': 'application/json' };
      if (token) headers['Authorization'] = `Bearer ${token}`;

      let res: Response;
      try {
        res = await fetch(`${API}/agent/chat`, {
          method:  'POST',
          headers,
          signal: controller.signal,
          body: JSON.stringify({ message, session_id: sessionId, guest_session_id: getGuestSessionId() || undefined }),
        });
      } finally {
        clearTimeout(timeout);
      }

      const raw = await res.text();
      let data: any = {};
      try {
        data = raw ? JSON.parse(raw) : {};
      } catch {
        data = { detail: raw };
      }

      if (!res.ok) {
        throw new Error(friendlyAgentError(data.detail || data.message || 'Agent error'));
      }

      const agentMsg: Msg = {
        role:  'agent',
        text:  data.response || 'I could not get an answer. Please try again.',
        answerCard: data.answer_card || null,
        ragTrace: data.rag_trace || null,
        tools: data.tools_used || [],
        traceExpanded: false,
      };

      setMsgs(prev => [...prev.slice(0, -1), agentMsg]);

    } catch (e: any) {
      const errMsg: Msg = {
        role: 'agent',
        text: e?.name === 'AbortError'
          ? 'That answer took too long. Please try again.'
          : friendlyAgentError(e.message || 'Could not connect'),
      };
      setMsgs(prev => [...prev.slice(0, -1), errMsg]);
    } finally {
      setLoading(false);
      scrollToBottom();
    }
  }

  async function clearConversation() {
    Alert.alert('Clear conversation', 'Start a fresh conversation with AI Generator?', [
      { text: 'Cancel', style: 'cancel' },
      {
        text: 'Clear',
        onPress: async () => {
          try {
            const token = getUserToken();
            const headers: any = { 'Content-Type': 'application/json' };
            if (token) headers['Authorization'] = `Bearer ${token}`;
            await fetch(`${API}/agent/clear`, {
              method: 'POST', headers,
              body: JSON.stringify({ session_id: sessionId, guest_session_id: getGuestSessionId() || undefined }),
            });
          } catch {}
          setMsgs([{
            role: 'agent',
            text: 'Fresh start. Ask about your receipts, prices, or spending.',
          }]);
        }
      }
    ]);
  }

  function previousUserMessage(agentIndex: number) {
    for (let i = agentIndex - 1; i >= 0; i--) {
      if (msgs[i]?.role === 'user') return msgs[i].text;
    }
    return '';
  }

  async function copyMessage(text: string, label = 'Message') {
    const value = text.trim();
    if (!value) return;
    try {
      await Clipboard.setStringAsync(value);
      Alert.alert('Copied', `${label} copied to clipboard.`);
    } catch {
      Alert.alert('Copy failed', 'Please try again.');
    }
  }

  function editUserMessage(text: string) {
    setInput(text);
    scrollToBottom();
  }

  function retryAgentMessage(agentIndex: number) {
    const message = previousUserMessage(agentIndex);
    if (!message || loading) return;
    sendMessage(message);
  }

  async function askForCorrection() {
    const alertPrompt = (Alert as any).prompt;
    if (typeof alertPrompt === 'function') {
      return await new Promise<string>((resolve) => {
        alertPrompt(
          'Teach ReceiptAI',
          'What should the answer or item match have been?',
          [
            { text: 'Cancel', style: 'cancel', onPress: () => resolve('') },
            { text: 'Save', onPress: (value: string) => resolve(value || '') },
          ],
          'plain-text'
        );
      });
    }
    return '';
  }

  async function sendFeedback(agentIndex: number, rating: 'correct' | 'wrong') {
    const agentMsg = msgs[agentIndex];
    const message = previousUserMessage(agentIndex);
    if (!agentMsg || agentMsg.role !== 'agent' || !message || agentMsg.feedbackSent) return;

    const correction = rating === 'wrong' ? (await askForCorrection()).trim() : '';

    setMsgs(prev => prev.map((msg, idx) => idx === agentIndex ? { ...msg, feedbackSent: true } : msg));

    try {
      const token = getUserToken();
      const headers: any = { 'Content-Type': 'application/json' };
      if (token) headers['Authorization'] = `Bearer ${token}`;
      await fetch(`${API}/agent/feedback`, {
        method: 'POST',
        headers,
        body: JSON.stringify({
          session_id: sessionId,
          guest_session_id: getGuestSessionId() || undefined,
          message,
          response: agentMsg.text,
          expected_response: rating === 'correct' ? agentMsg.text : correction,
          correction_note: correction || undefined,
          rating,
        }),
      });
    } catch {
      setMsgs(prev => prev.map((msg, idx) => idx === agentIndex ? { ...msg, feedbackSent: false } : msg));
      Alert.alert('Feedback not saved', 'Please try again when the backend is reachable.');
    }
  }

  async function sendMatchCorrection(agentIndex: number, matchedItem: string) {
    const message = previousUserMessage(agentIndex);
    if (!message) return;

    const correction = await (() => {
      const alertPrompt = (Alert as any).prompt;
      if (typeof alertPrompt === 'function') {
        return new Promise<string>((resolve) => {
          alertPrompt(
            'Wrong match',
            `"${matchedItem}" was matched incorrectly.\nWhat should it be? (optional)`,
            [
              { text: 'Cancel', style: 'cancel', onPress: () => resolve('') },
              { text: 'Report', onPress: (v: string) => resolve(v || '') },
            ],
            'plain-text'
          );
        });
      }
      return Promise.resolve('');
    })();

    try {
      const token = getUserToken();
      const headers: any = { 'Content-Type': 'application/json' };
      if (token) headers['Authorization'] = `Bearer ${token}`;
      await fetch(`${API}/agent/feedback`, {
        method: 'POST',
        headers,
        body: JSON.stringify({
          session_id: sessionId,
          guest_session_id: getGuestSessionId() || undefined,
          message,
          response: matchedItem,
          rating: 'wrong',
          correction_note: correction || undefined,
          alias_term: matchedItem,
          alias_value: correction || undefined,
        }),
      });
      Alert.alert('Reported', 'ReceiptAI will avoid this match for you going forward.');
    } catch {
      Alert.alert('Not saved', 'Could not save correction. Try again when connected.');
    }
  }

  function renderRagTrace(msg: Msg, index: number) {
    const trace = msg.ragTrace;
    if (!trace) return null;
    const rows: RagTraceRow[] = Array.isArray(trace.evidence) ? trace.evidence.slice(0, 8) : [];
    if (!rows.length) return null;

    const expanded = msg.traceExpanded ?? false;
    const pipeline = trace.retrieval_pipeline || {};
    const matchedCount = trace.matched_event_count ?? trace.evidence_count ?? rows.length;
    const traceLabel = `Matched ${matchedCount} verified purchase${matchedCount !== 1 ? 's' : ''}`;

    return (
      <View style={[s.traceBox, { borderColor: C.border, backgroundColor: C.surface }]}>
        <TouchableOpacity
          style={s.traceHeader}
          onPress={() => setMsgs(prev => prev.map((m, i) => i === index ? { ...m, traceExpanded: !m.traceExpanded } : m))}
          activeOpacity={0.7}
        >
          <Ionicons name="search-outline" size={12} color={C.text3} />
          <Text style={[s.traceHeaderTxt, { color: C.text3 }]}>
            {traceLabel}
          </Text>
          <Ionicons name={expanded ? 'chevron-up' : 'chevron-down'} size={12} color={C.text3} />
        </TouchableOpacity>
        {expanded && pipeline.embedding_model ? (
          <View style={[s.tracePipeline, { borderTopColor: C.border }]}>
            <Text style={[s.traceMeta, { color: C.text3 }]} numberOfLines={2}>
              {pipeline.embedding_model} · {pipeline.reranker || 'evidence reranker'}
              {matchedCount > rows.length ? ` · showing ${rows.length} of ${matchedCount}` : ''}
            </Text>
          </View>
        ) : null}
        {expanded && rows.map((row, ri) => (
          <View key={ri} style={[s.traceRow, { borderTopColor: C.border }]}>
            <View style={{ flex: 1 }}>
              <Text style={[s.traceItem, { color: C.text2 }]} numberOfLines={1}>{traceRowItem(row)}</Text>
              <Text style={[s.traceMeta, { color: C.text3 }]} numberOfLines={1}>
                {[row.store, row.date].filter(Boolean).join('  ·  ')}
                {row.match_score != null ? `  ·  score ${(row.match_score * 100).toFixed(0)}%` : ''}
              </Text>
            </View>
            <View style={s.traceRight}>
              {displayPrice(row.price) ? <Text style={[s.tracePrice, { color: C.text2 }]}>{displayPrice(row.price)}</Text> : null}
              <TouchableOpacity
                style={[s.traceWrongBtn, { borderColor: C.border }]}
                onPress={() => sendMatchCorrection(index, traceRowItem(row))}
                activeOpacity={0.7}
                accessibilityLabel="Report incorrect match"
              >
                <Ionicons name="thumbs-down-outline" size={13} color={C.text3} />
              </TouchableOpacity>
            </View>
          </View>
        ))}
      </View>
    );
  }

  function renderAnswerCard(card?: AgentAnswerCard | null) {
    if (!card) return null;
    const rows = card.rows || [];
    const actionReceiptId = card.receipt_id || rows.find(row => row.receipt_id)?.receipt_id;
    const canFindReceipt = Boolean(actionReceiptId);

    return (
      <View style={[s.answerCard, { backgroundColor: C.surface, borderColor: C.border }]}>
        <View style={s.answerCardHead}>
          <View style={[s.answerCardIcon, { backgroundColor: 'rgba(106,255,212,0.10)', borderColor: 'rgba(106,255,212,0.26)' }]}>
            <Ionicons name={card.type === 'category_list' ? 'list-outline' : 'pricetag-outline'} size={15} color={C.accent3} />
          </View>
          <View style={{ flex: 1 }}>
            <Text style={[s.answerCardKicker, { color: C.accent3 }]}>Evidence</Text>
            <Text style={[s.answerCardTitle, { color: C.text }]} numberOfLines={2}>{card.title || 'Receipt evidence'}</Text>
          </View>
        </View>

        {rows.length ? (
          <View style={s.answerRows}>
            {rows.map((row, idx) => {
              const rowReceiptId = row.receipt_id;
              const rowCanOpen = Boolean(rowReceiptId);
              return (
              <TouchableOpacity
                key={`${row.item}-${idx}`}
                style={[s.answerRow, rowCanOpen && s.answerRowTap, { borderTopColor: C.border }]}
                onPress={() => rowCanOpen && router.push({ pathname: '/receipts', params: { receiptId: String(rowReceiptId) } })}
                disabled={!rowCanOpen}
                activeOpacity={0.78}
              >
                <View style={{ flex: 1 }}>
                  <Text style={[s.answerRowItem, { color: C.text }]} numberOfLines={1}>{row.item || 'Item'}</Text>
                  <Text style={[s.answerRowMeta, { color: C.text2 }]} numberOfLines={2}>
                    {[row.store, row.date, row.detail].filter(Boolean).join('  |  ')}
                  </Text>
                </View>
                <View style={s.answerRowRight}>
                  <Text style={[s.answerRowPrice, { color: C.accent3 }]}>{displayPrice(row.price, row.price || '')}</Text>
                  {rowCanOpen ? <Ionicons name="open-outline" size={13} color={C.accent} /> : null}
                </View>
              </TouchableOpacity>
            );})}
          </View>
        ) : (
          <>
            <Text style={[s.answerMainItem, { color: C.text }]} numberOfLines={2}>{card.item || 'Matched item'}</Text>
            <View style={s.answerMetrics}>
              <View style={[s.answerMetric, { backgroundColor: C.surface2, borderColor: C.border }]}>
                <Text style={[s.answerMetricLabel, { color: C.text3 }]}>Price</Text>
                <Text style={[s.answerMetricValue, { color: C.accent3 }]} numberOfLines={1}>{displayPrice(card.price, card.price || 'N/A')}</Text>
              </View>
              <View style={[s.answerMetric, { backgroundColor: C.surface2, borderColor: C.border }]}>
                <Text style={[s.answerMetricLabel, { color: C.text3 }]}>Store</Text>
                <Text style={[s.answerMetricValue, { color: C.text }]} numberOfLines={1}>{card.store || 'Unknown'}</Text>
              </View>
            </View>
            <View style={[s.answerSource, { borderTopColor: C.border }]}>
              <Ionicons name="receipt-outline" size={14} color={C.text3} />
              <Text style={[s.answerSourceText, { color: C.text2 }]} numberOfLines={2}>
                {[card.date, card.detail].filter(Boolean).join('  |  ')}
              </Text>
            </View>
          </>
        )}

        {card.note ? <Text style={[s.answerNote, { color: C.text2 }]}>{card.note}</Text> : null}
        {canFindReceipt ? (
          <TouchableOpacity
            style={[s.answerAction, { borderColor: C.border, backgroundColor: C.surface2 }]}
            onPress={() => router.push({ pathname: '/receipts', params: { receiptId: String(actionReceiptId || '') } })}
            activeOpacity={0.8}
          >
            <Ionicons name="open-outline" size={14} color={C.accent} />
            <Text style={[s.answerActionText, { color: C.accent }]}>Open receipt</Text>
          </TouchableOpacity>
        ) : null}
      </View>
    );
  }

  function renderMessage(msg: Msg, index: number) {
    const isUser = msg.role === 'user';

    if (msg.loading) {
      return (
        <View key={index} style={s.msgRow}>
          <View style={[s.agentAvatar, { backgroundColor: 'rgba(124,106,255,0.15)' }]}>
            <Ionicons name="sparkles" size={15} color={C.accent} />
          </View>
          <View style={[s.bubble, s.agentBubble, { backgroundColor: C.surface2, borderColor: C.border }]}>
            <View style={{ flexDirection: 'row', alignItems: 'center', gap: 8 }}>
              <ActivityIndicator size="small" color={C.accent} />
              <Text style={{ color: C.text2, fontSize: 13 }}>Thinking and analyzing...</Text>
            </View>
          </View>
        </View>
      );
    }

    if (isUser) {
      return (
        <View key={index} style={[s.msgRow, s.userRow]}>
          <View style={s.userMessageWrap}>
            <View style={[s.bubble, s.userBubble, { backgroundColor: C.accent }]}>
              <Text style={[s.bubbleTxt, { color: '#fff' }]}>{msg.text}</Text>
            </View>
            <View style={s.userActionRow}>
              <TouchableOpacity
                style={s.iconActionBtn}
                onPress={() => copyMessage(msg.text, 'Question')}
                activeOpacity={0.75}
                accessibilityRole="button"
                accessibilityLabel="Copy question"
              >
                <Ionicons name="copy-outline" size={16} color={C.text3} />
              </TouchableOpacity>
              <TouchableOpacity
                style={s.iconActionBtn}
                onPress={() => editUserMessage(msg.text)}
                activeOpacity={0.75}
                accessibilityRole="button"
                accessibilityLabel="Edit question"
              >
                <Ionicons name="create-outline" size={16} color={C.text3} />
              </TouchableOpacity>
            </View>
          </View>
        </View>
      );
    }

    const formattedText = msg.answerCard ? formatAgentText(msg.text).split('\n')[0] : formatAgentText(msg.text);
    const tableLike = msg.text.includes('|');
    const canSendFeedback = Boolean(previousUserMessage(index));

    return (
      <View key={index} style={s.msgRow}>
        <View style={[s.agentAvatar, { backgroundColor: 'rgba(124,106,255,0.15)' }]}>
          <Ionicons name="sparkles" size={15} color={C.accent} />
        </View>
        <View style={{ flex: 1 }}>
          {formattedText ? (
            <View style={[s.bubble, s.agentBubble, msg.answerCard && s.answerLeadBubble, { backgroundColor: C.surface2, borderColor: C.border }]}>
              <Text style={[s.bubbleTxt, tableLike && !msg.answerCard && s.tableTxt, msg.answerCard && s.answerLeadTxt, { color: C.text }]}>{formattedText}</Text>
            </View>
          ) : null}
          {renderAnswerCard(msg.answerCard)}
          {renderRagTrace(msg, index)}
          {canSendFeedback ? <View style={s.feedbackRow}>
            {msg.feedbackSent ? (
              <Text style={[s.feedbackSaved, { color: C.text3 }]}>Feedback saved</Text>
            ) : (
              <>
                <TouchableOpacity
                  style={[s.iconFeedbackBtn, { borderColor: C.border, backgroundColor: C.surface2 }]}
                  onPress={() => sendFeedback(index, 'correct')}
                  activeOpacity={0.8}
                  accessibilityRole="button"
                  accessibilityLabel="Mark answer correct"
                >
                  <Ionicons name="thumbs-up-outline" size={13} color={C.accent3} />
                </TouchableOpacity>
                <TouchableOpacity
                  style={[s.iconFeedbackBtn, { borderColor: C.border, backgroundColor: C.surface2 }]}
                  onPress={() => sendFeedback(index, 'wrong')}
                  activeOpacity={0.8}
                  accessibilityRole="button"
                  accessibilityLabel="Mark answer wrong"
                >
                  <Ionicons name="thumbs-down-outline" size={13} color={C.text3} />
                </TouchableOpacity>
              </>
            )}
            <TouchableOpacity
              style={[s.iconFeedbackBtn, { borderColor: C.border, backgroundColor: C.surface2 }]}
              onPress={() => copyMessage(formatAgentText(msg.text), 'Answer')}
              activeOpacity={0.8}
              accessibilityRole="button"
              accessibilityLabel="Copy answer"
            >
              <Ionicons name="copy-outline" size={13} color={C.text3} />
            </TouchableOpacity>
            <TouchableOpacity
              style={[s.iconFeedbackBtn, { borderColor: C.border, backgroundColor: C.surface2 }, loading && { opacity: 0.45 }]}
              onPress={() => retryAgentMessage(index)}
              disabled={loading}
              activeOpacity={0.8}
              accessibilityRole="button"
              accessibilityLabel="Retry answer"
            >
              <Ionicons name="refresh-outline" size={13} color={C.text3} />
            </TouchableOpacity>
          </View> : null}
        </View>
      </View>
    );
  }

  return (
    <KeyboardAvoidingView
      style={[s.screen, { backgroundColor: C.bg }]}
      behavior={Platform.OS === 'ios' ? 'padding' : undefined}
      keyboardVerticalOffset={90}
    >
      {/* Header info */}
      <View style={[s.agentHeader, { backgroundColor: C.bg, borderBottomColor: C.border }]}>
        <View style={s.agentHeaderLeft}>
          <View style={s.miniPrismLogo}><View style={s.miniPrismViolet} /><View style={s.miniPrismMint} /></View>
          <Text style={[s.agentHeaderTxt, { color: C.text }]}>ReceiptAI</Text>
        </View>
        <View style={s.headerActions}>
          <TouchableOpacity
            style={[
              s.wakeBtn,
              { borderColor: C.border, backgroundColor: voiceMode === 'wake' ? 'rgba(74,222,128,0.12)' : C.surface2 },
            ]}
            onPress={() => voiceMode === 'wake' ? stopVoice() : startVoice('wake')}
            activeOpacity={0.8}
            accessibilityLabel={voiceMode === 'wake' ? 'Stop Hey ReceiptAI listening' : 'Enable Hey ReceiptAI listening'}
          >
            <Ionicons name={voiceMode === 'wake' ? 'ear' : 'ear-outline'} size={14} color={voiceMode === 'wake' ? C.green : C.accent} />
          </TouchableOpacity>
          <TouchableOpacity style={[s.headerRound, { backgroundColor:C.surface, borderColor:C.border }]} onPress={clearConversation} accessibilityLabel="Clear AI conversation">
            <Ionicons name="refresh-outline" size={16} color={C.text2} />
          </TouchableOpacity>
        </View>
      </View>

      {/* Messages */}
      <ScrollView
        ref={scrollRef}
        style={s.chat}
        contentContainerStyle={s.chatContent}
        showsVerticalScrollIndicator={false}
        keyboardShouldPersistTaps="handled"
      >
        {/* Quick prompts - only show at start */}
        {msgs.length <= 1 && (
          <View style={s.quickSection}>
            <View style={[s.agentIntro, { backgroundColor: C.surface, borderColor: C.border }]}>
              <View style={[s.agentIntroIcon, { backgroundColor: C.accent }]}>
                <View style={s.prismOrbPink} />
                <View style={s.prismOrbMint} />
                <Ionicons name="sparkles" size={23} color="#FFFEFA" />
              </View>
              <View style={{ flex: 1 }}>
                <Text style={[s.agentIntroKicker, { color: C.accent3 }]}>Your receipt intelligence</Text>
                <Text style={[s.agentIntroTitle, { color: C.text }]}>AI Generator</Text>
                <Text style={[s.agentIntroText, { color: C.text2 }]}>
                  Turn your receipt history into one clear answer, whenever you need it.
                </Text>
              </View>
            </View>
            <Text style={[s.quickLabel, { color: C.text3 }]}>Start with</Text>
            <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={s.starterList}>
              {PRISM_STARTERS.map((q) => (
                <TouchableOpacity
                  key={q.label}
                  style={[s.starterCard, { backgroundColor: C.surface, borderColor: C.border }]}
                  onPress={() => sendMessage(q.prompt)}
                  activeOpacity={0.82}
                >
                  <Text style={[s.starterLabel, { color: C.text }]}>{q.label}</Text>
                </TouchableOpacity>
              ))}
            </ScrollView>
            <View style={s.aiPoster}>
              <View style={s.aiPosterGlow} />
              <Text style={s.aiPosterKicker}>Built from your receipt memory</Text>
              <Text style={s.aiPosterTitle}>Ask once. Get one clear answer grounded in what you actually bought.</Text>
              <View style={s.aiPosterSource}>
                <Text style={s.aiPosterSourceText}>Prices · stores · spending</Text>
                <Text style={s.aiPosterSourceReady}>Sources connected</Text>
              </View>
            </View>
          </View>
        )}

        {/* Messages */}
        {msgs.map((msg, i) => renderMessage(msg, i))}
      </ScrollView>

      {/* Input */}
      <View style={[s.inputBar, { backgroundColor: C.bg, borderTopColor: C.border }]}>
        <TextInput
          style={[s.input, { backgroundColor: C.surface, borderColor: 'rgba(255,255,255,0.9)', color: C.text }]}
          placeholder="Ask about receipts, prices, stores, spending..."
          placeholderTextColor={C.text3}
          value={input}
          onChangeText={setInput}
          onSubmitEditing={() => sendMessage(input)}
          returnKeyType="send"
          multiline
          maxLength={500}
        />
        <TouchableOpacity
          style={[
            s.micBtn,
            { backgroundColor: voiceMode === 'dictate' ? C.green : C.surface2, borderColor: C.border },
          ]}
          onPress={() => voiceMode === 'dictate' ? stopVoice() : startVoice('dictate')}
          disabled={loading}
          activeOpacity={0.85}
        >
          <Ionicons name={voiceMode === 'dictate' ? 'mic' : 'mic-outline'} size={20} color={voiceMode === 'dictate' ? '#06120b' : C.accent} />
        </TouchableOpacity>
        <TouchableOpacity
          style={[s.sendBtn, { backgroundColor: C.accent }, (!input.trim() || loading) && { opacity: 0.35 }]}
          onPress={() => sendMessage(input)}
          disabled={!input.trim() || loading}
          activeOpacity={0.85}
        >
          {loading
            ? <ActivityIndicator size="small" color="#fff" />
            : <Ionicons name="arrow-up" size={20} color="#fff" />
          }
        </TouchableOpacity>
      </View>
      {voiceMode ? (
        <View style={[s.voiceHint, { backgroundColor: C.surface2, borderColor: C.border }]}>
          <Text style={[s.voiceHintTxt, { color: C.text2 }]} numberOfLines={1}>
            {voiceText || 'Listening...'}
          </Text>
          <TouchableOpacity onPress={stopVoice}>
            <Text style={{ color: C.accent, fontSize: 12, fontWeight: '800' }}>Stop</Text>
          </TouchableOpacity>
        </View>
      ) : null}
    </KeyboardAvoidingView>
  );
}

const s = StyleSheet.create({
  screen:       { flex: 1 },
  agentHeader:  { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', paddingHorizontal: 18, paddingTop: 12, paddingBottom: 6, borderBottomWidth: 0 },
  agentHeaderLeft: { flexDirection: 'row', alignItems: 'center', gap: 6 },
  headerActions:{ flexDirection: 'row', alignItems: 'center', gap: 7 },
  miniPrismLogo:{ position:'relative', width:28, height:28, marginRight:2 },
  miniPrismViolet:{ position:'absolute', left:2, top:2, width:16, height:23, borderRadius:6, borderBottomRightRadius:9, backgroundColor:'#6557FF', transform:[{rotate:'-8deg'}] },
  miniPrismMint:{ position:'absolute', right:2, bottom:1, width:16, height:22, borderRadius:6, borderBottomRightRadius:9, backgroundColor:'#54D9D2', opacity:0.82, transform:[{rotate:'8deg'}] },
  headerRound:{ width:40, height:40, borderRadius:15, borderBottomRightRadius:7, borderWidth:1, alignItems:'center', justifyContent:'center' },
  agentDot:     { width: 6, height: 6, borderRadius: 3 },
  agentHeaderTxt: { fontSize: 13, fontWeight:'800' },
  wakeBtn:      { width:40, height:40, flexDirection: 'row', alignItems: 'center', justifyContent:'center', borderWidth: 1, borderRadius: 15, borderBottomRightRadius:7 },
  wakeTxt:      { fontSize: 10, fontWeight: '800' },
  chat:         { flex: 1 },
  chatContent:  { padding: 18, paddingBottom: 12 },
  quickSection: { marginBottom: 20 },
  agentIntro:   { alignItems: 'flex-start', gap: 12, borderWidth: 0, borderRadius: 0, padding: 0, marginBottom: 17, shadowOpacity: 0, elevation: 0 },
  agentIntroIcon:{ width: 66, height: 66, borderRadius: 24, borderBottomRightRadius: 8, borderWidth: 0, alignItems: 'center', justifyContent: 'center', shadowColor:'#6557FF', shadowOpacity:0.24, shadowRadius:18, shadowOffset:{width:0,height:10}, elevation:5 },
  prismOrbPink:{ position:'absolute', width:44, height:44, borderRadius:22, right:-7, top:-8, backgroundColor:'rgba(244,155,207,0.72)' },
  prismOrbMint:{ position:'absolute', width:38, height:38, borderRadius:19, left:-9, bottom:-8, backgroundColor:'rgba(84,217,210,0.76)' },
  agentIntroKicker:{ fontSize: 10, fontWeight: '900', textTransform: 'uppercase', letterSpacing: 1.25, marginBottom: 5 },
  agentIntroTitle:{ fontSize: 35, lineHeight: 39, fontFamily:Platform.OS === 'android' ? 'serif' : 'Georgia', fontWeight: '400', letterSpacing: -1.1, marginBottom: 6 },
  agentIntroText:{ fontSize: 13, lineHeight: 19 },
  quickLabel:   { fontSize: 10, letterSpacing: 0.5, textTransform: 'uppercase', marginBottom: 10 },
  starterList:  { gap: 7, paddingRight: 4, marginBottom: 15 },
  starterCard:  { minHeight: 36, flexDirection: 'row', alignItems: 'center', borderWidth: 1, borderRadius: 99, paddingHorizontal: 13, paddingVertical: 8 },
  starterIcon:  { width: 36, height: 36, borderRadius: 12, borderWidth: 1, alignItems: 'center', justifyContent: 'center' },
  starterLabel: { fontSize: 11, lineHeight: 16, fontWeight: '800' },
  aiPoster:{ position:'relative', overflow:'hidden', minHeight:210, padding:20, borderRadius:31, borderBottomRightRadius:11, backgroundColor:'#272432', marginBottom:12, shadowColor:'#36243E', shadowOpacity:0.24, shadowRadius:24, shadowOffset:{width:0,height:14}, elevation:7 },
  aiPosterGlow:{ position:'absolute', width:175, height:175, borderRadius:90, right:-63, bottom:-88, backgroundColor:'rgba(244,155,207,0.20)' },
  aiPosterKicker:{ color:'rgba(255,254,250,0.66)', fontSize:9, fontWeight:'900', textTransform:'uppercase', letterSpacing:1.1 },
  aiPosterTitle:{ color:'#FFFEFA', fontSize:24, lineHeight:28, fontFamily:Platform.OS === 'android' ? 'serif' : 'Georgia', fontWeight:'400', marginTop:17, maxWidth:305 },
  aiPosterSource:{ flexDirection:'row', alignItems:'center', justifyContent:'space-between', gap:10, borderTopWidth:1, borderTopColor:'rgba(255,255,255,0.10)', marginTop:20, paddingTop:13 },
  aiPosterSourceText:{ color:'rgba(255,254,250,0.58)', fontSize:9, fontWeight:'700' },
  aiPosterSourceReady:{ color:'#C8F37C', fontSize:9, fontWeight:'900' },
  msgRow:       { flexDirection: 'row', alignItems: 'flex-start', marginBottom: 14, gap: 8 },
  userRow:      { justifyContent: 'flex-end' },
  userMessageWrap:{ alignItems: 'flex-end', maxWidth: '86%' },
  userActionRow:{ flexDirection: 'row', justifyContent: 'flex-end', gap: 6, marginTop: 5, paddingRight: 2 },
  iconActionBtn:{ width: 26, height: 24, borderRadius: 8, alignItems: 'center', justifyContent: 'center' },
  agentAvatar:  { width: 30, height: 30, borderRadius: 11, alignItems: 'center', justifyContent: 'center', flexShrink: 0, marginTop: 2 },
  bubble:       { maxWidth: '86%', borderRadius: 16, padding: 13, paddingHorizontal: 15 },
  agentBubble:  { borderWidth: 1, borderBottomLeftRadius: 4 },
  userBubble:   { borderBottomRightRadius: 4, shadowColor: '#000', shadowOpacity: 0.18, shadowRadius: 10, shadowOffset: { width: 0, height: 6 }, elevation: 3 },
  bubbleTxt:    { fontSize: 14, lineHeight: 21 },
  tableTxt:     { fontSize: 12, lineHeight: 18, fontFamily: Platform.OS === 'ios' ? 'Menlo' : 'monospace' },
  answerLeadBubble:{ paddingVertical: 10, borderRadius: 12 },
  answerLeadTxt:{ fontSize: 13, lineHeight: 18, fontWeight: '800' },
  answerCard:   { maxWidth: '86%', borderWidth: 1, borderRadius: 16, padding: 14, marginTop: 8, shadowColor: '#000', shadowOpacity: 0.20, shadowRadius: 14, shadowOffset: { width: 0, height: 8 }, elevation: 4 },
  answerCardHead:{ flexDirection: 'row', alignItems: 'center', gap: 9, marginBottom: 10 },
  answerCardIcon:{ width: 30, height: 30, borderRadius: 9, borderWidth: 1, alignItems: 'center', justifyContent: 'center' },
  answerCardKicker:{ fontSize: 9, fontWeight: '900', textTransform: 'uppercase', letterSpacing: 0.7 },
  answerCardTitle:{ fontSize: 15, lineHeight: 19, fontWeight: '900' },
  answerMainItem:{ fontSize: 14, lineHeight: 18, fontWeight: '900', marginBottom: 10 },
  answerMetrics:{ flexDirection: 'row', gap: 8 },
  answerMetric:{ flex: 1, borderWidth: 1, borderRadius: 12, padding: 9, minHeight: 58 },
  answerMetricLabel:{ fontSize: 9, textTransform: 'uppercase', letterSpacing: 0.5, marginBottom: 3 },
  answerMetricValue:{ fontSize: 13, lineHeight: 17, fontWeight: '900' },
  answerSource:{ flexDirection: 'row', alignItems: 'flex-start', gap: 7, borderTopWidth: 1, marginTop: 10, paddingTop: 9 },
  answerSourceText:{ flex: 1, fontSize: 11, lineHeight: 16 },
  answerRows:{ marginTop: 2 },
  answerRow:{ flexDirection: 'row', alignItems: 'flex-start', gap: 8, borderTopWidth: 1, paddingVertical: 8 },
  answerRowTap:{ paddingRight: 2 },
  answerRowItem:{ fontSize: 12, lineHeight: 16, fontWeight: '900' },
  answerRowMeta:{ fontSize: 10, lineHeight: 14, marginTop: 2 },
  answerRowPrice:{ fontSize: 12, lineHeight: 16, fontWeight: '900' },
  answerRowRight:{ alignItems: 'flex-end', gap: 4, minWidth: 74 },
  answerNote:{ fontSize: 11, lineHeight: 15, marginTop: 9 },
  answerAction:{ marginTop: 10, borderWidth: 1, borderRadius: 12, paddingVertical: 10, paddingHorizontal: 10, flexDirection: 'row', alignItems: 'center', justifyContent: 'center', gap: 6 },
  answerActionText:{ fontSize: 11, fontWeight: '900' },
  feedbackRow:  { flexDirection: 'row', alignItems: 'center', gap: 7, marginTop: 7, marginLeft: 2 },
  feedbackBtn:  { flexDirection: 'row', alignItems: 'center', gap: 4, borderWidth: 1, borderRadius: 99, paddingHorizontal: 9, paddingVertical: 5 },
  iconFeedbackBtn:{ width: 32, height: 30, borderWidth: 1, borderRadius: 99, alignItems: 'center', justifyContent: 'center' },
  feedbackTxt:  { fontSize: 10, fontWeight: '800' },
  feedbackSaved:{ fontSize: 10, fontWeight: '800', paddingVertical: 5 },
  toolsUsed:    { flexDirection: 'row', flexWrap: 'wrap', gap: 4, marginBottom: 5 },
  toolBadge:    { borderWidth: 1, borderRadius: 99, paddingHorizontal: 8, paddingVertical: 2 },
  inputBar:     { flexDirection: 'row', alignItems: 'flex-end', paddingTop: 12, paddingHorizontal: 18, paddingBottom: 92, borderTopWidth: 0, gap: 8, shadowColor: '#36283E', shadowOpacity: 0.08, shadowRadius: 18, shadowOffset: { width: 0, height: -8 }, elevation: 8 },
  input:        { flex: 1, borderWidth: 1, borderRadius: 20, borderBottomRightRadius:7, padding: 12, paddingHorizontal: 15, fontSize: 13, maxHeight: 100, shadowColor:'#36283E', shadowOpacity:0.09, shadowRadius:16, shadowOffset:{width:0,height:8}, elevation:2 },
  micBtn:       { width: 44, height: 44, borderRadius: 16, borderBottomRightRadius:7, borderWidth: 1, alignItems: 'center', justifyContent: 'center' },
  sendBtn:      { width: 44, height: 44, borderRadius: 16, borderBottomRightRadius:6, alignItems: 'center', justifyContent: 'center', shadowColor: '#6557FF', shadowOpacity: 0.26, shadowRadius: 12, shadowOffset: { width: 0, height: 7 }, elevation: 4 },
  sendIcon:     { color: '#fff', fontSize: 20, fontWeight: '700', lineHeight: 24 },
  voiceHint:    { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', borderTopWidth: 1, paddingHorizontal: 16, paddingVertical: 8, gap: 10 },
  voiceHintTxt: { flex: 1, fontSize: 12 },
  traceBox:     { maxWidth: '86%', borderWidth: 1, borderRadius: 12, marginTop: 6, overflow: 'hidden' },
  traceHeader:  { flexDirection: 'row', alignItems: 'center', gap: 5, paddingHorizontal: 10, paddingVertical: 8 },
  traceHeaderTxt: { flex: 1, fontSize: 10, fontWeight: '700' },
  tracePipeline:{ borderTopWidth: 1, paddingHorizontal: 10, paddingVertical: 7 },
  traceRow:     { flexDirection: 'row', alignItems: 'center', gap: 8, borderTopWidth: 1, paddingHorizontal: 10, paddingVertical: 7 },
  traceItem:    { fontSize: 11, fontWeight: '700' },
  traceMeta:    { fontSize: 10, marginTop: 1 },
  traceRight:   { alignItems: 'flex-end', gap: 4 },
  tracePrice:   { fontSize: 11, fontWeight: '700' },
  traceWrongBtn:{ borderWidth: 1, borderRadius: 99, padding: 6 },
});
