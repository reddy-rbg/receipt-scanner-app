import { useEffect, useRef, useState, useCallback } from 'react';
import { useTheme } from '../../stores/themeStore';
import { getUserToken, getGuestSessionId } from '../../stores/authStore';
import { useFocusEffect } from 'expo-router';
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
  if (lower.includes('column') || lower.includes('receipts.') || lower.includes('sql') || lower.includes('supabase')) {
    return 'I had trouble reading your receipt data. Please try again in a moment.';
  }
  return message;
}

function formatAgentText(text: string) {
  return text
    .replace(/\*\*(.+?)\*\*/g, '$1')
    .replace(/^### (.+)$/gm, '$1:')
    .replace(/^## (.+)$/gm, '$1')
    .replace(/^# (.+)$/gm, '$1')
    .split('\n')
    .filter(line => !/^\s*\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)+\|?\s*$/.test(line))
    .map(line => line.replace(/^\s*\|\s*/, '').replace(/\s*\|\s*$/, '').replace(/\s*\|\s*/g, '   '))
    .join('\n')
    .replace(/\n{3,}/g, '\n\n')
    .trim();
}

type Msg = {
  role: 'user' | 'agent';
  text: string;
  tools?: string[];
  loading?: boolean;
};

type VoiceMode = 'dictate' | 'wake' | null;

const QUICK_PROMPTS = [
  { label: ' Spending summary', prompt: 'Give me a complete summary of my spending' },
  { label: ' Best store', prompt: 'Which store gives me the best value for money?' },
  { label: ' Price trends', prompt: 'Show me price trends for items I buy regularly' },
  { label: ' Shopping plan', prompt: 'Help me plan my next grocery shopping trip to save money' },
  { label: ' Save money', prompt: 'What are the top 3 ways I can save money based on my receipts?' },
  { label: ' Monthly report', prompt: 'Give me a monthly spending report with store breakdown' },
  { label: ' Spending graph', prompt: 'Show my monthly expenses spent analysis as a chart' },
  { label: ' Buy this month', prompt: 'Give me this month items to purchase based on my receipts' },
  { label: ' Compare prices', prompt: 'Compare my prices to current market prices and find where I overpaid' },
  { label: 'Price memory', prompt: 'Show my price memory and avoid-above prices' },
  { label: 'Good price?', prompt: 'Is this a good price based on my receipt history?' },
  { label: ' Best deals', prompt: 'What were the best deals I got recently?' },
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
      text: 'Ask me anything about your receipts, spending, prices, or what to buy next.',
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
            text: ' Fresh start! Ask me anything about your receipts and spending.',
          }]);
        }
      }
    ]);
  }

  function renderMessage(msg: Msg, index: number) {
    const isUser = msg.role === 'user';

    if (msg.loading) {
      return (
        <View key={index} style={s.msgRow}>
          <View style={[s.agentAvatar, { backgroundColor: 'rgba(124,106,255,0.15)' }]}>
            <Text style={{ color: C.accent, fontSize: 12 }}></Text>
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

    const formattedText = formatAgentText(msg.text);
    const tableLike = msg.text.includes('|');

    return (
      <View key={index} style={s.msgRow}>
        <View style={[s.agentAvatar, { backgroundColor: 'rgba(124,106,255,0.15)' }]}>
          <Text style={{ color: C.accent, fontSize: 12 }}></Text>
        </View>
        <View style={{ flex: 1 }}>
          <View style={[s.bubble, s.agentBubble, { backgroundColor: C.surface2, borderColor: C.border }]}>
            <Text style={[s.bubbleTxt, tableLike && s.tableTxt, { color: C.text }]}>{formattedText}</Text>
          </View>
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
                <Text style={[s.agentIntroKicker, { color: C.accent3 }]}>AI Agent</Text>
                <Text style={[s.agentIntroTitle, { color: C.text }]}>Ask anything</Text>
                <Text style={[s.agentIntroText, { color: C.text2 }]}>
                  Prices, spending, stores, savings, and shopping plans.
                </Text>
              </View>
            </View>
            <Text style={[s.quickLabel, { color: C.text3 }]}>Ask anything</Text>
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
            : <Text style={s.sendIcon}></Text>
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
  agentIntroTitle:{ fontSize: 20, lineHeight: 24, fontWeight: '900', letterSpacing: 0, marginBottom: 5 },
  agentIntroText:{ fontSize: 13, lineHeight: 19 },
  quickLabel:   { fontSize: 10, letterSpacing: 0.5, textTransform: 'uppercase', marginBottom: 10 },
  quickGrid:    { flexDirection: 'row', flexWrap: 'wrap', gap: 7 },
  quickChip:    { borderWidth: 1, borderRadius: 99, paddingHorizontal: 12, paddingVertical: 6 },
  quickChipTxt: { fontSize: 12 },
  msgRow:       { flexDirection: 'row', alignItems: 'flex-start', marginBottom: 14, gap: 8 },
  userRow:      { justifyContent: 'flex-end' },
  agentAvatar:  { width: 28, height: 28, borderRadius: 8, alignItems: 'center', justifyContent: 'center', flexShrink: 0, marginTop: 2 },
  bubble:       { maxWidth: '85%', borderRadius: 16, padding: 12, paddingHorizontal: 14 },
  agentBubble:  { borderWidth: 1, borderBottomLeftRadius: 4 },
  userBubble:   { borderBottomRightRadius: 4 },
  bubbleTxt:    { fontSize: 14, lineHeight: 21 },
  tableTxt:     { fontSize: 12, lineHeight: 18, fontFamily: Platform.OS === 'ios' ? 'Menlo' : 'monospace' },
  toolsUsed:    { flexDirection: 'row', flexWrap: 'wrap', gap: 4, marginBottom: 5 },
  toolBadge:    { borderWidth: 1, borderRadius: 99, paddingHorizontal: 8, paddingVertical: 2 },
  inputBar:     { flexDirection: 'row', alignItems: 'flex-end', padding: 12, paddingHorizontal: 16, borderTopWidth: 1, gap: 8 },
  input:        { flex: 1, borderWidth: 1, borderRadius: 14, padding: 12, paddingHorizontal: 14, fontSize: 14, maxHeight: 100 },
  micBtn:       { width: 42, height: 42, borderRadius: 12, borderWidth: 1, alignItems: 'center', justifyContent: 'center' },
  sendBtn:      { width: 42, height: 42, borderRadius: 12, alignItems: 'center', justifyContent: 'center' },
  sendIcon:     { color: '#fff', fontSize: 20, fontWeight: '700', lineHeight: 24 },
  voiceHint:    { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', borderTopWidth: 1, paddingHorizontal: 16, paddingVertical: 8, gap: 10 },
  voiceHintTxt: { flex: 1, fontSize: 12 },
});
