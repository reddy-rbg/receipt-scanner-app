import AsyncStorage from '@react-native-async-storage/async-storage';
import * as SecureStore from 'expo-secure-store';
import { create } from 'zustand';

import { API } from '../config/api';

export interface User {
  id: string;
  email?: string;
  name?: string;
  token?: string;
  refresh_token?: string;
  isGuest?: boolean;
  is_guest?: boolean;
  guest_session_id?: string;
  guestStartTime?: number;
  created_at?: string;
  expires_at?: string;
}

interface AuthState {
  user: User | null;
  isLoggedIn: boolean;
  isGuest: boolean;
  setUser: (user: User | null) => Promise<void>;
  saveUser: (user: User | null) => Promise<void>;
  loadUser: () => Promise<void>;
  clearUser: () => Promise<void>;
  startGuestSession: () => Promise<User>;
}

const AUTH_KEY = 'auth_user';
const RECEIPTS_CACHE_PREFIX = 'receiptai:receipts-cache:v1';
const SHOP_LIST_PREFIX = 'receiptai:shop-list:v1';
const AGENT_SESSION_PREFIX = 'receiptai:agent-session';
const ACCESS_TOKEN_KEY = 'receiptai_access_token';
const REFRESH_TOKEN_KEY = 'receiptai_refresh_token';

function normalizeUser(user: User): User {
  const guest = user.isGuest === true || user.is_guest === true || user.token === 'guest';
  return {
    ...user,
    isGuest: guest,
    is_guest: guest,
    guest_session_id: guest ? (user.guest_session_id || user.id) : undefined,
  };
}

function createGuestUser(): User {
  const guestId = `guest_${Date.now()}_${Math.random().toString(36).slice(2, 10)}`;
  return {
    id: guestId,
    email: 'guest@receiptai.local',
    name: 'Guest',
    token: 'guest',
    isGuest: true,
    is_guest: true,
    guest_session_id: guestId,
    guestStartTime: Date.now(),
    created_at: new Date().toISOString(),
    expires_at: new Date(Date.now() + 24 * 60 * 60 * 1000).toISOString(),
  };
}

function flags(user: User | null) {
  const guest = !!(user?.isGuest || user?.is_guest || user?.token === 'guest');
  return { user, isLoggedIn: !!user, isGuest: guest };
}

async function clearStoredAuth(userId?: string) {
  const keys = [AUTH_KEY, 'cached_receipts', 'user_token'];
  if (userId) {
    keys.push(
      `${RECEIPTS_CACHE_PREFIX}:${userId}`,
      `${SHOP_LIST_PREFIX}:${userId}`,
      `${AGENT_SESSION_PREFIX}:${userId}`,
    );
  }
  await AsyncStorage.multiRemove(keys);
  await Promise.all([
    SecureStore.deleteItemAsync(ACCESS_TOKEN_KEY).catch(() => {}),
    SecureStore.deleteItemAsync(REFRESH_TOKEN_KEY).catch(() => {}),
  ]);
}

async function persistUser(user: User) {
  if (user.isGuest) {
    await AsyncStorage.setItem(AUTH_KEY, JSON.stringify(user));
    return;
  }
  if (user.token) await SecureStore.setItemAsync(ACCESS_TOKEN_KEY, user.token);
  if (user.refresh_token) await SecureStore.setItemAsync(REFRESH_TOKEN_KEY, user.refresh_token);
  const profile = { ...user, token: undefined, refresh_token: undefined };
  await AsyncStorage.setItem(AUTH_KEY, JSON.stringify(profile));
}

async function refreshSavedUser(user: User): Promise<User | null> {
  if (!user.refresh_token) return user;
  try {
    const response = await fetch(`${API}/auth/refresh`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ refresh_token: user.refresh_token }),
    });
    if (response.status === 401) return null;
    if (!response.ok) return user;
    const data = await response.json();
    return normalizeUser({
      ...user,
      ...data.user,
      token: data.session?.access_token || user.token,
      refresh_token: data.session?.refresh_token || user.refresh_token,
      isGuest: false,
      is_guest: false,
    });
  } catch {
    // Preserve the last session during a temporary network outage. API calls
    // will still enforce the token server-side.
    return user;
  }
}

export const useAuth = create<AuthState>((set, get) => ({
  user: null,
  isLoggedIn: false,
  isGuest: false,

  setUser: async (user) => {
    const normalized = user ? normalizeUser(user) : null;
    if (normalized) await persistUser(normalized);
    else await clearStoredAuth(get().user?.id);
    set(flags(normalized));
  },

  saveUser: async (user) => {
    const normalized = user ? normalizeUser(user) : null;
    if (normalized) await persistUser(normalized);
    else await clearStoredAuth(get().user?.id);
    set(flags(normalized));
  },

  loadUser: async () => {
    try {
      const raw = await AsyncStorage.getItem(AUTH_KEY);
      if (!raw) {
        set(flags(null));
        return;
      }
      let user = normalizeUser(JSON.parse(raw));
      if (user.isGuest) {
        const expiresAt = user.expires_at ? new Date(user.expires_at).getTime() : 0;
        if (!expiresAt || expiresAt <= Date.now()) {
          await clearStoredAuth(user.id);
          set(flags(null));
          return;
        }
      } else {
        user = {
          ...user,
          token: await SecureStore.getItemAsync(ACCESS_TOKEN_KEY) || user.token || undefined,
          refresh_token: await SecureStore.getItemAsync(REFRESH_TOKEN_KEY) || user.refresh_token || undefined,
        };
        const refreshed = await refreshSavedUser(user);
        if (!refreshed) {
          await clearStoredAuth(user.id);
          set(flags(null));
          return;
        }
        user = refreshed;
      }
      await persistUser(user);
      set(flags(user));
    } catch {
      await clearStoredAuth();
      set(flags(null));
    }
  },

  clearUser: async () => {
    await clearStoredAuth(get().user?.id);
    set(flags(null));
  },

  startGuestSession: async () => {
    const guestUser = createGuestUser();
    await AsyncStorage.removeItem('cached_receipts');
    await AsyncStorage.setItem(AUTH_KEY, JSON.stringify(guestUser));
    set(flags(guestUser));
    return guestUser;
  },
}));

export const loadUser = async () => useAuth.getState().loadUser();
export const saveUser = async (user: User | null) => useAuth.getState().saveUser(user);
export const setUser = async (user: User | null) => useAuth.getState().setUser(user);
export const clearUser = async () => useAuth.getState().clearUser();
export const startGuestSession = async () => useAuth.getState().startGuestSession();
export const getUser = () => useAuth.getState().user;
export const getUserToken = () => useAuth.getState().user?.token || '';
export const getGuestSessionId = () => {
  const user = useAuth.getState().user;
  if (!user || !(user.isGuest || user.is_guest || user.token === 'guest')) return '';
  return user.guest_session_id || user.id;
};

export default useAuth;
