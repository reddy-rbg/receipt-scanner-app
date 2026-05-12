import { create } from 'zustand';
import AsyncStorage from '@react-native-async-storage/async-storage';

export interface User { id: string; email?: string; name?: string; token?: string; isGuest?: boolean; is_guest?: boolean; guest_session_id?: string; guestStartTime?: number; created_at?: string; expires_at?: string; }
interface AuthState { user: User | null; isLoggedIn: boolean; isGuest: boolean; setUser: (user: User | null) => Promise<void>; saveUser: (user: User | null) => Promise<void>; loadUser: () => Promise<void>; clearUser: () => Promise<void>; startGuestSession: () => Promise<User>; }
function normalizeUser(user: User): User { const guest = user.isGuest === true || user.is_guest === true || user.token === 'guest'; return { ...user, isGuest: guest, is_guest: guest, guest_session_id: guest ? (user.guest_session_id || user.id) : user.guest_session_id }; }
function createGuestUser(): User { const guestId = `guest_${Date.now()}_${Math.random().toString(36).slice(2, 10)}`; return { id: guestId, email: 'guest@receiptai.local', name: 'Guest', token: 'guest', isGuest: true, is_guest: true, guest_session_id: guestId, guestStartTime: Date.now(), created_at: new Date().toISOString(), expires_at: new Date(Date.now() + 24 * 60 * 60 * 1000).toISOString() }; }
function flags(user: User | null) { const guest = !!(user?.isGuest || user?.is_guest || user?.token === 'guest'); return { user, isLoggedIn: !!user, isGuest: guest }; }
export const useAuth = create<AuthState>((set) => ({ user: null, isLoggedIn: false, isGuest: false, setUser: async (user) => { const u = user ? normalizeUser(user) : null; if (u) await AsyncStorage.setItem('auth_user', JSON.stringify(u)); else { await AsyncStorage.removeItem('auth_user'); await AsyncStorage.removeItem('cached_receipts'); await AsyncStorage.removeItem('user_token'); } set(flags(u)); }, saveUser: async (user) => { const u = user ? normalizeUser(user) : null; if (u) await AsyncStorage.setItem('auth_user', JSON.stringify(u)); else { await AsyncStorage.removeItem('auth_user'); await AsyncStorage.removeItem('cached_receipts'); await AsyncStorage.removeItem('user_token'); } set(flags(u)); }, loadUser: async () => { await AsyncStorage.removeItem('auth_user').catch(()=>{}); await AsyncStorage.removeItem('cached_receipts').catch(()=>{}); await AsyncStorage.removeItem('user_token').catch(()=>{}); set(flags(null)); }, clearUser: async () => { await AsyncStorage.removeItem('auth_user'); await AsyncStorage.removeItem('cached_receipts'); await AsyncStorage.removeItem('user_token'); set(flags(null)); }, startGuestSession: async () => { const guestUser = createGuestUser(); await AsyncStorage.removeItem('cached_receipts'); await AsyncStorage.setItem('auth_user', JSON.stringify(guestUser)); set(flags(guestUser)); return guestUser; } }));
export const loadUser = async () => useAuth.getState().loadUser();
export const saveUser = async (user: User | null) => useAuth.getState().saveUser(user);
export const setUser = async (user: User | null) => useAuth.getState().setUser(user);
export const clearUser = async () => useAuth.getState().clearUser();
export const startGuestSession = async () => useAuth.getState().startGuestSession();
export const getUser = () => useAuth.getState().user;
export const getUserToken = () => useAuth.getState().user?.token || '';
export const getGuestSessionId = () => { const user = useAuth.getState().user; if (!user) return ''; if (user.isGuest || user.is_guest || user.token === 'guest') return user.guest_session_id || user.id; return ''; };
export default useAuth;
