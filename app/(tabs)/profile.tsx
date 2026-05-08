import { useState, useEffect, useRef } from 'react';
import * as Updates from 'expo-updates';
import {
  View, Text, ScrollView, TouchableOpacity, StyleSheet,
  ActivityIndicator, TextInput, Alert, Modal, Linking, Share,
} from 'react-native';

const API = 'https://web-production-3605f4.up.railway.app';

const C = {
  bg:'#080810', surface:'#0f0f1a', surface2:'#16162a', surface3:'#1e1e35',
  border:'rgba(255,255,255,0.06)',
  accent:'#7c6aff', accent2:'#ff6a9e', accent3:'#6affd4',
  text:'#ede8ff', text2:'#7e7a9a', text3:'#3d3a55',
  green:'#4ade80', red:'#ff6b6b', gold:'#fbbf24',
};

type User = { id:string; email:string; name:string; created_at:string; token?:string; guestStartTime?:number };

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

// ── Guest countdown timer ──
function GuestCountdown({ startTime, onExpired }: { startTime: number; onExpired: () => void }) {
  const TRIAL_MS = 24 * 60 * 60 * 1000; // 24 hours
  const [remaining, setRemaining] = useState(TRIAL_MS - (Date.now() - startTime));

  useEffect(() => {
    const interval = setInterval(() => {
      const left = TRIAL_MS - (Date.now() - startTime);
      if (left <= 0) { clearInterval(interval); onExpired(); return; }
      setRemaining(left);
    }, 1000);
    return () => clearInterval(interval);
  }, [startTime]);

  const hours   = Math.floor(remaining / (1000 * 60 * 60));
  const minutes = Math.floor((remaining % (1000 * 60 * 60)) / (1000 * 60));
  const seconds = Math.floor((remaining % (1000 * 60)) / 1000);

  const urgentColor = hours < 2 ? C.red : hours < 6 ? C.gold : C.accent3;

  return (
    <View style={gc.container}>
      <View style={gc.header}>
        <Text style={gc.title}>⏱  Guest Trial Mode</Text>
        <Text style={[gc.timer, { color: urgentColor }]}>
          {String(hours).padStart(2,'0')}:{String(minutes).padStart(2,'0')}:{String(seconds).padStart(2,'0')}
        </Text>
      </View>
      <Text style={gc.desc}>
        Your trial data will be <Text style={{ color: C.red, fontWeight:'600' }}>automatically deleted</Text> when the timer expires. Sign up to keep your receipts forever.
      </Text>
      <View style={gc.bullets}>
        {['All scanned receipts will be deleted','Price history will be lost','Shopping lists will be cleared'].map((b,i) => (
          <View key={i} style={{ flexDirection:'row', gap:6, marginBottom:4 }}>
            <Text style={{ color:C.red, fontSize:12 }}>✗</Text>
            <Text style={{ color:C.text2, fontSize:12 }}>{b}</Text>
          </View>
        ))}
      </View>
    </View>
  );
}

const gc = StyleSheet.create({
  container:{ backgroundColor:'rgba(255,107,107,0.07)', borderWidth:1, borderColor:'rgba(255,107,107,0.25)', borderRadius:16, padding:16, marginBottom:16 },
  header:{ flexDirection:'row', justifyContent:'space-between', alignItems:'center', marginBottom:8 },
  title:{ color:C.text, fontSize:14, fontWeight:'700' },
  timer:{ fontFamily:'monospace', fontSize:22, fontWeight:'800', letterSpacing:2 },
  desc:{ color:C.text2, fontSize:12, lineHeight:18, marginBottom:10 },
  bullets:{ gap:2 },
});

const n = (v:any) => parseFloat(v)||0;

export default function ProfileScreen() {
  const [user, setUser]         = useState<User|null>(null);
  const [authMode, setAuthMode] = useState<'login'|'signup'>('login');
  const [email, setEmail]       = useState('');
  const [password, setPassword] = useState('');
  const [name, setName]         = useState('');
  const [showPassword, setShowPassword] = useState(false);
  const [authLoading, setAuthLoading]   = useState(false);
  const [authError, setAuthError]       = useState('');

  const [stats, setStats]           = useState({ receipts:0, spent:0, saved:0, stores:0 });
  const [statsLoading, setStatsLoading] = useState(true);
  const [activeModal, setActiveModal]   = useState<string|null>(null);

  const [deleteEmail, setDeleteEmail]       = useState('');
  const [deletePassword, setDeletePassword] = useState('');
  const [deleteLoading, setDeleteLoading]   = useState(false);
  const [deleteError, setDeleteError]       = useState('');

  const [updateAvailable, setUpdateAvailable] = useState(false);
  const [updateLoading, setUpdateLoading]     = useState(false);

  useEffect(() => { if (user) { loadStats(); checkForUpdates(); } }, [user]);

  async function loadStats() {
    setStatsLoading(true);
    try {
      const headers: any = { 'Content-Type':'application/json' };
      if (user?.token) headers['Authorization'] = `Bearer ${user.token}`;
      // Guest: pass session ID so backend returns only guest data
      if (user?.id === 'guest') headers['X-Guest-Session'] = user.created_at;
      const res = await fetch(`${API}/summary`, { headers });
      const d   = await res.json();
      setStats({
        receipts: d.total_receipts || 0,
        spent:    d.total_spent    || 0,
        saved:    d.total_saved    || 0,
        stores:   d.unique_stores  || 0,
      });
    } catch {}
    finally { setStatsLoading(false); }
  }

  // ── Guest expired ──
  function handleGuestExpired() {
    Alert.alert(
      '⏱ Trial Expired',
      'Your 24-hour guest trial has ended. All your trial data has been deleted. Sign up to use ReceiptAI with permanent storage.',
      [{ text: 'Create Account', onPress: () => { setUser(null); setAuthMode('signup'); } }]
    );
  }

  // ── Auth ──
  async function handleAuth() {
    setAuthError('');
    if (!email.trim())  { setAuthError('Please enter your email.'); return; }
    if (!password)      { setAuthError('Please enter your password.'); return; }
    if (authMode === 'signup') {
      if (!name.trim()) { setAuthError('Please enter your name.'); return; }
      const errors = validatePassword(password);
      if (errors.length > 0) { setAuthError('Password requirements not met.'); return; }
    }

    setAuthLoading(true);
    try {
      const endpoint = authMode === 'login' ? '/auth/login' : '/auth/signup';
      const body: any = { email: email.trim().toLowerCase(), password };
      if (authMode === 'signup') body.name = name.trim();

      const res  = await fetch(`${API}${endpoint}`, {
        method:'POST', headers:{'Content-Type':'application/json'},
        body: JSON.stringify(body),
      });
      const data = await res.json();
      if (!res.ok) { setAuthError(data.detail || 'Authentication failed.'); return; }

      setUser({
        id:         data.user.id,
        email:      data.user.email,
        name:       data.user.name,
        created_at: data.user.created_at,
        token:      data.session?.access_token,
      });
      setEmail(''); setPassword(''); setName('');
    } catch { setAuthError('Could not connect. Please try again.'); }
    finally  { setAuthLoading(false); }
  }

  function handleSignOut() {
    Alert.alert('Sign Out', 'Are you sure you want to sign out?', [
      { text:'Cancel', style:'cancel' },
      { text:'Sign Out', style:'destructive', onPress:() => {
        setUser(null); setAuthMode('login');
        setEmail(''); setPassword(''); setName('');
      }},
    ]);
  }

  async function handleDeleteAccount() {
    setDeleteError('');
    if (!deleteEmail.trim() || !deletePassword) { setDeleteError('Please enter your credentials.'); return; }
    if (deleteEmail.trim().toLowerCase() !== user?.email?.toLowerCase()) { setDeleteError('Email does not match your account.'); return; }
    setDeleteLoading(true);
    try {
      const res  = await fetch(`${API}/auth/delete-account`, {
        method:'DELETE', headers:{'Content-Type':'application/json'},
        body: JSON.stringify({ email: deleteEmail.trim().toLowerCase(), password: deletePassword }),
      });
      const data = await res.json();
      if (!res.ok) { setDeleteError(data.detail || 'Could not delete account.'); return; }
      setActiveModal(null);
      Alert.alert('Account Deleted', 'Your account and all data have been permanently deleted.', [
        { text:'OK', onPress:() => { setUser(null); setAuthMode('login'); } }
      ]);
    } catch { setDeleteError('Could not connect. Please try again.'); }
    finally  { setDeleteLoading(false); }
  }

  async function checkForUpdates() {
    try {
      setUpdateLoading(true);
      const update = await Updates.checkForUpdateAsync();
      if (update.isAvailable) {
        setUpdateAvailable(true);
        Alert.alert(
          '🎉 Update Available!',
          'A new version of ReceiptAI is ready. Install now?',
          [
            { text:'Later', style:'cancel' },
            {
              text:'Update Now',
              onPress: async () => {
                await Updates.fetchUpdateAsync();
                await Updates.reloadAsync();
              }
            }
          ]
        );
      } else {
        Alert.alert('✓ Up to date', 'You have the latest version of ReceiptAI!');
      }
    } catch {
      Alert.alert('Check failed', 'Could not check for updates. Try again later.');
    } finally {
      setUpdateLoading(false);
    }
  }

  async function handleShare() {
    try {
      await Share.share({ message:'📱 Check out ReceiptAI — scan receipts, track prices, and save money on groceries!', title:'ReceiptAI' });
    } catch {}
  }

  function handleHelpSupport() {
    Alert.alert('Help & Support', 'How can we help?', [
      { text:'Cancel', style:'cancel' },
      { text:'📧 Email Support', onPress:() => Linking.openURL('mailto:support@receiptai.app') },
    ]);
  }

  function handleRateApp() {
    Alert.alert('Rate ReceiptAI', 'How would you rate your experience?\n\n⭐ ⭐ ⭐ ⭐ ⭐', [
      { text:'⭐ 1',     onPress:() => Alert.alert('Thank you!','We will work hard to improve!') },
      { text:'⭐⭐ 2',   onPress:() => Alert.alert('Thank you!','We appreciate your feedback!') },
      { text:'⭐⭐⭐ 3', onPress:() => Alert.alert('Thank you!','We will keep improving!') },
      { text:'⭐⭐⭐⭐ 4',   onPress:() => Alert.alert('Thank you! 😊','So glad you enjoy ReceiptAI!') },
      { text:'⭐⭐⭐⭐⭐ 5', onPress:() => Alert.alert('Thank you! 🎉','You made our day!') },
    ]);
  }

  // ── AUTH SCREEN ──
  if (!user) {
    return (
      <ScrollView style={s.authScroll} contentContainerStyle={s.authContainer} keyboardShouldPersistTaps="handled">
        <View style={s.authLogo}>
          <Text style={s.authLogoText}>{authMode==='login'?'✦':'+'}</Text>
        </View>
        <Text style={s.authTitle}>{authMode==='login'?'Welcome Back':'Create Account'}</Text>
        <Text style={s.authSubtitle}>{authMode==='login'?'Sign in to your account':'Join ReceiptAI today'}</Text>

        <View style={s.securityBadge}>
          <Text style={s.securityBadgeText}>🔒  Your data is encrypted and private</Text>
        </View>

        <View style={s.authForm}>
          {authMode==='signup' && (
            <View style={s.inputWrap}>
              <Text style={s.inputLabel}>Full Name</Text>
              <TextInput style={s.authInput} placeholder="John Smith" placeholderTextColor={C.text3} value={name} onChangeText={setName} autoCapitalize="words"/>
            </View>
          )}

          <View style={s.inputWrap}>
            <Text style={s.inputLabel}>Email Address</Text>
            <TextInput style={s.authInput} placeholder="you@example.com" placeholderTextColor={C.text3} value={email} onChangeText={setEmail} keyboardType="email-address" autoCapitalize="none" autoCorrect={false}/>
          </View>

          <View style={s.inputWrap}>
            <Text style={s.inputLabel}>Password</Text>
            <View style={{ position:'relative' }}>
              <TextInput
                style={[s.authInput,{ paddingRight:50 }]}
                placeholder={authMode==='signup'?'Min 8 chars, 1 capital, 1 special':'Enter your password'}
                placeholderTextColor={C.text3}
                value={password}
                onChangeText={setPassword}
                secureTextEntry={!showPassword}
              />
              <TouchableOpacity style={s.eyeBtn} onPress={()=>setShowPassword(!showPassword)}>
                <Text style={s.eyeText}>{showPassword?'🙈':'👁'}</Text>
              </TouchableOpacity>
            </View>
            {authMode==='signup' && <PasswordStrengthBar password={password}/>}
          </View>

          {authMode==='signup' && (
            <View style={s.passwordRules}>
              <Text style={s.passwordRulesTitle}>Password must have:</Text>
              {[
                { rule:'At least 8 characters',          ok: password.length >= 8 },
                { rule:'1 uppercase letter (A-Z)',        ok: /[A-Z]/.test(password) },
                { rule:'1 lowercase letter (a-z)',        ok: /[a-z]/.test(password) },
                { rule:'1 special character (.,?!@#$%)', ok: /[.,?!@#$%&*_\-+]/.test(password) },
              ].map((item,i) => (
                <View key={i} style={s.passwordRule}>
                  <Text style={{ color: item.ok ? C.green : C.text3, fontSize:13 }}>{item.ok?'✓':'○'}</Text>
                  <Text style={{ color: item.ok ? C.green : C.text3, fontSize:12, marginLeft:6 }}>{item.rule}</Text>
                </View>
              ))}
            </View>
          )}

          {authError!=='' && (
            <View style={s.authError}>
              <Text style={s.authErrorText}>⚠  {authError}</Text>
            </View>
          )}

          <TouchableOpacity style={[s.authBtn, authLoading&&{opacity:0.5}]} onPress={handleAuth} disabled={authLoading} activeOpacity={0.85}>
            {authLoading
              ? <ActivityIndicator color="#fff" size="small"/>
              : <Text style={s.authBtnText}>{authMode==='login'?'Sign In':'Create Account'}</Text>
            }
          </TouchableOpacity>

          <TouchableOpacity style={s.switchModeBtn} onPress={()=>{ setAuthMode(authMode==='login'?'signup':'login'); setAuthError(''); setPassword(''); }}>
            <Text style={s.switchModeTxt}>
              {authMode==='login'?"Don't have an account? ":'Already have an account? '}
              <Text style={{ color:C.accent, fontWeight:'600' }}>{authMode==='login'?'Sign Up':'Sign In'}</Text>
            </Text>
          </TouchableOpacity>
        </View>

        <View style={s.privacyNote}>
          <Text style={s.privacyNoteText}>🔐  We never sell your data. Your receipts are private and only visible to you.</Text>
        </View>

        {/* Guest trial button */}
        <View style={s.guestSection}>
          <Text style={s.guestSectionTitle}>Want to try first?</Text>
          <TouchableOpacity
            style={s.guestBtn}
            onPress={() => setUser({
              id:             'guest',
              email:          'guest@receiptai.app',
              name:           'Guest User',
              created_at:     new Date().toISOString(),
              guestStartTime: Date.now(),
            })}
          >
            <Text style={s.guestBtnText}>⏱  Start 24-Hour Free Trial</Text>
          </TouchableOpacity>
          <Text style={s.guestWarning}>Trial data is automatically deleted after 24 hours</Text>
        </View>
      </ScrollView>
    );
  }

  const isGuest = user.id === 'guest';

  // ── PROFILE SCREEN ──
  return (
    <ScrollView style={s.scroll} contentContainerStyle={s.container} showsVerticalScrollIndicator={false}>

      {/* Guest countdown banner */}
      {isGuest && user.guestStartTime && (
        <GuestCountdown startTime={user.guestStartTime} onExpired={handleGuestExpired}/>
      )}

      {/* Sign up CTA for guests */}
      {isGuest && (
        <TouchableOpacity style={s.signUpCTA} onPress={()=>{ setUser(null); setAuthMode('signup'); }} activeOpacity={0.85}>
          <Text style={s.signUpCTAText}>✦  Create a free account to save your data permanently</Text>
        </TouchableOpacity>
      )}

      {/* Avatar */}
      <View style={s.avatarSection}>
        <View style={s.avatar}>
          <Text style={s.avatarText}>{isGuest ? '👤' : user.name?.[0]?.toUpperCase()||'✦'}</Text>
        </View>
        <Text style={s.userName}>{isGuest ? 'Guest User' : user.name}</Text>
        <Text style={s.userEmail}>{isGuest ? '24-Hour Trial Mode' : user.email}</Text>
        <View style={[s.statusBadge, isGuest && { borderColor:'rgba(251,191,36,0.3)', backgroundColor:'rgba(251,191,36,0.08)' }]}>
          <View style={[s.statusDot, isGuest && { backgroundColor:C.gold }]}/>
          <Text style={[s.statusText, isGuest && { color:C.gold }]}>
            {isGuest ? '⏱ Trial — Data deletes in 24h' : 'Verified Account 🔒'}
          </Text>
        </View>
      </View>

      {/* Stats */}
      {statsLoading
        ? <ActivityIndicator color={C.accent} style={{ marginBottom:16 }}/>
        : (
          <View style={s.statsGrid}>
            <View style={[s.statBox,{ borderBottomColor:C.accent }]}>
              <Text style={[s.statVal,{ color:C.accent }]}>{stats.receipts}</Text>
              <Text style={s.statLbl}>Receipts</Text>
            </View>
            <View style={[s.statBox,{ borderBottomColor:C.accent2 }]}>
              <Text style={[s.statVal,{ color:C.accent2 }]}>${n(stats.spent).toFixed(0)}</Text>
              <Text style={s.statLbl}>Spent</Text>
            </View>
            <View style={[s.statBox,{ borderBottomColor:C.accent3 }]}>
              <Text style={[s.statVal,{ color:C.accent3 }]}>${n(stats.saved).toFixed(0)}</Text>
              <Text style={s.statLbl}>Saved</Text>
            </View>
            <View style={[s.statBox,{ borderBottomColor:C.gold }]}>
              <Text style={[s.statVal,{ color:C.gold }]}>{stats.stores}</Text>
              <Text style={s.statLbl}>Stores</Text>
            </View>
          </View>
        )
      }

      {/* Menu */}
      <View style={s.menuCard}>
        <Text style={s.menuSection}>Notifications</Text>
        <TouchableOpacity style={s.menuItem} onPress={()=>setActiveModal('notifications')} disabled={isGuest}>
          <View style={[s.menuIcon,{ backgroundColor:C.accent+'22' }]}><Text>🔔</Text></View>
          <Text style={[s.menuLabel, isGuest && { color:C.text3 }]}>Notifications</Text>
          <Text style={s.menuArrow}>{isGuest ? '🔒' : '›'}</Text>
        </TouchableOpacity>

        <Text style={[s.menuSection,{ marginTop:16 }]}>Privacy</Text>
        <TouchableOpacity style={s.menuItem} onPress={()=>setActiveModal('privacy')} disabled={isGuest}>
          <View style={[s.menuIcon,{ backgroundColor:C.accent2+'22' }]}><Text>🔒</Text></View>
          <Text style={[s.menuLabel, isGuest && { color:C.text3 }]}>Privacy & Security</Text>
          <Text style={s.menuArrow}>{isGuest ? '🔒' : '›'}</Text>
        </TouchableOpacity>

        <Text style={[s.menuSection,{ marginTop:16 }]}>Preferences</Text>
        <TouchableOpacity style={s.menuItem} onPress={()=>setActiveModal('appearance')}>
          <View style={[s.menuIcon,{ backgroundColor:C.accent3+'22' }]}><Text>🎨</Text></View>
          <Text style={s.menuLabel}>Appearance</Text>
          <Text style={s.menuArrow}>›</Text>
        </TouchableOpacity>

        <Text style={[s.menuSection,{ marginTop:16 }]}>Support</Text>
        <TouchableOpacity style={s.menuItem} onPress={handleHelpSupport}>
          <View style={[s.menuIcon,{ backgroundColor:C.gold+'22' }]}><Text>❓</Text></View>
          <Text style={s.menuLabel}>Help & Support</Text>
          <Text style={s.menuArrow}>›</Text>
        </TouchableOpacity>

        <TouchableOpacity style={s.menuItem} onPress={handleRateApp}>
          <View style={[s.menuIcon,{ backgroundColor:C.green+'22' }]}><Text>⭐</Text></View>
          <Text style={s.menuLabel}>Rate ReceiptAI</Text>
          <Text style={s.menuArrow}>›</Text>
        </TouchableOpacity>

        <TouchableOpacity style={s.menuItem} onPress={handleShare}>
          <View style={[s.menuIcon,{ backgroundColor:C.text2+'22' }]}><Text>📤</Text></View>
          <Text style={s.menuLabel}>Share App</Text>
          <Text style={s.menuArrow}>›</Text>
        </TouchableOpacity>

        <TouchableOpacity style={[s.menuItem,{borderBottomWidth:0}]} onPress={checkForUpdates} disabled={updateLoading}>
          <View style={[s.menuIcon,{backgroundColor:'rgba(74,222,128,0.18)'}]}>
            <Text>{updateLoading?'⏳':updateAvailable?'🔴':'✅'}</Text>
          </View>
          <Text style={[s.menuLabel,updateAvailable&&{color:C.green}]}>
            {updateLoading?'Checking...':updateAvailable?'Update Available!':'Check for Updates'}
          </Text>
          {updateLoading
            ?<ActivityIndicator size="small" color={C.accent}/>
            :<Text style={s.menuArrow}>›</Text>
          }
        </TouchableOpacity>
      </View>

      {isGuest ? (
        <TouchableOpacity style={s.authBtn} onPress={()=>{ setUser(null); setAuthMode('signup'); }} activeOpacity={0.85}>
          <Text style={s.authBtnText}>✦  Create Free Account</Text>
        </TouchableOpacity>
      ) : (
        <TouchableOpacity style={s.signOutBtn} onPress={handleSignOut}>
          <Text style={s.signOutText}>Sign Out</Text>
        </TouchableOpacity>
      )}

      {!isGuest && (
        <TouchableOpacity style={s.deleteAccountBtn} onPress={()=>{ setActiveModal('deleteAccount'); setDeleteEmail(''); setDeletePassword(''); setDeleteError(''); }}>
          <Text style={s.deleteAccountText}>🗑  Delete My Account</Text>
        </TouchableOpacity>
      )}

      <Text style={s.version}>ReceiptAI v1.0  ·  {isGuest ? 'Trial mode — 24h data expiry' : 'Your data is always private 🔒'}</Text>

      {/* ── NOTIFICATIONS MODAL ── */}
      <Modal visible={activeModal==='notifications'} animationType="slide" presentationStyle="pageSheet" onRequestClose={()=>setActiveModal(null)}>
        <View style={s.modal}>
          <View style={s.modalHeader}>
            <Text style={s.modalTitle}>🔔  Notifications</Text>
            <TouchableOpacity onPress={()=>setActiveModal(null)} style={s.modalClose}><Text style={s.modalCloseTxt}>✕</Text></TouchableOpacity>
          </View>
          <ScrollView contentContainerStyle={s.modalBody}>
            <Text style={s.settingDesc}>Notification settings coming soon in the next update!</Text>
          </ScrollView>
        </View>
      </Modal>

      {/* ── PRIVACY MODAL ── */}
      <Modal visible={activeModal==='privacy'} animationType="slide" presentationStyle="pageSheet" onRequestClose={()=>setActiveModal(null)}>
        <View style={s.modal}>
          <View style={s.modalHeader}>
            <Text style={s.modalTitle}>🔒  Privacy & Security</Text>
            <TouchableOpacity onPress={()=>setActiveModal(null)} style={s.modalClose}><Text style={s.modalCloseTxt}>✕</Text></TouchableOpacity>
          </View>
          <ScrollView contentContainerStyle={s.modalBody}>
            <Text style={s.settingSection}>Account</Text>
            <View style={s.infoRow}>
              <Text style={s.infoLabel}>Email</Text>
              <Text style={s.infoValue}>{user?.email}</Text>
            </View>
            <View style={s.infoRow}>
              <Text style={s.infoLabel}>Member since</Text>
              <Text style={s.infoValue}>
                {user?.created_at ? new Date(user.created_at).toLocaleDateString('en-US',{ month:'long', year:'numeric' }) : '—'}
              </Text>
            </View>
            <View style={[s.infoRow,{ borderBottomWidth:0 }]}>
              <Text style={s.infoLabel}>Account status</Text>
              <Text style={[s.infoValue,{ color:C.green }]}>● Active</Text>
            </View>

            <Text style={[s.settingSection,{ marginTop:24 }]}>Your Data</Text>
            <TouchableOpacity style={s.privacyLink} onPress={()=>Alert.alert('Privacy Policy','All your receipts are private and only accessible by you. We never share or sell your personal data.')}>
              <Text style={s.privacyLinkText}>Data Privacy Policy</Text>
              <Text style={s.menuArrow}>›</Text>
            </TouchableOpacity>
            <TouchableOpacity style={s.privacyLink} onPress={()=>Alert.alert('Export Data','Data export feature coming soon!')}>
              <Text style={s.privacyLinkText}>Export My Data</Text>
              <Text style={s.menuArrow}>›</Text>
            </TouchableOpacity>
            <TouchableOpacity style={[s.privacyLink,{ borderBottomWidth:0 }]} onPress={()=>{ setActiveModal('deleteAccount'); setDeleteEmail(''); setDeletePassword(''); setDeleteError(''); }}>
              <Text style={[s.privacyLinkText,{ color:C.red }]}>Delete My Account</Text>
              <Text style={s.menuArrow}>›</Text>
            </TouchableOpacity>
          </ScrollView>
        </View>
      </Modal>

      {/* ── APPEARANCE MODAL ── */}
      <Modal visible={activeModal==='appearance'} animationType="slide" presentationStyle="pageSheet" onRequestClose={()=>setActiveModal(null)}>
        <View style={s.modal}>
          <View style={s.modalHeader}>
            <Text style={s.modalTitle}>🎨  Appearance</Text>
            <TouchableOpacity onPress={()=>setActiveModal(null)} style={s.modalClose}><Text style={s.modalCloseTxt}>✕</Text></TouchableOpacity>
          </View>
          <ScrollView contentContainerStyle={s.modalBody}>
            <Text style={s.settingDesc}>Theme and appearance settings coming soon!</Text>
            <Text style={[s.settingSection,{ marginTop:16 }]}>App Theme Color</Text>
            {[
              { name:'Purple (Default)', color:'#7c6aff' },
              { name:'Pink',             color:'#ff6a9e' },
              { name:'Teal',             color:'#6affd4' },
              { name:'Gold',             color:'#fbbf24' },
            ].map((theme,i) => (
              <TouchableOpacity key={i} style={s.themeRow} onPress={()=>Alert.alert('Theme',`${theme.name} theme coming soon!`)}>
                <View style={[s.themeColor,{ backgroundColor:theme.color }]}/>
                <Text style={s.themeLabel}>{theme.name}</Text>
                {i===0 && <Text style={[s.themeActive,{ color:theme.color }]}>Active</Text>}
              </TouchableOpacity>
            ))}
          </ScrollView>
        </View>
      </Modal>

      {/* ── DELETE ACCOUNT MODAL ── */}
      <Modal visible={activeModal==='deleteAccount'} animationType="slide" presentationStyle="pageSheet" onRequestClose={()=>setActiveModal(null)}>
        <View style={s.modal}>
          <View style={s.modalHeader}>
            <Text style={s.modalTitle}>🗑  Delete Account</Text>
            <TouchableOpacity onPress={()=>setActiveModal(null)} style={s.modalClose}><Text style={s.modalCloseTxt}>✕</Text></TouchableOpacity>
          </View>
          <ScrollView contentContainerStyle={s.modalBody}>
            <View style={s.deleteWarning}>
              <Text style={s.deleteWarningTitle}>⚠️  This cannot be undone</Text>
              <Text style={s.deleteWarningText}>Deleting your account will permanently remove:</Text>
              <View style={{ gap:6, marginTop:8 }}>
                {['All your scanned receipts','All your purchase history','All your saved data','Your account and login'].map((item,i) => (
                  <View key={i} style={{ flexDirection:'row', gap:8, alignItems:'center' }}>
                    <Text style={{ color:C.red, fontSize:13 }}>✗</Text>
                    <Text style={{ color:C.text2, fontSize:13 }}>{item}</Text>
                  </View>
                ))}
              </View>
            </View>

            <Text style={s.settingDesc}>To confirm, enter your account credentials:</Text>

            <View style={s.inputWrap}>
              <Text style={s.inputLabel}>Your Email</Text>
              <TextInput style={s.authInput} placeholder={user?.email} placeholderTextColor={C.text3} value={deleteEmail} onChangeText={setDeleteEmail} keyboardType="email-address" autoCapitalize="none"/>
            </View>
            <View style={s.inputWrap}>
              <Text style={s.inputLabel}>Your Password</Text>
              <TextInput style={s.authInput} placeholder="Enter your password" placeholderTextColor={C.text3} value={deletePassword} onChangeText={setDeletePassword} secureTextEntry/>
            </View>

            {deleteError!=='' && (
              <View style={s.authError}>
                <Text style={s.authErrorText}>⚠  {deleteError}</Text>
              </View>
            )}

            <TouchableOpacity style={[s.dangerBtn, deleteLoading&&{ opacity:0.5 }]} onPress={handleDeleteAccount} disabled={deleteLoading} activeOpacity={0.85}>
              {deleteLoading
                ? <ActivityIndicator color={C.red} size="small"/>
                : <Text style={s.dangerBtnText}>🗑️  Permanently Delete My Account</Text>
              }
            </TouchableOpacity>

            <TouchableOpacity style={[s.signOutBtn,{ marginTop:10 }]} onPress={()=>setActiveModal(null)}>
              <Text style={[s.signOutText,{ color:C.text2 }]}>Cancel</Text>
            </TouchableOpacity>
          </ScrollView>
        </View>
      </Modal>

    </ScrollView>
  );
}

const s = StyleSheet.create({
  // AUTH
  authScroll:{ flex:1, backgroundColor:C.bg },
  authContainer:{ padding:24, paddingBottom:50, alignItems:'center' },
  authLogo:{ width:80, height:80, borderRadius:22, backgroundColor:'rgba(124,106,255,0.18)', borderWidth:2, borderColor:C.accent, alignItems:'center', justifyContent:'center', marginTop:40, marginBottom:14 },
  authLogoText:{ fontSize:36, color:C.accent, fontWeight:'800' },
  authTitle:{ fontWeight:'800', fontSize:26, color:C.text, letterSpacing:-0.5, marginBottom:6 },
  authSubtitle:{ color:C.text2, fontSize:14, marginBottom:16 },
  securityBadge:{ backgroundColor:'rgba(74,222,128,0.1)', borderWidth:1, borderColor:'rgba(74,222,128,0.25)', borderRadius:99, paddingHorizontal:14, paddingVertical:6, marginBottom:24 },
  securityBadgeText:{ color:C.green, fontSize:12, fontWeight:'500' },
  authForm:{ width:'100%' },
  inputWrap:{ marginBottom:14 },
  inputLabel:{ color:C.text2, fontSize:12, marginBottom:6, fontWeight:'500' },
  authInput:{ backgroundColor:C.surface2, borderWidth:1, borderColor:C.border, borderRadius:12, padding:14, paddingHorizontal:16, color:C.text, fontSize:14, width:'100%' },
  eyeBtn:{ position:'absolute', right:14, top:14 },
  eyeText:{ fontSize:18 },
  passwordRules:{ backgroundColor:C.surface2, borderRadius:12, padding:14, marginTop:4, marginBottom:8, gap:6 },
  passwordRulesTitle:{ color:C.text2, fontSize:11, fontWeight:'600', marginBottom:4, letterSpacing:0.5, textTransform:'uppercase' },
  passwordRule:{ flexDirection:'row', alignItems:'center' },
  authError:{ backgroundColor:'rgba(255,107,107,0.08)', borderWidth:1, borderColor:'rgba(255,107,107,0.2)', borderRadius:10, padding:12, marginBottom:12 },
  authErrorText:{ color:C.red, fontSize:13 },
  authBtn:{ backgroundColor:C.accent, borderRadius:12, padding:16, alignItems:'center', marginTop:4, shadowColor:C.accent, shadowOpacity:0.4, shadowRadius:12, width:'100%' },
  authBtnText:{ color:'#fff', fontSize:16, fontWeight:'700' },
  switchModeBtn:{ padding:16, alignItems:'center' },
  switchModeTxt:{ color:C.text2, fontSize:14 },
  privacyNote:{ backgroundColor:'rgba(124,106,255,0.06)', borderWidth:1, borderColor:'rgba(124,106,255,0.15)', borderRadius:12, padding:14, marginTop:8, width:'100%' },
  privacyNoteText:{ color:C.text2, fontSize:12, lineHeight:18, textAlign:'center' },
  guestSection:{ width:'100%', alignItems:'center', marginTop:20 },
  guestSectionTitle:{ color:C.text3, fontSize:13, marginBottom:10 },
  guestBtn:{ backgroundColor:C.surface2, borderWidth:1, borderColor:'rgba(251,191,36,0.3)', borderRadius:12, paddingHorizontal:24, paddingVertical:14, width:'100%', alignItems:'center' },
  guestBtnText:{ color:C.gold, fontSize:14, fontWeight:'600' },
  guestWarning:{ color:C.text3, fontSize:11, marginTop:8, textAlign:'center' },

  // PROFILE
  scroll:{ flex:1, backgroundColor:C.bg },
  container:{ padding:16, paddingBottom:40 },
  signUpCTA:{ backgroundColor:'rgba(124,106,255,0.1)', borderWidth:1, borderColor:'rgba(124,106,255,0.3)', borderRadius:14, padding:14, alignItems:'center', marginBottom:16 },
  signUpCTAText:{ color:C.accent, fontSize:13, fontWeight:'600', textAlign:'center' },
  avatarSection:{ alignItems:'center', paddingVertical:20 },
  avatar:{ width:72, height:72, borderRadius:20, backgroundColor:'rgba(124,106,255,0.18)', borderWidth:2, borderColor:C.accent, alignItems:'center', justifyContent:'center', marginBottom:12 },
  avatarText:{ fontSize:28, color:C.accent, fontWeight:'800' },
  userName:{ color:C.text, fontSize:20, fontWeight:'800', marginBottom:2, letterSpacing:-0.5 },
  userEmail:{ color:C.text2, fontSize:13, marginBottom:10 },
  statusBadge:{ flexDirection:'row', alignItems:'center', gap:6, backgroundColor:'rgba(74,222,128,0.1)', borderWidth:1, borderColor:'rgba(74,222,128,0.2)', borderRadius:99, paddingHorizontal:12, paddingVertical:4 },
  statusDot:{ width:6, height:6, borderRadius:3, backgroundColor:C.green },
  statusText:{ color:C.green, fontSize:12 },
  statsGrid:{ flexDirection:'row', gap:10, marginBottom:16 },
  statBox:{ flex:1, backgroundColor:C.surface2, borderRadius:14, padding:12, borderWidth:1, borderColor:C.border, borderBottomWidth:2, alignItems:'center' },
  statVal:{ fontSize:18, fontWeight:'800', letterSpacing:-0.5, marginBottom:4 },
  statLbl:{ color:C.text3, fontSize:9, textTransform:'uppercase', letterSpacing:0.5 },
  menuCard:{ backgroundColor:C.surface, borderRadius:18, borderWidth:1, borderColor:C.border, overflow:'hidden', marginBottom:16, padding:16 },
  menuSection:{ color:C.text3, fontSize:10, fontWeight:'600', letterSpacing:1, textTransform:'uppercase', marginBottom:8 },
  menuItem:{ flexDirection:'row', alignItems:'center', paddingVertical:12, gap:12, borderBottomWidth:1, borderBottomColor:C.border },
  menuIcon:{ width:36, height:36, borderRadius:10, alignItems:'center', justifyContent:'center' },
  menuLabel:{ flex:1, color:C.text, fontSize:14, fontWeight:'500' },
  menuArrow:{ color:C.text3, fontSize:22 },
  signOutBtn:{ backgroundColor:'rgba(255,107,107,0.08)', borderWidth:1, borderColor:'rgba(255,107,107,0.2)', borderRadius:14, padding:16, alignItems:'center', marginBottom:10 },
  signOutText:{ color:C.red, fontSize:15, fontWeight:'600' },
  deleteAccountBtn:{ padding:14, alignItems:'center', marginBottom:16 },
  deleteAccountText:{ color:C.text3, fontSize:13, textDecorationLine:'underline' },
  version:{ color:C.text3, fontSize:11, textAlign:'center', letterSpacing:0.3 },

  // MODALS
  modal:{ flex:1, backgroundColor:C.bg },
  modalHeader:{ flexDirection:'row', alignItems:'center', justifyContent:'space-between', padding:20, borderBottomWidth:1, borderBottomColor:C.border, backgroundColor:C.surface },
  modalTitle:{ color:C.text, fontSize:17, fontWeight:'700' },
  modalClose:{ backgroundColor:C.surface2, borderWidth:1, borderColor:C.border, borderRadius:99, width:32, height:32, alignItems:'center', justifyContent:'center' },
  modalCloseTxt:{ color:C.text2, fontSize:15 },
  modalBody:{ padding:20, paddingBottom:40 },
  settingDesc:{ color:C.text2, fontSize:13, lineHeight:18, marginBottom:20 },
  settingSection:{ color:C.text3, fontSize:10, fontWeight:'600', letterSpacing:1, textTransform:'uppercase', marginBottom:12 },
  infoRow:{ flexDirection:'row', justifyContent:'space-between', alignItems:'center', paddingVertical:14, borderBottomWidth:1, borderBottomColor:C.border },
  infoLabel:{ color:C.text2, fontSize:14 },
  infoValue:{ color:C.text, fontSize:14, fontWeight:'500', maxWidth:'60%', textAlign:'right' },
  privacyLink:{ flexDirection:'row', alignItems:'center', justifyContent:'space-between', paddingVertical:14, borderBottomWidth:1, borderBottomColor:C.border },
  privacyLinkText:{ color:C.text, fontSize:14, fontWeight:'500' },
  themeRow:{ flexDirection:'row', alignItems:'center', paddingVertical:12, borderBottomWidth:1, borderBottomColor:C.border, gap:12 },
  themeColor:{ width:28, height:28, borderRadius:8 },
  themeLabel:{ flex:1, color:C.text, fontSize:14 },
  themeActive:{ fontSize:12, fontWeight:'600' },
  deleteWarning:{ backgroundColor:'rgba(255,107,107,0.07)', borderWidth:1, borderColor:'rgba(255,107,107,0.2)', borderRadius:14, padding:16, marginBottom:20 },
  deleteWarningTitle:{ color:C.red, fontSize:15, fontWeight:'700', marginBottom:8 },
  deleteWarningText:{ color:C.text2, fontSize:13 },
  dangerBtn:{ padding:16, backgroundColor:'rgba(255,107,107,0.1)', borderWidth:1, borderColor:'rgba(255,107,107,0.3)', borderRadius:12, alignItems:'center', marginTop:16 },
  dangerBtnText:{ color:C.red, fontSize:14, fontWeight:'600' },
});
