import AsyncStorage from '@react-native-async-storage/async-storage';
import { useEffect, useState } from 'react';

// Light mode colors
export const LIGHT = {
  bg:'#ffffff', surface:'#f5f5f5', surface2:'#eeeeee', surface3:'#e0e0e0',
  border:'rgba(0,0,0,0.08)',
  accent:'#7c6aff', accent2:'#ff6a9e', accent3:'#00b894',
  text:'#1a1a2e', text2:'#555577', text3:'#999999',
  green:'#00b894', red:'#ff6b6b', gold:'#f39c12',
};

// Dark mode colors (current)
export const DARK = {
  bg:'#080810', surface:'#0f0f1a', surface2:'#16162a', surface3:'#1e1e35',
  border:'rgba(255,255,255,0.06)',
  accent:'#7c6aff', accent2:'#ff6a9e', accent3:'#6affd4',
  text:'#ede8ff', text2:'#7e7a9a', text3:'#3d3a55',
  green:'#4ade80', red:'#ff6b6b', gold:'#fbbf24',
};

// Simple global theme
let _theme: 'dark' | 'light' = 'dark';
let _listeners: Array<() => void> = [];

export function getTheme() { return _theme; }
export function getColors() { return _theme === 'dark' ? DARK : LIGHT; }

export async function setTheme(mode: 'dark' | 'light') {
  _theme = mode;
  await AsyncStorage.setItem('app_theme', mode);
  _listeners.forEach(fn => fn());
}

export async function loadTheme() {
  const saved = await AsyncStorage.getItem('app_theme');
  if (saved === 'light' || saved === 'dark') _theme = saved;
}

export function useTheme() {
  const [, forceUpdate] = useState(0);
  useEffect(() => {
    const listener = () => forceUpdate(n => n + 1);
    _listeners.push(listener);
    return () => { _listeners = _listeners.filter(l => l !== listener); };
  }, []);
  return { theme: _theme, colors: getColors(), setTheme };
}