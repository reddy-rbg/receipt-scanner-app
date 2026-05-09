// ─────────────────────────────────────────
// app/LoginScreen.tsx
// Full screen login shown before tabs unlock
// ─────────────────────────────────────────

import { useState } from 'react';
import {
  View, Text, ScrollView, TouchableOpacity, StyleSheet,
  TextInput, ActivityIndicator, Alert,
} from 'react-native';
import { saveUser, startGuestSession } from './authStore';

const API = 'https://web-production-3605f4.up.railway.app';

const C = {
  bg:'#080810', surface:'#0f0f1a', surface2:'#16162a', surface3:'#1e1e35',
  border:'rgba(255,255,255,0.06)',
  accent:'#7c6aff', accent2:'#ff6a9e', accent3:'#6affd4',
  text:'#ede8ff', text2:'#7e7a9a', text3:'#3d3a55',
  green:'#4ade80', red:'#ff6b6b', gold:'#fbbf24',
};

function validatePassword(password: string): string[] {
  const errors: string[] = [];
  if (password.length < 8)                  errors.push('At least 8 characters');
  if (!/[A-Z]/.test(password))             errors.push('At least 1 uppercase letter');
  if (!/[a-z]/.test(password))             errors.push('At least 1 lowercase letter');
  if (!/[.,?!@#$%&*_\-+]/.test(password)) errors.push('At least 1 special character');
  return errors;
}

function PasswordStrengthBar({ password }: { password: string }) {
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
        ? <Text style={{ fontSize:11, color:C.text3 }}>Missing: {errors.join(' · ')}</Text>
        : <Text style={{ fontSize:11, color:C.green }}>✓ Strong password</Text>
      }
    </View>
  );
}

export default function LoginScreen() {
  const [mode, setMode]         = useState<'login'|'signup'>('login');
  const [email, setEmail]       = useState('');
  const [password, setPassword] = useState('');
  const [name, setName]         = useState('');
  const [showPw, setShowPw]     = useState(false);
  const [loading, setLoading]   = useState(false);
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
      const data = await res.json();

      if (!res.ok) { setError(data.detail || 'Authentication failed.'); return; }

      await saveUser({
        id:         data.user.id,
        email:      data.user.email,
        name:       data.user.name,
        created_at: data.user.created_at,
        token:      data.session?.access_token,
        isGuest:    false,
      });

    } catch { setError('Could not connect. Please try again.'); }
    finally  { setLoading(false); }
  }

  async function handleGuest() {
    await startGuestSession();
  }

  return (
    <ScrollView style={s.scroll} contentContainerStyle={s.container} keyboardShouldPersistTaps="handled">

      {/* Logo */}
      <View style={s.logoWrap}>
        <View style={s.logo}>
          <Text style={s.logoIcon}>✦</Text>
        </View>
        <Text style={s.appName}>ReceiptAI</Text>
        <Text style={s.appTagline}>Smart Receipt Scanner</Text>
      </View>

      {/* Security badge */}
      <View style={s.securityBadge}>
        <Text style={s.securityBadgeText}>🔒  Your data is encrypted and private</Text>
      </View>

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
              <Text style={s.eyeText}>{showPw?'🙈':'👁'}</Text>
            </TouchableOpacity>
          </View>
          {mode==='signup' && <PasswordStrengthBar password={password}/>}
        </View>

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
                <Text style={{ color: item.ok ? C.green : C.text3, fontSize:13, width:20 }}>{item.ok?'✓':'○'}</Text>
                <Text style={{ color: item.ok ? C.green : C.text3, fontSize:12 }}>{item.rule}</Text>
              </View>
            ))}
          </View>
        )}

        {error!=='' && (
          <View style={s.errorBox}>
            <Text style={s.errorTxt}>⚠  {error}</Text>
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

      {/* Privacy note */}
      <View style={s.privacyNote}>
        <Text style={s.privacyNoteTxt}>🔐  We never sell your data. Your receipts are private and only visible to you.</Text>
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
          <Text style={s.guestBtnTxt}>⏱  Start 24-Hour Free Trial</Text>
        </TouchableOpacity>
        <Text style={s.guestWarning}>
          Trial data is automatically deleted after 24 hours.{'\n'}
          Sign up to keep your receipts permanently.
        </Text>
      </View>

    </ScrollView>
  );
}

const s = StyleSheet.create({
  scroll:{ flex:1, backgroundColor:C.bg },
  container:{ padding:24, paddingBottom:50, alignItems:'center', minHeight:'100%', justifyContent:'center' },

  logoWrap:{ alignItems:'center', marginBottom:24, marginTop:20 },
  logo:{ width:90, height:90, borderRadius:24, backgroundColor:'rgba(124,106,255,0.18)', borderWidth:2, borderColor:C.accent, alignItems:'center', justifyContent:'center', marginBottom:16, shadowColor:C.accent, shadowOpacity:0.4, shadowRadius:20 },
  logoIcon:{ fontSize:40, color:C.accent },
  appName:{ fontSize:32, fontWeight:'800', color:C.text, letterSpacing:-1, marginBottom:4 },
  appTagline:{ fontSize:14, color:C.text2 },

  securityBadge:{ backgroundColor:'rgba(74,222,128,0.1)', borderWidth:1, borderColor:'rgba(74,222,128,0.25)', borderRadius:99, paddingHorizontal:16, paddingVertical:7, marginBottom:24 },
  securityBadgeText:{ color:C.green, fontSize:12, fontWeight:'500' },

  tabRow:{ flexDirection:'row', backgroundColor:C.surface2, borderRadius:12, padding:4, marginBottom:20, width:'100%', borderWidth:1, borderColor:C.border },
  tab:{ flex:1, padding:10, borderRadius:10, alignItems:'center' },
  tabActive:{ backgroundColor:C.accent },
  tabTxt:{ color:C.text2, fontSize:14, fontWeight:'600' },
  tabTxtActive:{ color:'#fff' },

  form:{ width:'100%' },
  inputWrap:{ marginBottom:14 },
  inputLabel:{ color:C.text2, fontSize:12, marginBottom:6, fontWeight:'500' },
  input:{ backgroundColor:C.surface2, borderWidth:1, borderColor:C.border, borderRadius:12, padding:14, paddingHorizontal:16, color:C.text, fontSize:14, width:'100%' },
  eyeBtn:{ position:'absolute', right:14, top:14 },
  eyeText:{ fontSize:18 },
  passwordRules:{ backgroundColor:C.surface2, borderRadius:12, padding:14, marginTop:4, marginBottom:8, borderWidth:1, borderColor:C.border },
  passwordRulesTitle:{ color:C.text2, fontSize:11, fontWeight:'600', marginBottom:8, textTransform:'uppercase', letterSpacing:0.5 },
  errorBox:{ backgroundColor:'rgba(255,107,107,0.08)', borderWidth:1, borderColor:'rgba(255,107,107,0.2)', borderRadius:10, padding:12, marginBottom:12 },
  errorTxt:{ color:C.red, fontSize:13 },
  authBtn:{ backgroundColor:C.accent, borderRadius:12, padding:16, alignItems:'center', marginTop:4, shadowColor:C.accent, shadowOpacity:0.4, shadowRadius:12 },
  authBtnTxt:{ color:'#fff', fontSize:16, fontWeight:'700' },

  privacyNote:{ backgroundColor:'rgba(124,106,255,0.06)', borderWidth:1, borderColor:'rgba(124,106,255,0.15)', borderRadius:12, padding:14, marginTop:16, width:'100%' },
  privacyNoteTxt:{ color:C.text2, fontSize:12, lineHeight:18, textAlign:'center' },

  divider:{ flexDirection:'row', alignItems:'center', gap:12, width:'100%', marginVertical:20 },
  dividerLine:{ flex:1, height:1, backgroundColor:C.border },
  dividerTxt:{ color:C.text3, fontSize:13 },

  guestSection:{ width:'100%', alignItems:'center' },
  guestTitle:{ color:C.text2, fontSize:13, marginBottom:10 },
  guestBtn:{ backgroundColor:C.surface2, borderWidth:1, borderColor:'rgba(251,191,36,0.35)', borderRadius:12, paddingHorizontal:24, paddingVertical:14, width:'100%', alignItems:'center', marginBottom:10 },
  guestBtnTxt:{ color:C.gold, fontSize:14, fontWeight:'600' },
  guestWarning:{ color:C.text3, fontSize:11, textAlign:'center', lineHeight:16 },
});
