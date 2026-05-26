import { useState, useEffect } from 'react';
import { useAuth, clearUser, saveUser, getUserToken } from '../../stores/authStore';
import { useTheme } from '../../stores/themeStore';
import {
  View, Text, ScrollView, TouchableOpacity, StyleSheet,
  ActivityIndicator, TextInput, Alert, Modal, Switch,
  Linking, Share,
} from 'react-native';
import { Ionicons } from '@expo/vector-icons';

const API = 'https://web-production-3605f4.up.railway.app';

const FALLBACK_COLORS = {
  bg:'#070810', surface:'#10111d', surface2:'#17182b', surface3:'#22233a', card:'#121423',
  border:'rgba(237,232,255,0.09)',
  accent:'#806fff', accent2:'#ff6aa6', accent3:'#62f2d0',
  text:'#f2eeff', text2:'#a8a3c0', text3:'#696481',
  green:'#4ade80', red:'#ff6b7d', gold:'#f6c453',
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
          <View key={i} style={{ flex:1, height:3, borderRadius:2, backgroundColor: i < strength ? colors[strength] : FALLBACK_COLORS.surface3 }} />
        ))}
      </View>
      {strength < 4
        ? <Text style={{ fontSize:11, color:FALLBACK_COLORS.text3 }}>Missing: {errors.join('  ')}</Text>
        : <Text style={{ fontSize:11, color:FALLBACK_COLORS.green }}> Strong password</Text>
      }
    </View>
  );
}

const n = (v:any) => parseFloat(v)||0;

export default function ProfileScreen() {
  const { theme, colors: C, setTheme } = useTheme();
  const s = createStyles(C);
  const { user } = useAuth();
  const [email, setEmail]       = useState('');
  const [password, setPassword] = useState('');
  const [name, setName]         = useState('');
  const [showPassword, setShowPassword] = useState(false);
  const [authLoading, setAuthLoading]   = useState(false);
  const [authError, setAuthError]       = useState('');
  const [authMode, setAuthMode] = useState<'login'|'signup'>('login');

  const [stats, setStats]             = useState({ receipts:0, spent:0, saved:0, stores:0 });
  const [statsLoading, setStatsLoading] = useState(true);
  const [activeModal, setActiveModal]   = useState<string|null>(null);

  const [deleteEmail, setDeleteEmail]       = useState('');
  const [deletePassword, setDeletePassword] = useState('');
  const [deleteLoading, setDeleteLoading]   = useState(false);
  const [deleteError, setDeleteError]       = useState('');

  // Notification toggles
  const [notifReceipts, setNotifReceipts] = useState(true);
  const [notifSavings, setNotifSavings]   = useState(true);
  const [notifDeals, setNotifDeals]       = useState(false);

  // Rating
  const [rating, setRating]         = useState(0);
  const [showRating, setShowRating] = useState(false);

  // Updates
  const [updateLoading, setUpdateLoading]     = useState(false);
  const [updateAvailable, setUpdateAvailable] = useState(false);

  useEffect(() => { if (user) loadStats(); }, [user]);

  async function loadStats() {
    setStatsLoading(true);
    try {
      const headers: any = { 'Content-Type':'application/json' };
      if (user?.token) headers['Authorization'] = `Bearer ${user.token}`;
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

      //  Save token globally for scan screen
      

      await saveUser({
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
      {
        text:'Sign Out',
        style:'destructive',
        onPress: async () => {
          await clearUser();
          setEmail('');
          setPassword('');
          setName('');
          setStats({ receipts:0, spent:0, saved:0, stores:0 });
        }
      },
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
        { text:'OK', onPress: async () => { await clearUser(); } }
      ]);
    } catch { setDeleteError('Could not connect. Please try again.'); }
    finally  { setDeleteLoading(false); }
  }

  async function checkForUpdates() {
    setUpdateLoading(true);
    try {
      // Try expo-updates if available
      const Updates = require('expo-updates');
      const update = await Updates.checkForUpdateAsync();
      if (update.isAvailable) {
        setUpdateAvailable(true);
        Alert.alert('Update Available', 'Install the latest version now?', [
          { text:'Later', style:'cancel' },
          { text:'Update Now', onPress: async () => {
            await Updates.fetchUpdateAsync();
            await Updates.reloadAsync();
          }}
        ]);
      } else {
        Alert.alert(' Up to date', 'You have the latest version of ReceiptAI!');
      }
    } catch {
      Alert.alert(' Up to date', 'You have the latest version of ReceiptAI!');
    } finally {
      setUpdateLoading(false);
    }
  }

  async function handleShare() {
    try {
      await Share.share({ message:' Check out ReceiptAI  scan receipts, track prices, and save money on groceries!', title:'ReceiptAI' });
    } catch {}
  }

  function handleHelpSupport() {
    Alert.alert('Help & Support', 'How can we help?', [
      { text:'Cancel', style:'cancel' },
      { text:' Email Support', onPress:() => Linking.openURL('mailto:support@receiptai.app') },
    ]);
  }

  const isGuest = user?.is_guest === true || user?.id === 'guest' || user?.token === 'guest';
  const profileName = user?.name || user?.email?.split('@')[0] || 'User';
  const profileEmail = user?.email || '';

  // PROFILE SCREEN
  return (
    <ScrollView style={s.scroll} contentContainerStyle={s.container} showsVerticalScrollIndicator={false}>

      {/* Avatar */}
      <View style={s.avatarSection}>
        <View style={s.avatar}>
          <Text style={s.avatarText}>{isGuest ? 'G' : profileName[0]?.toUpperCase() || 'A'}</Text>
        </View>
        <Text style={s.userName}>{isGuest ? 'Guest User' : profileName}</Text>
        <Text style={s.userEmail}>{isGuest ? 'Guest Mode' : profileEmail}</Text>
        {isGuest && (
          <TouchableOpacity style={s.upgradeBtn} onPress={ async ()=>{ await clearUser(); }}>
            <Text style={s.upgradeBtnText}>Create account for full access</Text>
          </TouchableOpacity>
        )}
        <View style={s.statusBadge}>
          <View style={s.statusDot}/>
          <Text style={s.statusText}>{isGuest ? 'Guest Mode' : 'Verified Account'}</Text>
        </View>
      </View>

      <View style={s.profileInsightCard}>
        <View style={s.profileInsightTop}>
          <Text style={s.profileInsightKicker}>Your ReceiptAI profile</Text>
          <View style={s.profileInsightBadge}>
            <Text style={s.profileInsightBadgeText}>{isGuest ? 'Trial' : 'Private'}</Text>
          </View>
        </View>
        <Text style={s.profileInsightTitle}>
          {isGuest ? 'Guest trial active' : 'Account ready'}
        </Text>
        <Text style={s.profileInsightText}>
          Manage privacy, appearance, notifications, and account settings.
        </Text>
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
        <TouchableOpacity style={s.menuItem} onPress={()=>setActiveModal('notifications')}>
          <View style={[s.menuIcon,{ backgroundColor:C.accent+'22' }]}><Ionicons name="notifications-outline" size={18} color={C.accent} /></View>
          <Text style={s.menuLabel}>Notifications</Text>
          <Text style={s.menuArrow}>{'>'}</Text>
        </TouchableOpacity>

        <Text style={[s.menuSection,{ marginTop:16 }]}>Privacy</Text>
        <TouchableOpacity style={s.menuItem} onPress={()=>setActiveModal('privacy')} disabled={isGuest}>
          <View style={[s.menuIcon,{ backgroundColor:C.accent2+'22' }]}><Ionicons name="shield-checkmark-outline" size={18} color={C.accent2} /></View>
          <Text style={[s.menuLabel, isGuest&&{color:C.text3}]}>Privacy & Security</Text>
          <Text style={s.menuArrow}>{isGuest ? 'Locked' : '>'}</Text>
        </TouchableOpacity>

        <Text style={[s.menuSection,{ marginTop:16 }]}>Preferences</Text>
        <TouchableOpacity style={s.menuItem} onPress={()=>setActiveModal('appearance')}>
          <View style={[s.menuIcon,{ backgroundColor:C.accent3+'22' }]}><Ionicons name="color-palette-outline" size={18} color={C.accent3} /></View>
          <Text style={s.menuLabel}>Appearance</Text>
          <Text style={s.menuArrow}>{'>'}</Text>
        </TouchableOpacity>

        <Text style={[s.menuSection,{ marginTop:16 }]}>Support</Text>
        <TouchableOpacity style={s.menuItem} onPress={handleHelpSupport}>
          <View style={[s.menuIcon,{ backgroundColor:C.gold+'22' }]}><Ionicons name="help-circle-outline" size={18} color={C.gold} /></View>
          <Text style={s.menuLabel}>Help & Support</Text>
          <Text style={s.menuArrow}>{'>'}</Text>
        </TouchableOpacity>

        <TouchableOpacity style={s.menuItem} onPress={()=>{ setRating(0); setShowRating(true); }}>
          <View style={[s.menuIcon,{ backgroundColor:C.green+'22' }]}><Ionicons name="star-outline" size={18} color={C.green} /></View>
          <Text style={s.menuLabel}>Rate ReceiptAI</Text>
          <Text style={s.menuArrow}>{'>'}</Text>
        </TouchableOpacity>

        <TouchableOpacity style={s.menuItem} onPress={handleShare}>
          <View style={[s.menuIcon,{ backgroundColor:C.text2+'22' }]}><Ionicons name="share-outline" size={18} color={C.text2} /></View>
          <Text style={s.menuLabel}>Share App</Text>
          <Text style={s.menuArrow}>{'>'}</Text>
        </TouchableOpacity>

        <TouchableOpacity style={[s.menuItem,{borderBottomWidth:0}]} onPress={checkForUpdates} disabled={updateLoading}>
          <View style={[s.menuIcon,{ backgroundColor:'rgba(74,222,128,0.18)' }]}>
            <Ionicons name={updateAvailable ? 'cloud-download-outline' : 'checkmark-circle-outline'} size={18} color={C.green} />
          </View>
          <Text style={[s.menuLabel, updateAvailable&&{color:C.green}]}>
            {updateLoading?'Checking...':updateAvailable?'Update Available!':'Check for Updates'}
          </Text>
          {updateLoading
            ? <ActivityIndicator size="small" color={C.accent}/>
            : <Text style={s.menuArrow}>{'>'}</Text>
          }
        </TouchableOpacity>
      </View>

      {isGuest ? (
        <TouchableOpacity style={s.authBtn} onPress={ async ()=>{ await clearUser(); }} activeOpacity={0.85}>
          <Text style={s.authBtnText}>Create Free Account</Text>
        </TouchableOpacity>
      ) : (
        <TouchableOpacity style={s.signOutBtn} onPress={handleSignOut}>
          <Text style={s.signOutText}>Sign Out</Text>
        </TouchableOpacity>
      )}

      {!isGuest && (
        <TouchableOpacity style={s.deleteAccountBtn} onPress={()=>{ setActiveModal('deleteAccount'); setDeleteEmail(''); setDeletePassword(''); setDeleteError(''); }}>
          <Text style={s.deleteAccountText}>Delete My Account</Text>
        </TouchableOpacity>
      )}

      <Text style={s.version}>ReceiptAI v1.0 | Private by default</Text>

      {/*  RATING MODAL  */}
      <Modal visible={showRating} animationType="fade" transparent onRequestClose={()=>setShowRating(false)}>
        <View style={{ flex:1, backgroundColor:'rgba(0,0,0,0.75)', alignItems:'center', justifyContent:'center', padding:24 }}>
          <View style={{ backgroundColor:C.surface, borderRadius:24, padding:28, width:'100%', alignItems:'center', borderWidth:1, borderColor:C.border }}>
            <Text style={{ fontSize:22, fontWeight:'800', color:C.text, marginBottom:6 }}>Rate ReceiptAI</Text>
            <Text style={{ fontSize:13, color:C.text2, marginBottom:24, textAlign:'center' }}>How would you rate your experience?</Text>

            {/* 5 Stars */}
            <View style={{ flexDirection:'row', gap:10, marginBottom:16 }}>
              {[1,2,3,4,5].map(star => (
                <TouchableOpacity key={star} onPress={()=>setRating(star)} activeOpacity={0.7}>
                  <Ionicons name={star <= rating ? 'star' : 'star-outline'} size={38} color={C.gold} style={{ opacity: star <= rating ? 1 : 0.35 }} />
                </TouchableOpacity>
              ))}
            </View>

            {/* Rating label */}
            <Text style={{ fontSize:14, color:C.accent, fontWeight:'600', marginBottom:24, minHeight:20 }}>
              {rating===1?'Poor':rating===2?'Fair':rating===3?'Good':rating===4?'Great':rating===5?'Excellent':'Tap a star to rate'}
            </Text>

            {/* Buttons */}
            <View style={{ flexDirection:'row', gap:12, width:'100%' }}>
              <TouchableOpacity
                style={{ flex:1, padding:14, borderRadius:12, alignItems:'center', backgroundColor:C.surface2, borderWidth:1, borderColor:C.border }}
                onPress={()=>setShowRating(false)}
              >
                <Text style={{ color:C.text2, fontWeight:'600' }}>Cancel</Text>
              </TouchableOpacity>
              <TouchableOpacity
                style={{ flex:1, padding:14, borderRadius:12, alignItems:'center', backgroundColor: rating>0 ? C.accent : C.surface3, opacity: rating>0?1:0.5 }}
                onPress={()=>{
                  if(rating===0) return;
                  setShowRating(false);
                  setTimeout(()=>{
                    Alert.alert(
                      'Thank you',
                      rating>=4 ? 'We love building ReceiptAI for you!' : 'We appreciate your feedback and will keep improving!'
                    );
                  }, 300);
                }}
                disabled={rating===0}
              >
                <Text style={{ color:'#fff', fontWeight:'700' }}>Submit</Text>
              </TouchableOpacity>
            </View>
          </View>
        </View>
      </Modal>

      {/*  NOTIFICATIONS MODAL  */}
      <Modal visible={activeModal==='notifications'} animationType="slide" presentationStyle="pageSheet" onRequestClose={()=>setActiveModal(null)}>
        <View style={s.modal}>
          <View style={s.modalHeader}>
            <Text style={s.modalTitle}>  Notifications</Text>
            <TouchableOpacity onPress={()=>setActiveModal(null)} style={s.modalClose}><Text style={s.modalCloseTxt}></Text></TouchableOpacity>
          </View>
          <ScrollView contentContainerStyle={s.modalBody}>
            <Text style={s.settingSection}>Push Notifications</Text>

            <View style={s.settingRow}>
              <View style={{flex:1}}>
                <Text style={s.settingLabel}>Receipt Scanned</Text>
                <Text style={s.settingHint}>Get notified when a receipt is saved</Text>
              </View>
              <Switch
                value={notifReceipts}
                onValueChange={async (val) => {
                  setNotifReceipts(val);
                  if (val) {
                    try {
                      const Notifications = require('expo-notifications');
                      const { status } = await Notifications.requestPermissionsAsync();
                      if (status !== 'granted') {
                        Alert.alert('Permission Required', 'Please enable notifications in your device settings.');
                        setNotifReceipts(false);
                      }
                    } catch { setNotifReceipts(val); }
                  }
                }}
                trackColor={{false:C.surface3, true:C.accent}}
                thumbColor="#fff"
              />
            </View>

            <View style={s.settingRow}>
              <View style={{flex:1}}>
                <Text style={s.settingLabel}>Savings Alerts</Text>
                <Text style={s.settingHint}>Get notified when you save money</Text>
              </View>
              <Switch
                value={notifSavings}
                onValueChange={async (val) => {
                  setNotifSavings(val);
                  if (val) {
                    try {
                      const Notifications = require('expo-notifications');
                      const { status } = await Notifications.requestPermissionsAsync();
                      if (status !== 'granted') {
                        Alert.alert('Permission Required', 'Please enable notifications in your device settings.');
                        setNotifSavings(false);
                      }
                    } catch { setNotifSavings(val); }
                  }
                }}
                trackColor={{false:C.surface3, true:C.accent}}
                thumbColor="#fff"
              />
            </View>

            <View style={[s.settingRow,{borderBottomWidth:0}]}>
              <View style={{flex:1}}>
                <Text style={s.settingLabel}>Price Drop Alerts</Text>
                <Text style={s.settingHint}>Get notified when tracked items drop in price</Text>
              </View>
              <Switch
                value={notifDeals}
                onValueChange={async (val) => {
                  setNotifDeals(val);
                  if (val) {
                    try {
                      const Notifications = require('expo-notifications');
                      const { status } = await Notifications.requestPermissionsAsync();
                      if (status !== 'granted') {
                        Alert.alert('Permission Required', 'Please enable notifications in your device settings.');
                        setNotifDeals(false);
                      }
                    } catch { setNotifDeals(val); }
                  }
                }}
                trackColor={{false:C.surface3, true:C.accent}}
                thumbColor="#fff"
              />
            </View>
          </ScrollView>
        </View>
      </Modal>

      {/*  PRIVACY MODAL  */}
      <Modal visible={activeModal==='privacy'} animationType="slide" presentationStyle="pageSheet" onRequestClose={()=>setActiveModal(null)}>
        <View style={s.modal}>
          <View style={s.modalHeader}>
            <Text style={s.modalTitle}>  Privacy & Security</Text>
            <TouchableOpacity onPress={()=>setActiveModal(null)} style={s.modalClose}><Text style={s.modalCloseTxt}></Text></TouchableOpacity>
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
                {user?.created_at ? new Date(user.created_at).toLocaleDateString('en-US',{ month:'long', year:'numeric' }) : ''}
              </Text>
            </View>
            <View style={[s.infoRow,{ borderBottomWidth:0 }]}>
              <Text style={s.infoLabel}>Account status</Text>
              <Text style={[s.infoValue,{ color:C.green }]}> Active</Text>
            </View>

            <Text style={[s.settingSection,{ marginTop:24 }]}>Your Data</Text>
            <TouchableOpacity style={s.privacyLink} onPress={()=>Alert.alert('Privacy Policy','All your receipts are private and only accessible by you. We never share or sell your personal data.')}>
              <Text style={s.privacyLinkText}>Data Privacy Policy</Text>
              <Text style={s.menuArrow}></Text>
            </TouchableOpacity>
            <TouchableOpacity style={s.privacyLink} onPress={()=>Alert.alert('Export Data','Data export feature coming soon!')}>
              <Text style={s.privacyLinkText}>Export My Data</Text>
              <Text style={s.menuArrow}></Text>
            </TouchableOpacity>
            <TouchableOpacity style={[s.privacyLink,{ borderBottomWidth:0 }]} onPress={()=>{ setActiveModal('deleteAccount'); setDeleteEmail(''); setDeletePassword(''); setDeleteError(''); }}>
              <Text style={[s.privacyLinkText,{ color:C.red }]}>Delete My Account</Text>
              <Text style={s.menuArrow}></Text>
            </TouchableOpacity>
          </ScrollView>
        </View>
      </Modal>

      {/*  APPEARANCE MODAL  */}
      <Modal visible={activeModal==='appearance'} animationType="slide" presentationStyle="pageSheet" onRequestClose={()=>setActiveModal(null)}>
        <View style={s.modal}>
          <View style={s.modalHeader}>
            <Text style={s.modalTitle}>  Appearance</Text>
            <TouchableOpacity onPress={()=>setActiveModal(null)} style={s.modalClose}><Text style={s.modalCloseTxt}></Text></TouchableOpacity>
          </View>
          <ScrollView contentContainerStyle={s.modalBody}>
            <Text style={s.settingSection}>Theme Mode</Text>
            <Text style={[s.settingHint,{marginBottom:16}]}>Choose how ReceiptAI looks on your device.</Text>

            <View style={{ flexDirection:'row', gap:12 }}>
              {[
                { label:'Dark', icon:'moon-outline' as const, value:'dark' as const },
                { label:'Light', icon:'sunny-outline' as const, value:'light' as const },
              ].map((t) => (
                <TouchableOpacity
                  key={t.value}
                  style={{
                    flex:1, padding:20, borderRadius:16, alignItems:'center',
                    borderWidth: theme===t.value ? 2 : 1,
                    borderColor: theme===t.value ? C.accent : C.border,
                    backgroundColor: theme===t.value ? 'rgba(124,106,255,0.15)' : C.surface2,
                  }}
                  onPress={() => setTheme(t.value)}
                  activeOpacity={0.8}
                >
                  <Ionicons name={t.icon} size={30} color={theme===t.value ? C.accent : C.text2} style={{ marginBottom:8 }} />
                  <Text style={{ color: theme===t.value ? C.accent : C.text2, fontWeight:'700', fontSize:14 }}>
                    {t.label}
                  </Text>
                  {theme===t.value && (
                    <View style={{ marginTop:6, backgroundColor:C.accent, borderRadius:99, paddingHorizontal:10, paddingVertical:2 }}>
                      <Text style={{ color:'#fff', fontSize:10, fontWeight:'600' }}>Active</Text>
                    </View>
                  )}
                </TouchableOpacity>
              ))}
            </View>
          </ScrollView>
        </View>
      </Modal>

      {/*  DELETE ACCOUNT MODAL  */}
      <Modal visible={activeModal==='deleteAccount'} animationType="slide" presentationStyle="pageSheet" onRequestClose={()=>setActiveModal(null)}>
        <View style={s.modal}>
          <View style={s.modalHeader}>
            <Text style={s.modalTitle}>  Delete Account</Text>
            <TouchableOpacity onPress={()=>setActiveModal(null)} style={s.modalClose}><Text style={s.modalCloseTxt}></Text></TouchableOpacity>
          </View>
          <ScrollView contentContainerStyle={s.modalBody}>
            <View style={s.deleteWarning}>
              <Text style={s.deleteWarningTitle}>  This cannot be undone</Text>
              <Text style={s.deleteWarningText}>Deleting your account will permanently remove:</Text>
              <View style={{ gap:6, marginTop:8 }}>
                {['All your scanned receipts','All your purchase history','All your saved data','Your account and login'].map((item,i) => (
                  <View key={i} style={{ flexDirection:'row', gap:8, alignItems:'center' }}>
                    <Text style={{ color:C.red, fontSize:13 }}></Text>
                    <Text style={{ color:C.text2, fontSize:13 }}>{item}</Text>
                  </View>
                ))}
              </View>
            </View>

            <Text style={s.settingHint}>To confirm, enter your account credentials:</Text>

            <View style={[s.inputWrap,{marginTop:16}]}>
              <Text style={s.inputLabel}>Your Email</Text>
              <TextInput style={s.authInput} placeholder={user?.email} placeholderTextColor={C.text3} value={deleteEmail} onChangeText={setDeleteEmail} keyboardType="email-address" autoCapitalize="none"/>
            </View>
            <View style={s.inputWrap}>
              <Text style={s.inputLabel}>Your Password</Text>
              <TextInput style={s.authInput} placeholder="Enter your password" placeholderTextColor={C.text3} value={deletePassword} onChangeText={setDeletePassword} secureTextEntry/>
            </View>

            {deleteError!=='' && (
              <View style={s.authError}>
                <Text style={s.authErrorText}>  {deleteError}</Text>
              </View>
            )}

            <TouchableOpacity style={[s.dangerBtn, deleteLoading&&{ opacity:0.5 }]} onPress={handleDeleteAccount} disabled={deleteLoading} activeOpacity={0.85}>
              {deleteLoading
                ? <ActivityIndicator color={C.red} size="small"/>
                : <Text style={s.dangerBtnText}>  Permanently Delete My Account</Text>
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

const createStyles = (C: typeof FALLBACK_COLORS) => StyleSheet.create({
  // AUTH
  authScroll:{ flex:1, backgroundColor:C.bg },
  authContainer:{ padding:24, paddingBottom:50, alignItems:'center' },
  authLogo:{ width:80, height:80, borderRadius:22, backgroundColor:'rgba(124,106,255,0.18)', borderWidth:2, borderColor:C.accent, alignItems:'center', justifyContent:'center', marginTop:40, marginBottom:14 },
  authLogoText:{ fontSize:36, color:C.accent, fontWeight:'800' },
  authTitle:{ fontWeight:'900', fontSize:26, color:C.text, letterSpacing:0, marginBottom:6 },
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
  avatarSection:{ alignItems:'center', paddingVertical:20 },
  avatar:{ width:72, height:72, borderRadius:18, backgroundColor:'rgba(128,111,255,0.18)', borderWidth:1, borderColor:'rgba(128,111,255,0.55)', alignItems:'center', justifyContent:'center', marginBottom:12 },
  avatarText:{ fontSize:28, color:C.accent, fontWeight:'800' },
  userName:{ color:C.text, fontSize:20, fontWeight:'900', marginBottom:2, letterSpacing:0 },
  userEmail:{ color:C.text2, fontSize:13, marginBottom:10 },
  upgradeBtn:{ backgroundColor:'rgba(124,106,255,0.1)', borderWidth:1, borderColor:'rgba(124,106,255,0.3)', borderRadius:99, paddingHorizontal:16, paddingVertical:6, marginBottom:10 },
  upgradeBtnText:{ color:C.accent, fontSize:12, fontWeight:'600' },
  statusBadge:{ flexDirection:'row', alignItems:'center', gap:6, backgroundColor:'rgba(74,222,128,0.1)', borderWidth:1, borderColor:'rgba(74,222,128,0.2)', borderRadius:99, paddingHorizontal:12, paddingVertical:4 },
  statusDot:{ width:6, height:6, borderRadius:3, backgroundColor:C.green },
  statusText:{ color:C.green, fontSize:12 },
  profileInsightCard:{ backgroundColor:C.card, borderRadius:14, borderWidth:1, borderColor:C.border, padding:16, marginBottom:16 },
  profileInsightTop:{ flexDirection:'row', alignItems:'center', justifyContent:'space-between', gap:10, marginBottom:10 },
  profileInsightKicker:{ color:C.accent3, fontSize:10, fontWeight:'900', textTransform:'uppercase', letterSpacing:0.8 },
  profileInsightBadge:{ backgroundColor:'rgba(74,222,128,0.10)', borderWidth:1, borderColor:'rgba(74,222,128,0.24)', borderRadius:99, paddingHorizontal:10, paddingVertical:4 },
  profileInsightBadgeText:{ color:C.green, fontSize:10, fontWeight:'900' },
  profileInsightTitle:{ color:C.text, fontSize:19, lineHeight:24, fontWeight:'900', letterSpacing:0, marginBottom:7 },
  profileInsightText:{ color:C.text2, fontSize:13, lineHeight:20 },
  statsGrid:{ flexDirection:'row', gap:10, marginBottom:16 },
  statBox:{ flex:1, backgroundColor:C.surface2, borderRadius:12, padding:12, borderWidth:1, borderColor:C.border, borderBottomWidth:2, alignItems:'center' },
  statVal:{ fontSize:18, fontWeight:'900', letterSpacing:0, marginBottom:4 },
  statLbl:{ color:C.text3, fontSize:9, textTransform:'uppercase', letterSpacing:0.5 },
  menuCard:{ backgroundColor:C.card, borderRadius:14, borderWidth:1, borderColor:C.border, overflow:'hidden', marginBottom:16, padding:16 },
  menuSection:{ color:C.text3, fontSize:10, fontWeight:'600', letterSpacing:1, textTransform:'uppercase', marginBottom:8 },
  menuItem:{ flexDirection:'row', alignItems:'center', paddingVertical:12, gap:12, borderBottomWidth:1, borderBottomColor:C.border },
  menuIcon:{ width:36, height:36, borderRadius:9, alignItems:'center', justifyContent:'center' },
  menuLabel:{ flex:1, color:C.text, fontSize:14, fontWeight:'500' },
  menuArrow:{ color:C.text3, fontSize:22 },
  signOutBtn:{ backgroundColor:'rgba(255,107,125,0.08)', borderWidth:1, borderColor:'rgba(255,107,125,0.22)', borderRadius:12, padding:16, alignItems:'center', marginBottom:10 },
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
  settingSection:{ color:C.text3, fontSize:10, fontWeight:'600', letterSpacing:1, textTransform:'uppercase', marginBottom:12 },
  settingRow:{ flexDirection:'row', alignItems:'center', paddingVertical:14, borderBottomWidth:1, borderBottomColor:C.border, gap:12 },
  settingLabel:{ color:C.text, fontSize:14, fontWeight:'500', marginBottom:3 },
  settingHint:{ color:C.text3, fontSize:12 },
  infoRow:{ flexDirection:'row', justifyContent:'space-between', alignItems:'center', paddingVertical:14, borderBottomWidth:1, borderBottomColor:C.border },
  infoLabel:{ color:C.text2, fontSize:14 },
  infoValue:{ color:C.text, fontSize:14, fontWeight:'500', maxWidth:'60%', textAlign:'right' },
  privacyLink:{ flexDirection:'row', alignItems:'center', justifyContent:'space-between', paddingVertical:14, borderBottomWidth:1, borderBottomColor:C.border },
  privacyLinkText:{ color:C.text, fontSize:14, fontWeight:'500' },
  deleteWarning:{ backgroundColor:'rgba(255,107,107,0.07)', borderWidth:1, borderColor:'rgba(255,107,107,0.2)', borderRadius:14, padding:16, marginBottom:20 },
  deleteWarningTitle:{ color:C.red, fontSize:15, fontWeight:'700', marginBottom:8 },
  deleteWarningText:{ color:C.text2, fontSize:13 },
  dangerBtn:{ padding:16, backgroundColor:'rgba(255,107,107,0.1)', borderWidth:1, borderColor:'rgba(255,107,107,0.3)', borderRadius:12, alignItems:'center', marginTop:16 },
  dangerBtnText:{ color:C.red, fontSize:14, fontWeight:'600' },
});
