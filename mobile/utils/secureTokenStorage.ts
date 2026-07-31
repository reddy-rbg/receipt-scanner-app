import { Platform } from 'react-native';
import * as SecureStore from 'expo-secure-store';

const webStorage = () => {
  if (Platform.OS !== 'web' || typeof globalThis.localStorage === 'undefined') return null;
  return globalThis.localStorage;
};

export async function getSecureToken(key: string): Promise<string | null> {
  const storage = webStorage();
  if (storage) return storage.getItem(key);
  return SecureStore.getItemAsync(key);
}

export async function setSecureToken(key: string, value: string): Promise<void> {
  const storage = webStorage();
  if (storage) {
    storage.setItem(key, value);
    return;
  }
  await SecureStore.setItemAsync(key, value);
}

export async function deleteSecureToken(key: string): Promise<void> {
  const storage = webStorage();
  if (storage) {
    storage.removeItem(key);
    return;
  }
  await SecureStore.deleteItemAsync(key);
}
