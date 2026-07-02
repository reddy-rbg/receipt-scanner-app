//
// app/LoginScreen.tsx
// Full screen login shown before tabs unlock
//

import { useState } from 'react';
import {
  View, Text, ScrollView, TouchableOpacity, StyleSheet,
  TextInput, ActivityIndicator, Alert,
} from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import { saveUser, startGuestSession } from '../stores/authStore';
import { DARK_COLORS, useTheme } from '../stores/themeStore';
import { API } from '../config/api';

function validatePassword(password: string): string[] {
  const errors: string[] = [];
  if (password.length < 8)                  errors.push('At least 8 characters');
  if (!/[A-Z]/.test(password))             errors.push('At least 1 uppercase letter');
  if (!/[a-z]/.test(password))             errors.push('At least 1 lowercase letter');
  if (!/[.,?!@#$%&*_\-+]/.test(password)) errors.push('At least 1 special character');
  return errors;
}

function PasswordStrengthBar({ password, colors: C }: { password: string; colors: typeof DARK_COLORS }) {
  if (!password) return null;
  const errors = validatePassword(password);
  const strength = 4 - errors.length;
  const colors = ['#ff6b6b','#ff6b6b','#fbbf24','#4ade80','#4ade80'];
  return (
    <View style={{ marginTop:8, marginBottom:4 }}>
      <View style={{ flexDirection:'row', gap:4, marginBottom:4 }}>
        {[0,1,2,3].map(i => (
          <View key={i} style={{ flex:1, height:3, borderRadius:2, backgroundColor: i < strength ? colors[strength] : C.surface3 }} />
        ))}
      </View>
      {strength < 4
        ? <Text style={{ fontSize:11, color:C.text3 }}>Missing: {errors.join('  ')}</Text>
        : <Text style={{ fontSize:11, color:C.green }}> Strong password</Text>
      }
    </View>
  );
}

function friendlyAuthError(message: string) {
  const text = String(message || '').trim();
  const lower = text.toLowerCase();
  if (!text) return 'Something went wrong. Please try again.';
  if (lower.includes('application not found')) {
    return 'ReceiptAI server is not reachable. Please check the backend deployment.';
  }
  if (lower.includes('invalid login') || lower.includes('invalid credentials') || lower.includes('authentication failed')) {
    return 'Email or password is incorrect.';
  }
  if (lower.includes('email not confirmed')) {
    return 'Please confirm your email before signing in.';
  }
  if (lower.includes('rate') || lower.includes('too many')) {
    return 'Too many attempts. Please wait a few minutes and try again.';
  }
  return text;
}

function friendlyRecoveryError(message: string) {
  const text = String(message || '').trim();
  const lower = text.toLowerCase();
  if (lower.includes('application not found')) {
    return 'Password reset is not available right now. Please try again later.';
  }
  if (lower.includes('rate') || lower.includes('too many')) {
    return 'Too many reset attempts. Please wait a few minutes and try again.';
  }
  if (!text) return 'Could not send reset email. Please try again.';
  return text;
}

export default function LoginScreen() {
  const { colors: C } = useTheme();
  const s = createStyles(C);
  const [mode, setMode]         = useState<'login'|'signup'>('login');
  const [email, setEmail]       = useState('');
  const [password, setPassword] = useState('');
  const [name, setName]         = useState('');
  const [showPw, setShowPw]     = useState(false);
  const [loading, setLoading]   = useState(false);
  const [recoveryLoading, setRecoveryLoading] = useState(false);
  const [error, setError]       = useState('');

  async function handleAuth() {
    setError('');
    if (!email.trim())  { setError('Please enter your email.'); return; }
    if (!password)      { setError('Please enter your password.'); return; }
    if (mode === 'signup') {
      if (!name.trim()) { setError('Please enter your name.'); return; }
      const errs = validatePassword(password);
      if (errs.length > 0) { setError('Password requirements not met.'); return; }
    }

    setLoading(true);
    try {
      const endpoint = mode === 'login' ? '/auth/login' : '/auth/signup';
      const body: any = { email: email.trim().toLowerCase(), password };
      if (mode === 'signup') body.name = name.trim();

      const res  = await fetch(`${API}${endpoint}`, {
        method:'POST', headers:{'Content-Type':'application/json'},
        body: JSON.stringify(body),
      });
      const raw = await res.text();
      let data: any = {};
      try {
        data = raw ? JSON.parse(raw) : {};
      } catch {
        data = { detail: raw };
      }

      if (res.status === 404) {
        setError('ReceiptAI server is not reachable. Please check the backend deployment.');
        return;
      }

      if (!res.ok) {
        const detail = Array.isArray(data.detail)
          ? data.detail.map((d: any) => d?.msg || String(d)).join('\n')
          : data.detail || data.message || raw;
        setError(friendlyAuthError(detail || 'Authentication failed.'));
        return;
      }

      const accessToken =
        data.session?.access_token ||
        data.access_token ||
        data.token ||
        '';

      if (!accessToken) {
        setError('Account created, but session token was not returned. Please sign in once.');
        setMode('login');
        return;
      }

      await saveUser({
        id:         data.user.id,
        email:      data.user.email,
        name:       data.user.name,
        created_at: data.user.created_at,
        token:      accessToken,
        refresh_token: data.session?.refresh_token || '',
        isGuest:    false,
        is_guest:   false,
      });

    } catch { setError('Could not connect. Please try again.'); }
    finally  { setLoading(false); }
  }

  async function handleGuest() {
    setError('');
    try {
      await startGuestSession();
    } catch {
      setError('Could not start guest session. Please try again.');
    }
  }

  async function handleForgotPassword() {
    setError('');
    const targetEmail = email.trim().toLowerCase();
    if (!targetEmail) {
      setError('Enter your email address first, then tap Forgot password.');
      return;
    }

    setRecoveryLoading(true);
    try {
      const res = await fetch(`${API}/auth/forgot-password`, {
        method:'POST',
        headers:{'Content-Type':'application/json'},
        body: JSON.stringify({ email: targetEmail }),
      });
      const raw = await res.text();
      let data: any = {};
      try { data = raw ? JSON.parse(raw) : {}; } catch { data = { detail: raw }; }
      if (!res.ok) {
        setError(friendlyRecoveryError(data.detail || data.message || 'Could not send reset email.'));
        return;
      }
      Alert.alert(
        'Check your email',
        data.message || 'If an account exists for this email, a password reset link has been sent.'
      );
    } catch {
      setError('Could not send reset email. Please try again.');
    } finally {
      setRecoveryLoading(false);
    }
  }

  function handleForgotUsername() {
    Alert.alert(
      'Forgot email?',
      'ReceiptAI uses your email address as your username. Try the email you used when creating your account. If you used Guest Trial, no permanent account was created.'
    );
  }

  return (
    <ScrollView style={s.scroll} contentContainerStyle={s.container} keyboardShouldPersistTaps="handled">

      {/* Logo */}
      <View style={s.logoWrap}>
        <View style={s.logo}>
          <Ionicons name="receipt-outline" size={34} color={C.accent} />
        </View>
        <Text style={s.appName}>ReceiptAI</Text>
        <Text style={s.appTagline}>Receipt scanner and AI shopping memory.</Text>
      </View>

      {/* Security badge */}
      <View style={s.securityBadge}>
        <Text style={s.securityBadgeText}>Private by default. Your receipts stay yours.</Text>
      </View>

      <View style={s.authPanel}>
      {/* Tab switcher */}
      <View style={s.tabRow}>
        <TouchableOpacity
          style={[s.tab, mode==='login' && s.tabActive]}
          onPress={()=>{ setMode('login'); setError(''); setPassword(''); }}
        >
          <Text style={[s.tabTxt, mode==='login' && s.tabTxtActive]}>Sign In</Text>
        </TouchableOpacity>
        <TouchableOpacity
          style={[s.tab, mode==='signup' && s.tabActive]}
          onPress={()=>{ setMode('signup'); setError(''); setPassword(''); }}
        >
          <Text style={[s.tabTxt, mode==='signup' && s.tabTxtActive]}>Create Account</Text>
        </TouchableOpacity>
      </View>

      {/* Form */}
      <View style={s.form}>
        {mode==='signup' && (
          <View style={s.inputWrap}>
            <Text style={s.inputLabel}>Full Name</Text>
            <TextInput
              style={s.input} placeholder="John Smith"
              placeholderTextColor={C.text3} value={name}
              onChangeText={setName} autoCapitalize="words"
            />
          </View>
        )}

        <View style={s.inputWrap}>
          <Text style={s.inputLabel}>Email Address</Text>
          <TextInput
            style={s.input} placeholder="you@example.com"
            placeholderTextColor={C.text3} value={email}
            onChangeText={setEmail} keyboardType="email-address"
            autoCapitalize="none" autoCorrect={false}
          />
        </View>

        <View style={s.inputWrap}>
          <Text style={s.inputLabel}>Password</Text>
          <View style={{ position:'relative' }}>
            <TextInput
              style={[s.input,{ paddingRight:50 }]}
              placeholder={mode==='signup'?'Min 8 chars, 1 capital, 1 special':'Enter your password'}
              placeholderTextColor={C.text3} value={password}
              onChangeText={setPassword} secureTextEntry={!showPw}
            />
            <TouchableOpacity style={s.eyeBtn} onPress={()=>setShowPw(!showPw)}>
              <Text style={s.eyeText}>{showPw ? 'Hide' : 'Show'}</Text>
            </TouchableOpacity>
          </View>
          {mode==='signup' && <PasswordStrengthBar password={password} colors={C}/>}
        </View>

        {mode==='login' && (
          <View style={s.recoveryRow}>
            <TouchableOpacity onPress={handleForgotPassword} disabled={recoveryLoading}>
              <Text style={s.recoveryLink}>{recoveryLoading ? 'Sending reset...' : 'Forgot password?'}</Text>
            </TouchableOpacity>
            <TouchableOpacity onPress={handleForgotUsername}>
              <Text style={s.recoveryLink}>Forgot email?</Text>
            </TouchableOpacity>
          </View>
        )}

        {mode==='signup' && (
          <View style={s.passwordRules}>
            <Text style={s.passwordRulesTitle}>Password must have:</Text>
            {[
              { rule:'At least 8 characters',          ok: password.length >= 8 },
              { rule:'1 uppercase letter (A-Z)',        ok: /[A-Z]/.test(password) },
              { rule:'1 lowercase letter (a-z)',        ok: /[a-z]/.test(password) },
              { rule:'1 special character (.,?!@#$%)', ok: /[.,?!@#$%&*_\-+]/.test(password) },
            ].map((item,i) => (
              <View key={i} style={{ flexDirection:'row', alignItems:'center', marginBottom:4 }}>
                <Text style={{ color: item.ok ? C.green : C.text3, fontSize:13, width:20 }}>{item.ok?'':''}</Text>
                <Text style={{ color: item.ok ? C.green : C.text3, fontSize:12 }}>{item.rule}</Text>
              </View>
            ))}
          </View>
        )}

        {error!=='' && (
          <View style={s.errorBox}>
            <Text style={s.errorTxt}>{error}</Text>
          </View>
        )}

        <TouchableOpacity
          style={[s.authBtn, loading&&{opacity:0.5}]}
          onPress={handleAuth} disabled={loading} activeOpacity={0.85}
        >
          {loading
            ? <ActivityIndicator color="#fff" size="small"/>
            : <Text style={s.authBtnTxt}>{mode==='login'?'Sign In':'Create Account'}</Text>
          }
        </TouchableOpacity>
      </View>
      </View>

      {/* Privacy note */}
      <View style={s.privacyNote}>
        <Text style={s.privacyNoteTxt}>Your receipts are private and only visible to you.</Text>
      </View>

      {/* Divider */}
      <View style={s.divider}>
        <View style={s.dividerLine}/>
        <Text style={s.dividerTxt}>or</Text>
        <View style={s.dividerLine}/>
      </View>

      {/* Guest trial */}
      <View style={s.guestSection}>
        <Text style={s.guestTitle}>Want to try first?</Text>
        <TouchableOpacity style={s.guestBtn} onPress={handleGuest} activeOpacity={0.85}>
          <Text style={s.guestBtnTxt}>Start 24-Hour Free Trial</Text>
        </TouchableOpacity>
        <Text style={s.guestWarning}>
          Trial data is automatically deleted after 24 hours.{'\n'}
          Sign up to keep your receipts permanently.
        </Text>
      </View>

    </ScrollView>
  );
}

const createStyles = (C: typeof DARK_COLORS) => StyleSheet.create({
  scroll:{ flex:1, backgroundColor:C.bg },
  container:{ padding:22, paddingBottom:50, alignItems:'center', minHeight:'100%', justifyContent:'center' },

  logoWrap:{ alignItems:'center', marginBottom:18, marginTop:14 },
  logo:{ width:88, height:88, borderRadius:26, backgroundColor:'rgba(124,109,255,0.14)', borderWidth:1, borderColor:'rgba(124,109,255,0.48)', alignItems:'center', justifyContent:'center', marginBottom:16, shadowColor:C.accent, shadowOpacity:0.28, shadowRadius:22, shadowOffset:{width:0,height:12}, elevation:5 },
  appName:{ fontSize:34, fontWeight:'900', color:C.text, letterSpacing:0, marginBottom:5 },
  appTagline:{ fontSize:14, color:C.text2, textAlign:'center', lineHeight:20 },
  promiseRow:{ display:'none' },
  promisePill:{ backgroundColor:C.surface2, borderWidth:1, borderColor:C.border, borderRadius:99, paddingHorizontal:12, paddingVertical:6 },
  promiseTxt:{ color:C.accent, fontSize:11, fontWeight:'900' },
  previewCard:{ display:'none' },
  previewTop:{ flexDirection:'row', alignItems:'flex-start', gap:12, marginBottom:12 },
  previewKicker:{ color:C.accent, fontSize:10, fontWeight:'900', textTransform:'uppercase', letterSpacing:0.6, marginBottom:5 },
  previewTitle:{ color:C.text, fontSize:18, fontWeight:'900', lineHeight:23 },
  previewBadge:{ width:38, height:38, borderRadius:12, backgroundColor:'rgba(106,255,212,0.10)', borderWidth:1, borderColor:'rgba(106,255,212,0.24)', alignItems:'center', justifyContent:'center' },
  previewBadgeTxt:{ color:C.accent3, fontSize:12, fontWeight:'900' },
  previewRow:{ flexDirection:'row', alignItems:'center', gap:10, paddingTop:10, borderTopWidth:1, borderTopColor:C.border },
  previewStep:{ color:C.text, width:42, fontSize:12, fontWeight:'900' },
  previewText:{ color:C.text2, flex:1, fontSize:12, lineHeight:17 },

  securityBadge:{ backgroundColor:'rgba(74,222,128,0.1)', borderWidth:1, borderColor:'rgba(74,222,128,0.25)', borderRadius:99, paddingHorizontal:16, paddingVertical:8, marginBottom:14 },
  securityBadgeText:{ color:C.green, fontSize:12, fontWeight:'700', textAlign:'center' },
  authPanel:{ width:'100%', backgroundColor:C.card, borderWidth:1, borderColor:C.border, borderRadius:18, padding:16, marginBottom:16, shadowColor:'#000', shadowOpacity:0.22, shadowRadius:18, shadowOffset:{width:0,height:12}, elevation:5 },

  tabRow:{ flexDirection:'row', backgroundColor:C.surface2, borderRadius:14, padding:4, marginBottom:16, width:'100%', borderWidth:1, borderColor:C.border },
  tab:{ flex:1, padding:10, borderRadius:11, alignItems:'center' },
  tabActive:{ backgroundColor:C.accent },
  tabTxt:{ color:C.text2, fontSize:14, fontWeight:'600' },
  tabTxtActive:{ color:'#fff' },

  form:{ width:'100%' },
  inputWrap:{ marginBottom:14 },
  inputLabel:{ color:C.text2, fontSize:12, marginBottom:6, fontWeight:'500' },
  input:{ backgroundColor:C.surface2, borderWidth:1, borderColor:C.border, borderRadius:14, padding:14, paddingHorizontal:16, color:C.text, fontSize:14, width:'100%' },
  eyeBtn:{ position:'absolute', right:12, top:13, paddingHorizontal:6, paddingVertical:2 },
  eyeText:{ color:C.accent, fontSize:12, fontWeight:'900' },
  recoveryRow:{ flexDirection:'row', justifyContent:'space-between', alignItems:'center', marginTop:-4, marginBottom:12 },
  recoveryLink:{ color:C.accent, fontSize:12, fontWeight:'800' },
  passwordRules:{ backgroundColor:C.surface2, borderRadius:12, padding:14, marginTop:4, marginBottom:8, borderWidth:1, borderColor:C.border },
  passwordRulesTitle:{ color:C.text2, fontSize:11, fontWeight:'600', marginBottom:8, textTransform:'uppercase', letterSpacing:0.5 },
  errorBox:{ backgroundColor:'rgba(255,107,107,0.08)', borderWidth:1, borderColor:'rgba(255,107,107,0.2)', borderRadius:10, padding:12, marginBottom:12 },
  errorTxt:{ color:C.red, fontSize:13 },
  authBtn:{ backgroundColor:C.accent, borderRadius:14, padding:16, alignItems:'center', marginTop:4, shadowColor:C.accent, shadowOpacity:0.32, shadowRadius:14, shadowOffset:{width:0,height:8}, elevation:4 },
  authBtnTxt:{ color:'#fff', fontSize:16, fontWeight:'700' },

  privacyNote:{ backgroundColor:'rgba(124,109,255,0.06)', borderWidth:1, borderColor:'rgba(124,109,255,0.18)', borderRadius:14, padding:14, marginTop:16, width:'100%' },
  privacyNoteTxt:{ color:C.text2, fontSize:12, lineHeight:18, textAlign:'center' },

  divider:{ flexDirection:'row', alignItems:'center', gap:12, width:'100%', marginVertical:20 },
  dividerLine:{ flex:1, height:1, backgroundColor:C.border },
  dividerTxt:{ color:C.text3, fontSize:13 },

  guestSection:{ width:'100%', alignItems:'center' },
  guestTitle:{ color:C.text2, fontSize:13, marginBottom:10 },
  guestBtn:{ backgroundColor:C.surface2, borderWidth:1, borderColor:'rgba(243,199,92,0.38)', borderRadius:14, paddingHorizontal:24, paddingVertical:14, width:'100%', alignItems:'center', marginBottom:10 },
  guestBtnTxt:{ color:C.gold, fontSize:14, fontWeight:'600' },
  guestWarning:{ color:C.text3, fontSize:11, textAlign:'center', lineHeight:16 },
});
