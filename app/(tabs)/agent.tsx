import { useEffect, useRef, useState, useCallback } from 'react';
import { useTheme } from '../../stores/themeStore';
import { getUserToken, getGuestSessionId } from '../../stores/authStore';
import { router, useFocusEffect } from 'expo-router';
import { Ionicons } from '@expo/vector-icons';
import Constants from 'expo-constants';
import {
  View, Text, ScrollView, TouchableOpacity, TextInput,
  StyleSheet, ActivityIndicator, KeyboardAvoidingView,
  Platform, Alert, NativeModules,
} from 'react-native';

const API = 'https://web-production-3605f4.up.railway.app';
declare const require: any;
let VoiceModule: any = null;
let VoiceModuleChecked = false;

function getVoiceModule() {
  if (VoiceModuleChecked) return VoiceModule;
  VoiceModuleChecked = true;
  if (Constants.appOwnership === 'expo' || !NativeModules.Voice) {
    VoiceModule = null;
    return VoiceModule;
  }
  try {
    VoiceModule = require('@react-native-voice/voice').default;
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

type Msg = {
  role: 'user' | 'agent';
  text: string;
  tools?: string[];
  loading?: boolean;
  answerCard?: AgentAnswerCard | null;
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

const QUICK_PROMPTS = [
  { label: 'Spending summary', prompt: 'Give me a complete summary of my spending' },
  { label: 'Best store', prompt: 'Which store gives me the best value for money?' },
  { label: 'Price trends', prompt: 'Show me price trends for items I buy regularly' },
  { label: 'Shopping plan', prompt: 'Help me plan my next grocery shopping trip to save money' },
  { label: 'Save money', prompt: 'What are the top 3 ways I can save money based on my receipts?' },
  { label: 'Monthly report', prompt: 'Give me a monthly spending report with store breakdown' },
  { label: 'Spending graph', prompt: 'Show my monthly expenses spent analysis as a chart' },
  { label: 'Buy this month', prompt: 'Give me this month items to purchase based on my receipts' },
  { label: 'Compare prices', prompt: 'Compare my prices to current market prices and find where I overpaid' },
  { label: 'Price memory', prompt: 'Show my price memory and avoid-above prices' },
  { label: 'Good price?', prompt: 'Is this a good price based on my receipt history?' },
  { label: 'Best deals', prompt: 'What were the best deals I got recently?' },
];

const FEATURED_PROMPTS = [
  { icon: 'analytics-outline' as const, label: 'Analyze spending', prompt: 'Give me a smart spending snapshot with best next moves' },
  { icon: 'pricetag-outline' as const, label: 'Check prices', prompt: 'Show my price trends and biggest price swings' },
  { icon: 'cart-outline' as const, label: 'Plan trip', prompt: 'Build my next shopping plan from my receipt history' },
];

function cleanPromptLabel(label: string) {
  return label
    .replace(/^[^\w?]+/u, '')
    .replace(/[^\x20-\x7E]/g, '')
    .trim();
}

export default function AgentScreen() {
  const { colors: C } = useTheme();
  const [msgs, setMsgs]         = useState<Msg[]>([
    {
      role: 'agent',
      text: 'Ready. Ask about prices, spending, stores, or what to buy next.',
    }
  ]);
  const [input, setInput]       = useState('');
  const [loading, setLoading]   = useState(false);
  const [voiceMode, setVoiceMode] = useState<VoiceMode>(null);
  const [voiceText, setVoiceText] = useState('');
  const [sessionId]             = useState(`session_${Date.now()}`);
  const scrollRef               = useRef<ScrollView>(null);
  const voiceModeRef            = useRef<VoiceMode>(null);
  const wakeRestartRef          = useRef<any>(null);

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
    Alert.alert(
      'Voice build required',
      'Voice recognition needs a development or production build with the native voice module. It will not work inside Expo Go.'
    );
  }

  async function stopVoice() {
    const Voice = getVoiceModule();
    if (wakeRestartRef.current) clearTimeout(wakeRestartRef.current);
    wakeRestartRef.current = null;
    voiceModeRef.current = null;
    setVoiceMode(null);
    setVoiceText('');
    if (!Voice) return;
    try {
      await Voice.stop();
      await Voice.cancel();
    } catch {}
  }

  async function startVoice(mode: Exclude<VoiceMode, null>) {
    if (loading) return;
    try {
      const Voice = getVoiceModule();
      if (!Voice) {
        voiceUnavailable();
        return;
      }
      const available = await Voice.isAvailable();
      if (!available) {
        voiceUnavailable();
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
      await Voice.start('en-US');
    } catch (e: any) {
      setVoiceMode(null);
      voiceModeRef.current = null;
      if (String(e?.message || e).toLowerCase().includes('native')) voiceUnavailable();
      else Alert.alert('Voice error', 'Could not start voice recognition. Please try again.');
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
      await Voice.start('en-US');
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
    Voice.onSpeechPartialResults = (e: any) => handleSpeechText((e.value || [])[0] || '');
    Voice.onSpeechResults = (e: any) => handleSpeechText((e.value || [])[0] || '', true);
    Voice.onSpeechError = () => {
      if (voiceModeRef.current === 'wake') {
        wakeRestartRef.current = setTimeout(restartWakeListening, 700);
      } else {
        stopVoice();
      }
    };
    Voice.onSpeechEnd = () => {
      if (voiceModeRef.current === 'wake') {
        wakeRestartRef.current = setTimeout(restartWakeListening, 700);
      }
    };
    return () => {
      if (wakeRestartRef.current) clearTimeout(wakeRestartRef.current);
      Voice.destroy().then(() => Voice.removeAllListeners()).catch(() => {});
    };
  }, []);

  async function sendMessage(text: string) {
    const message = text.trim();
    if (!message || loading) return;

    setInput('');
    const userMsg: Msg = { role: 'user', text: message };
    const loadingMsg: Msg = { role: 'agent', text: '', loading: true };

    setMsgs(prev => [...prev, userMsg, loadingMsg]);
    setLoading(true);
    scrollToBottom();

    try {
      const token = getUserToken();
      const headers: any = { 'Content-Type': 'application/json' };
      if (token) headers['Authorization'] = `Bearer ${token}`;

      const res = await fetch(`${API}/agent/chat`, {
        method:  'POST',
        headers,
        body:    JSON.stringify({ message, session_id: sessionId, guest_session_id: getGuestSessionId() || undefined }),
      });

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
        tools: data.tools_used || [],
      };

      setMsgs(prev => [...prev.slice(0, -1), agentMsg]);

    } catch (e: any) {
      const errMsg: Msg = {
        role: 'agent',
        text: friendlyAgentError(e.message || 'Could not connect'),
      };
      setMsgs(prev => [...prev.slice(0, -1), errMsg]);
    } finally {
      setLoading(false);
      scrollToBottom();
    }
  }

  async function clearConversation() {
    Alert.alert('Clear Conversation', 'Start a fresh conversation with the agent?', [
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

        {card.type === 'category_list' && rows.length ? (
          <View style={s.answerRows}>
            {rows.map((row, idx) => (
              <View key={`${row.item}-${idx}`} style={[s.answerRow, { borderTopColor: C.border }]}>
                <View style={{ flex: 1 }}>
                  <Text style={[s.answerRowItem, { color: C.text }]} numberOfLines={1}>{row.item || 'Item'}</Text>
                  <Text style={[s.answerRowMeta, { color: C.text2 }]} numberOfLines={2}>
                    {[row.store, row.date, row.detail].filter(Boolean).join('  |  ')}
                  </Text>
                </View>
                <Text style={[s.answerRowPrice, { color: C.accent3 }]}>{row.price || ''}</Text>
              </View>
            ))}
          </View>
        ) : (
          <>
            <Text style={[s.answerMainItem, { color: C.text }]} numberOfLines={2}>{card.item || 'Matched item'}</Text>
            <View style={s.answerMetrics}>
              <View style={[s.answerMetric, { backgroundColor: C.surface2, borderColor: C.border }]}>
                <Text style={[s.answerMetricLabel, { color: C.text3 }]}>Price</Text>
                <Text style={[s.answerMetricValue, { color: C.accent3 }]} numberOfLines={1}>{card.price || 'N/A'}</Text>
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
          <View style={[s.bubble, s.userBubble, { backgroundColor: C.accent }]}>
            <Text style={[s.bubbleTxt, { color: '#fff' }]}>{msg.text}</Text>
          </View>
        </View>
      );
    }

    const formattedText = msg.answerCard ? formatAgentText(msg.text).split('\n')[0] : formatAgentText(msg.text);
    const tableLike = msg.text.includes('|');

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
      <View style={[s.agentHeader, { backgroundColor: C.surface, borderBottomColor: C.border }]}>
        <View style={s.agentHeaderLeft}>
          <View style={[s.agentDot, { backgroundColor: C.green }]} />
          <Text style={[s.agentHeaderTxt, { color: C.text2 }]}>
            {voiceMode === 'wake' ? 'Listening for Hey ReceiptAI' : voiceMode === 'dictate' ? 'Voice listening' : 'Ready'}
          </Text>
        </View>
        <View style={s.headerActions}>
          <TouchableOpacity
            style={[
              s.wakeBtn,
              { borderColor: C.border, backgroundColor: voiceMode === 'wake' ? 'rgba(74,222,128,0.12)' : C.surface2 },
            ]}
            onPress={() => voiceMode === 'wake' ? stopVoice() : startVoice('wake')}
            activeOpacity={0.8}
          >
            <Ionicons name={voiceMode === 'wake' ? 'ear' : 'ear-outline'} size={14} color={voiceMode === 'wake' ? C.green : C.accent} />
            <Text style={[s.wakeTxt, { color: voiceMode === 'wake' ? C.green : C.accent }]}>
              Hey ReceiptAI
            </Text>
          </TouchableOpacity>
          <TouchableOpacity onPress={clearConversation}>
            <Text style={{ color: C.accent, fontSize: 12 }}>Clear</Text>
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
              <View style={[s.agentIntroIcon, { backgroundColor: 'rgba(124,106,255,0.16)', borderColor: 'rgba(124,106,255,0.34)' }]}>
                <Ionicons name="sparkles" size={18} color={C.accent} />
              </View>
              <View style={{ flex: 1 }}>
                <Text style={[s.agentIntroKicker, { color: C.accent3 }]}>ReceiptAI Agent</Text>
                <Text style={[s.agentIntroTitle, { color: C.text }]}>Shopping intelligence</Text>
                <Text style={[s.agentIntroText, { color: C.text2 }]}>
                  Ask for price checks, spending analysis, store comparisons, and next-purchase plans.
                </Text>
              </View>
            </View>
            <View style={s.featuredGrid}>
              {FEATURED_PROMPTS.map((q) => (
                <TouchableOpacity
                  key={q.label}
                  style={[s.featuredCard, { backgroundColor: C.surface, borderColor: C.border }]}
                  onPress={() => sendMessage(q.prompt)}
                  activeOpacity={0.82}
                >
                  <Ionicons name={q.icon} size={18} color={C.accent} />
                  <Text style={[s.featuredLabel, { color: C.text }]}>{q.label}</Text>
                </TouchableOpacity>
              ))}
            </View>
            <Text style={[s.quickLabel, { color: C.text3 }]}>Quick questions</Text>
            <View style={s.quickGrid}>
              {QUICK_PROMPTS.map((q, i) => (
                <TouchableOpacity
                  key={i}
                  style={[s.quickChip, { backgroundColor: C.surface2, borderColor: C.border }]}
                  onPress={() => sendMessage(q.prompt)}
                  activeOpacity={0.7}
                >
                  <Text style={[s.quickChipTxt, { color: C.text2 }]}>{cleanPromptLabel(q.label)}</Text>
                </TouchableOpacity>
              ))}
            </View>
          </View>
        )}

        {/* Messages */}
        {msgs.map((msg, i) => renderMessage(msg, i))}
      </ScrollView>

      {/* Input */}
      <View style={[s.inputBar, { backgroundColor: C.surface, borderTopColor: C.border }]}>
        <TextInput
          style={[s.input, { backgroundColor: C.surface2, borderColor: C.border, color: C.text }]}
          placeholder="Ask anything about your receipts..."
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
  agentHeader:  { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', paddingHorizontal: 16, paddingVertical: 8, borderBottomWidth: 1 },
  agentHeaderLeft: { flexDirection: 'row', alignItems: 'center', gap: 6 },
  headerActions:{ flexDirection: 'row', alignItems: 'center', gap: 10 },
  agentDot:     { width: 6, height: 6, borderRadius: 3 },
  agentHeaderTxt: { fontSize: 11 },
  wakeBtn:      { flexDirection: 'row', alignItems: 'center', gap: 5, borderWidth: 1, borderRadius: 99, paddingHorizontal: 9, paddingVertical: 5 },
  wakeTxt:      { fontSize: 10, fontWeight: '800' },
  chat:         { flex: 1 },
  chatContent:  { padding: 16, paddingBottom: 8 },
  quickSection: { marginBottom: 20 },
  agentIntro:   { flexDirection: 'row', alignItems: 'flex-start', gap: 12, borderWidth: 1, borderRadius: 20, padding: 16, marginBottom: 16 },
  agentIntroIcon:{ width: 42, height: 42, borderRadius: 14, borderWidth: 1, alignItems: 'center', justifyContent: 'center' },
  agentIntroKicker:{ fontSize: 10, fontWeight: '900', textTransform: 'uppercase', letterSpacing: 0.7, marginBottom: 4 },
  agentIntroTitle:{ fontSize: 22, lineHeight: 26, fontWeight: '900', letterSpacing: 0, marginBottom: 5 },
  agentIntroText:{ fontSize: 13, lineHeight: 19 },
  featuredGrid:  { flexDirection: 'row', gap: 8, marginBottom: 16 },
  featuredCard:  { flex: 1, minHeight: 78, borderWidth: 1, borderRadius: 16, padding: 11, justifyContent: 'space-between' },
  featuredLabel: { fontSize: 12, lineHeight: 16, fontWeight: '800' },
  quickLabel:   { fontSize: 10, letterSpacing: 0.5, textTransform: 'uppercase', marginBottom: 10 },
  quickGrid:    { flexDirection: 'row', flexWrap: 'wrap', gap: 7 },
  quickChip:    { borderWidth: 1, borderRadius: 99, paddingHorizontal: 13, paddingVertical: 7 },
  quickChipTxt: { fontSize: 12, fontWeight: '700' },
  msgRow:       { flexDirection: 'row', alignItems: 'flex-start', marginBottom: 14, gap: 8 },
  userRow:      { justifyContent: 'flex-end' },
  agentAvatar:  { width: 30, height: 30, borderRadius: 10, alignItems: 'center', justifyContent: 'center', flexShrink: 0, marginTop: 2 },
  bubble:       { maxWidth: '86%', borderRadius: 18, padding: 13, paddingHorizontal: 15 },
  agentBubble:  { borderWidth: 1, borderBottomLeftRadius: 4 },
  userBubble:   { borderBottomRightRadius: 4 },
  bubbleTxt:    { fontSize: 14, lineHeight: 21 },
  tableTxt:     { fontSize: 12, lineHeight: 18, fontFamily: Platform.OS === 'ios' ? 'Menlo' : 'monospace' },
  answerLeadBubble:{ paddingVertical: 10, borderRadius: 12 },
  answerLeadTxt:{ fontSize: 13, lineHeight: 18, fontWeight: '800' },
  answerCard:   { maxWidth: '86%', borderWidth: 1, borderRadius: 12, padding: 13, marginTop: 8 },
  answerCardHead:{ flexDirection: 'row', alignItems: 'center', gap: 9, marginBottom: 10 },
  answerCardIcon:{ width: 30, height: 30, borderRadius: 9, borderWidth: 1, alignItems: 'center', justifyContent: 'center' },
  answerCardKicker:{ fontSize: 9, fontWeight: '900', textTransform: 'uppercase', letterSpacing: 0.7 },
  answerCardTitle:{ fontSize: 15, lineHeight: 19, fontWeight: '900' },
  answerMainItem:{ fontSize: 14, lineHeight: 18, fontWeight: '900', marginBottom: 10 },
  answerMetrics:{ flexDirection: 'row', gap: 8 },
  answerMetric:{ flex: 1, borderWidth: 1, borderRadius: 8, padding: 9, minHeight: 58 },
  answerMetricLabel:{ fontSize: 9, textTransform: 'uppercase', letterSpacing: 0.5, marginBottom: 3 },
  answerMetricValue:{ fontSize: 13, lineHeight: 17, fontWeight: '900' },
  answerSource:{ flexDirection: 'row', alignItems: 'flex-start', gap: 7, borderTopWidth: 1, marginTop: 10, paddingTop: 9 },
  answerSourceText:{ flex: 1, fontSize: 11, lineHeight: 16 },
  answerRows:{ marginTop: 2 },
  answerRow:{ flexDirection: 'row', alignItems: 'flex-start', gap: 8, borderTopWidth: 1, paddingVertical: 8 },
  answerRowItem:{ fontSize: 12, lineHeight: 16, fontWeight: '900' },
  answerRowMeta:{ fontSize: 10, lineHeight: 14, marginTop: 2 },
  answerRowPrice:{ fontSize: 12, lineHeight: 16, fontWeight: '900' },
  answerNote:{ fontSize: 11, lineHeight: 15, marginTop: 9 },
  answerAction:{ marginTop: 10, borderWidth: 1, borderRadius: 8, paddingVertical: 9, paddingHorizontal: 10, flexDirection: 'row', alignItems: 'center', justifyContent: 'center', gap: 6 },
  answerActionText:{ fontSize: 11, fontWeight: '900' },
  toolsUsed:    { flexDirection: 'row', flexWrap: 'wrap', gap: 4, marginBottom: 5 },
  toolBadge:    { borderWidth: 1, borderRadius: 99, paddingHorizontal: 8, paddingVertical: 2 },
  inputBar:     { flexDirection: 'row', alignItems: 'flex-end', padding: 12, paddingHorizontal: 16, borderTopWidth: 1, gap: 8 },
  input:        { flex: 1, borderWidth: 1, borderRadius: 16, padding: 12, paddingHorizontal: 14, fontSize: 14, maxHeight: 100 },
  micBtn:       { width: 44, height: 44, borderRadius: 14, borderWidth: 1, alignItems: 'center', justifyContent: 'center' },
  sendBtn:      { width: 44, height: 44, borderRadius: 14, alignItems: 'center', justifyContent: 'center' },
  sendIcon:     { color: '#fff', fontSize: 20, fontWeight: '700', lineHeight: 24 },
  voiceHint:    { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', borderTopWidth: 1, paddingHorizontal: 16, paddingVertical: 8, gap: 10 },
  voiceHintTxt: { flex: 1, fontSize: 12 },
});
