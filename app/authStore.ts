// ─────────────────────────────────────────
// app/authStore.ts
// Global auth state shared across all screens
// ─────────────────────────────────────────

import { useState, useEffect } from 'react';
import AsyncStorage from '@react-native-async-storage/async-storage';

const API = 'https://web-production-3605f4.up.railway.app';

export type User = {
  id: string;
  email: string;
  name: string;
  created_at: string;
  token?: string;
  isGuest?: boolean;
  guestStartTime?: number;
};

// Global state
let _user: User | null = null;
let _listeners: Array<() => void> = [];

function notify() {
  _listeners.forEach(fn => fn());
}

export function getUser(): User | null { return _user; }
export function isLoggedIn(): boolean { return _user !== null; }
export function isGuest(): boolean { return _user?.isGuest === true; }

export async function saveUser(user: User) {
  _user = user;
  await AsyncStorage.setItem('auth_user', JSON.stringify(user)).catch(() => {});
  notify();
}

export async function clearUser() {
  _user = null;
  await AsyncStorage.removeItem('auth_user').catch(() => {});
  await AsyncStorage.removeItem('user_token').catch(() => {});
  await AsyncStorage.removeItem('cached_receipts').catch(() => {});
  await AsyncStorage.removeItem('receipts_cache').catch(() => {});
  await AsyncStorage.removeItem('last_receipts_user').catch(() => {});
  notify();
}

export async function loadUser(): Promise<User | null> {
  try {
    const saved = await AsyncStorage.getItem('auth_user');
    if (saved) {
      const user = JSON.parse(saved) as User;
      // Check if guest trial has expired
      if (user.isGuest && user.guestStartTime) {
        const elapsed = Date.now() - user.guestStartTime;
        const TRIAL_MS = 24 * 60 * 60 * 1000;
        if (elapsed >= TRIAL_MS) {
          await clearUser();
          return null;
        }
      }
      _user = user;
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

// React hook for components to subscribe to auth changes
export function useAuth() {
  const [user, setUser] = useState<User | null>(_user);

  useEffect(() => {
    const listener = () => setUser(_user ? { ..._user } : null);
    _listeners.push(listener);
    return () => {
      _listeners = _listeners.filter(l => l !== listener);
    };
  }, []);

  return { user, isLoggedIn: user !== null, isGuest: user?.isGuest === true };
}
