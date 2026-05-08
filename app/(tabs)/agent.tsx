import { useState, useRef, useCallback } from 'react';
import { useTheme } from '../themeStore';
import { getUser, getUserToken } from '../authStore';
import { useFocusEffect } from 'expo-router';
import {
  View, Text, ScrollView, TouchableOpacity, TextInput,
  StyleSheet, ActivityIndicator, KeyboardAvoidingView,
  Platform, Alert,
} from 'react-native';

const API = 'https://web-production-3605f4.up.railway.app';

type Msg = {
  role: 'user' | 'agent';
  text: string;
  tools?: string[];
  loading?: boolean;
};

const QUICK_PROMPTS = [
  { label: '💰 Spending summary', prompt: 'Give me a complete summary of my spending' },
  { label: '🏪 Best store', prompt: 'Which store gives me the best value for money?' },
  { label: '📈 Price trends', prompt: 'Show me price trends for items I buy regularly' },
  { label: '🛒 Shopping plan', prompt: 'Help me plan my next grocery shopping trip to save money' },
  { label: '💡 Save money', prompt: 'What are the top 3 ways I can save money based on my receipts?' },
  { label: '📊 Monthly report', prompt: 'Give me a monthly spending report with store breakdown' },
  { label: '🔍 Compare prices', prompt: 'Compare my prices to current market prices and find where I overpaid' },
  { label: '🎯 Best deals', prompt: 'What were the best deals I got recently?' },
];

const TOOL_LABELS: Record<string, string> = {
  query_receipts:       '🗄 Querying receipts',
  get_price_history:    '📈 Checking price history',
  analyze_spending:     '📊 Analyzing spending',
  find_best_deals:      '🛒 Finding best deals',
  search_market_prices: '🌐 Searching market prices',
};

export default function AgentScreen() {
  const { colors: C } = useTheme();
  const [msgs, setMsgs]         = useState<Msg[]>([
    {
      role: 'agent',
      text: '👋 Hi! I\'m your ReceiptAI Agent.\n\nI can analyze your purchase history, find the best prices, optimize your shopping list, and answer any question about your spending.\n\nWhat would you like to know?',
    }
  ]);
  const [input, setInput]       = useState('');
  const [loading, setLoading]   = useState(false);
  const [sessionId]             = useState(`session_${Date.now()}`);
  const scrollRef               = useRef<ScrollView>(null);

  useFocusEffect(useCallback(() => {}, []));

  function scrollToBottom() {
    setTimeout(() => scrollRef.current?.scrollToEnd({ animated: true }), 100);
  }

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

      const res = await fetch(`${API}/agent`, {
        method:  'POST',
        headers,
        body:    JSON.stringify({ message, session_id: sessionId }),
      });

      const data = await res.json();

      if (!res.ok) {
        throw new Error(data.detail || 'Agent error');
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
        text: `Sorry, I ran into an error: ${e.message || 'Could not connect'}. Please try again.`,
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
              body: JSON.stringify({ session_id: sessionId }),
            });
          } catch {}
          setMsgs([{
            role: 'agent',
            text: '✨ Fresh start! Ask me anything about your receipts and spending.',
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
            <Text style={{ color: C.accent, fontSize: 12 }}>✦</Text>
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

    // Format agent response - convert markdown to readable text
    const formattedText = msg.text
      .replace(/\*\*(.+?)\*\*/g, '$1')
      .replace(/^### (.+)$/gm, '$1:')
      .replace(/^## (.+)$/gm, '$1')
      .replace(/^# (.+)$/gm, '$1');

    return (
      <View key={index} style={s.msgRow}>
        <View style={[s.agentAvatar, { backgroundColor: 'rgba(124,106,255,0.15)' }]}>
          <Text style={{ color: C.accent, fontSize: 12 }}>✦</Text>
        </View>
        <View style={{ flex: 1 }}>
          {msg.tools && msg.tools.length > 0 && (
            <View style={s.toolsUsed}>
              {msg.tools.map((tool, i) => (
                <View key={i} style={[s.toolBadge, { backgroundColor: 'rgba(124,106,255,0.08)', borderColor: 'rgba(124,106,255,0.2)' }]}>
                  <Text style={{ color: C.accent, fontSize: 10 }}>
                    {TOOL_LABELS[tool] || tool}
                  </Text>
                </View>
              ))}
            </View>
          )}
          <View style={[s.bubble, s.agentBubble, { backgroundColor: C.surface2, borderColor: C.border }]}>
            <Text style={[s.bubbleTxt, { color: C.text }]}>{formattedText}</Text>
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
            AI Agent · Claude Opus · 5 tools available
          </Text>
        </View>
        <TouchableOpacity onPress={clearConversation}>
          <Text style={{ color: C.accent, fontSize: 12 }}>Clear</Text>
        </TouchableOpacity>
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
            <Text style={[s.quickLabel, { color: C.text3 }]}>Try asking</Text>
            <View style={s.quickGrid}>
              {QUICK_PROMPTS.map((q, i) => (
                <TouchableOpacity
                  key={i}
                  style={[s.quickChip, { backgroundColor: C.surface2, borderColor: C.border }]}
                  onPress={() => sendMessage(q.prompt)}
                  activeOpacity={0.7}
                >
                  <Text style={[s.quickChipTxt, { color: C.text2 }]}>{q.label}</Text>
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
          style={[s.sendBtn, { backgroundColor: C.accent }, (!input.trim() || loading) && { opacity: 0.35 }]}
          onPress={() => sendMessage(input)}
          disabled={!input.trim() || loading}
          activeOpacity={0.85}
        >
          {loading
            ? <ActivityIndicator size="small" color="#fff" />
            : <Text style={s.sendIcon}>↑</Text>
          }
        </TouchableOpacity>
      </View>
    </KeyboardAvoidingView>
  );
}

const s = StyleSheet.create({
  screen:       { flex: 1 },
  agentHeader:  { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', paddingHorizontal: 16, paddingVertical: 8, borderBottomWidth: 1 },
  agentHeaderLeft: { flexDirection: 'row', alignItems: 'center', gap: 6 },
  agentDot:     { width: 6, height: 6, borderRadius: 3 },
  agentHeaderTxt: { fontSize: 11 },
  chat:         { flex: 1 },
  chatContent:  { padding: 16, paddingBottom: 8 },
  quickSection: { marginBottom: 20 },
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
  toolsUsed:    { flexDirection: 'row', flexWrap: 'wrap', gap: 4, marginBottom: 5 },
  toolBadge:    { borderWidth: 1, borderRadius: 99, paddingHorizontal: 8, paddingVertical: 2 },
  inputBar:     { flexDirection: 'row', alignItems: 'flex-end', padding: 12, paddingHorizontal: 16, borderTopWidth: 1, gap: 10 },
  input:        { flex: 1, borderWidth: 1, borderRadius: 14, padding: 12, paddingHorizontal: 14, fontSize: 14, maxHeight: 100 },
  sendBtn:      { width: 42, height: 42, borderRadius: 12, alignItems: 'center', justifyContent: 'center' },
  sendIcon:     { color: '#fff', fontSize: 20, fontWeight: '700', lineHeight: 24 },
});
