import AsyncStorage from '@react-native-async-storage/async-storage';

const TOKEN_KEY = 'user_token';

// In-memory cache for sync access
let _token = '';

export function setUserToken(token: string) {
  _token = token;
  // Also save to AsyncStorage for persistence
  AsyncStorage.setItem(TOKEN_KEY, token).catch(() => {});
}

export function getUserToken(): string {
  return _token;
}

// Call this on app startup to restore token
export async function loadUserToken(): Promise<string> {
  try {
    const token = await AsyncStorage.getItem(TOKEN_KEY);
    _token = token || '';
    return _token;
  } catch {
    return '';
  }
}

export async function clearUserToken() {
  _token = '';
  await AsyncStorage.removeItem(TOKEN_KEY).catch(() => {});
}