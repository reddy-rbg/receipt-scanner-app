import Constants from 'expo-constants';
import { Platform } from 'react-native';

declare const process: {
  env?: Record<string, string | undefined>;
};

export const PRODUCTION_API = 'https://web-production-3605f4.up.railway.app';
const LOCAL_WEB_API = 'http://127.0.0.1:8000';

function cleanApiUrl(value?: string | null) {
  const trimmed = String(value || '').trim();
  return trimmed.replace(/\/+$/, '');
}

function isPrivateLanHost(host: string) {
  return (
    /^10\./.test(host) ||
    /^192\.168\./.test(host) ||
    /^172\.(1[6-9]|2\d|3[0-1])\./.test(host)
  );
}

export function resolveApiBase() {
  const envApi = cleanApiUrl(typeof process !== 'undefined' ? process.env?.EXPO_PUBLIC_API_URL : undefined);
  if (envApi) return envApi;

  const configuredApi = cleanApiUrl((Constants.expoConfig?.extra as any)?.apiUrl);
  if (configuredApi) return configuredApi;

  const webHost = Platform.OS === 'web' ? String((globalThis as any)?.location?.hostname || '') : '';
  if (webHost === 'localhost' || webHost === '127.0.0.1') return LOCAL_WEB_API;
  if (Platform.OS === 'web' && isPrivateLanHost(webHost)) return `http://${webHost}:8000`;

  return PRODUCTION_API;
}

export const API = resolveApiBase();
