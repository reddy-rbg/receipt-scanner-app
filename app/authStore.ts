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
  // Snake-case aliases are used by some screens/backend payloads
  is_guest?: boolean;
  guestStartTime?: number;
  guest_session_id?: string;
  guestSessionId?: string;
};

// Global state
let _user: User | null = null;
let _listeners: Array<() => void> = [];

function notify() {
  _listeners.forEach(fn => fn());
}

function createGuestId(): string {
  return `guest_${Date.now()}_${Math.random().toString(36).slice(2, 10)}`;
}

function normalizeUser(user: User): User {
  const isGuestUser = user.isGuest === true || user.is_guest === true || user.id === 'guest';

  if (!isGuestUser) {
    return {
      ...user,
      isGuest: false,
      is_guest: false,
    };
  }

  const existingGuestId =
    user.guest_session_id ||
    user.guestSessionId ||
    (user.id && user.id !== 'guest' ? user.id : '');

  const guestId = existingGuestId || createGuestId();

  return {
    ...user,
    id: guestId,
    token: '',
    email: user.email || 'guest@receiptai.app',
    name: user.name || 'Guest User',
    created_at: user.created_at || new Date().toISOString(),
    isGuest: true,
    is_guest: true,
    guestStartTime: user.guestStartTime || Date.now(),
    guest_session_id: guestId,
    guestSessionId: guestId,
  };
}

export function getUser(): User | null { return _user; }
export function isLoggedIn(): boolean { return _user !== null; }
export function isGuest(): boolean { return _user?.isGuest === true || _user?.is_guest === true; }

export async function saveUser(user: User) {
  const normalizedUser = normalizeUser(user);
  _user = normalizedUser;
  await AsyncStorage.setItem('auth_user', JSON.stringify(normalizedUser)).catch(() => {});
  notify();
}

export async function clearUser() {
  _user = null;
  await AsyncStorage.removeItem('auth_user').catch(() => {});
  await AsyncStorage.removeItem('user_token').catch(() => {});
  notify();
}

export async function loadUser(): Promise<User | null> {
  try {
    const saved = await AsyncStorage.getItem('auth_user');
    if (saved) {
      const user = normalizeUser(JSON.parse(saved) as User);
      // Check if guest trial has expired
      if ((user.isGuest || user.is_guest) && user.guestStartTime) {
        const elapsed = Date.now() - user.guestStartTime;
        const TRIAL_MS = 24 * 60 * 60 * 1000;
        if (elapsed >= TRIAL_MS) {
          await clearUser();
          return null;
        }
      }
      _user = user;
      await AsyncStorage.setItem('auth_user', JSON.stringify(user)).catch(() => {});
      return user;
    }
  } catch {}
  return null;
}

export function getUserToken(): string {
  return _user?.token || '';
}

export function getGuestSessionId(): string {
  return _user?.guest_session_id || _user?.guestSessionId || (_user?.isGuest ? _user.id : '');
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

  return { user, isLoggedIn: user !== null, isGuest: user?.isGuest === true || user?.is_guest === true }; 
}
