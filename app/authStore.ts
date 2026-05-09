// ─────────────────────────────────────────
// app/authStore.ts
// Global auth state shared across all screens
// ─────────────────────────────────────────

import { useState, useEffect } from 'react';
import AsyncStorage from '@react-native-async-storage/async-storage';

export type User = {
  id: string;
  email: string;
  name: string;
  created_at: string;
  token?: string;
  isGuest?: boolean;
  is_guest?: boolean;
  guestStartTime?: number;
  guest_session_id?: string;
  guestSessionId?: string;
};

let _user: User | null = null;
let _listeners: Array<() => void> = [];

function notify() {
  _listeners.forEach(fn => fn());
}

function createGuestId(): string {
  return `guest_${Date.now()}_${Math.random().toString(36).slice(2, 10)}`;
}

export function getUser(): User | null { return _user; }
export function isLoggedIn(): boolean { return _user !== null; }
export function isGuest(): boolean { return _user?.isGuest === true || _user?.is_guest === true; }

export function getGuestSessionId(): string {
  return _user?.guest_session_id || _user?.guestSessionId || _user?.id || '';
}

export async function saveUser(user: User) {
  // Normalize guest fields so every screen/backend request uses the same stable owner id.
  const normalized: User = {
    ...user,
    isGuest: user.isGuest === true || user.is_guest === true,
    is_guest: user.isGuest === true || user.is_guest === true,
  };

  if (normalized.isGuest) {
    const guestId = normalized.guest_session_id || normalized.guestSessionId || normalized.id || createGuestId();
    normalized.id = guestId;
    normalized.guest_session_id = guestId;
    normalized.guestSessionId = guestId;
    normalized.token = '';
    normalized.email = normalized.email || 'guest@receiptai.app';
    normalized.name = normalized.name || 'Guest User';
    normalized.created_at = normalized.created_at || new Date().toISOString();
    normalized.guestStartTime = normalized.guestStartTime || Date.now();
  }

  _user = normalized;
  await AsyncStorage.setItem('auth_user', JSON.stringify(normalized)).catch(() => {});
  notify();
}

export async function clearUser() {
  _user = null;
  await Promise.all([
    AsyncStorage.removeItem('auth_user'),
    AsyncStorage.removeItem('user_token'),
    AsyncStorage.removeItem('cached_receipts'),
    AsyncStorage.removeItem('receipts_cache'),
    AsyncStorage.removeItem('last_receipts_user'),
  ]).catch(() => {});
  notify();
}

export async function loadUser(): Promise<User | null> {
  try {
    const saved = await AsyncStorage.getItem('auth_user');
    if (saved) {
      const user = JSON.parse(saved) as User;
      if (user.isGuest || user.is_guest) {
        const elapsed = Date.now() - (user.guestStartTime || 0);
        const TRIAL_MS = 24 * 60 * 60 * 1000;
        if (!user.guestStartTime || elapsed >= TRIAL_MS) {
          await clearUser();
          return null;
        }
        const guestId = user.guest_session_id || user.guestSessionId || user.id || createGuestId();
        user.id = guestId;
        user.guest_session_id = guestId;
        user.guestSessionId = guestId;
        user.isGuest = true;
        user.is_guest = true;
        user.token = '';
      }
      _user = user;
      notify();
      return user;
    }
  } catch {}
  return null;
}

export function getUserToken(): string {
  return _user?.token || '';
}

export async function startGuestSession() {
  const guestId = createGuestId();
  await clearUser();
  await saveUser({
    id: guestId,
    email: 'guest@receiptai.app',
    name: 'Guest User',
    created_at: new Date().toISOString(),
    token: '',
    isGuest: true,
    is_guest: true,
    guestStartTime: Date.now(),
    guest_session_id: guestId,
    guestSessionId: guestId,
  });
}

export function useAuth() {
  const [user, setUserState] = useState<User | null>(_user);

  useEffect(() => {
    const listener = () => setUserState(_user ? { ..._user } : null);
    _listeners.push(listener);
    listener();
    return () => {
      _listeners = _listeners.filter(l => l !== listener);
    };
  }, []);

  const guest = user?.isGuest === true || user?.is_guest === true;
  return { user, isLoggedIn: user !== null, isGuest: guest };
}
