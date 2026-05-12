import { create } from 'zustand';
import AsyncStorage from '@react-native-async-storage/async-storage';
export type ThemeMode = 'dark' | 'light';
export const DARK_COLORS = { bg:'#080810', surface:'#0f0f1a', surface2:'#16162a', card:'#151528', card2:'#1B1A33', border:'rgba(255,255,255,0.06)', accent:'#7c6aff', accent2:'#ff6a9e', accent3:'#6affd4', text:'#ede8ff', text2:'#7e7a9a', text3:'#3d3a55', green:'#4ade80', red:'#ff6b6b', success:'#54E6A5', warning:'#FFD166', danger:'#FF5C7A' };
export const LIGHT_COLORS = { bg:'#F7F7FB', surface:'#FFFFFF', surface2:'#F0F0FA', card:'#FFFFFF', card2:'#F0F0FA', border:'#DDDDF0', accent:'#6D5DFB', accent2:'#E93D8F', accent3:'#00A88A', text:'#111322', text2:'#6D6A80', text3:'#9A98AA', green:'#12A66A', red:'#D9365E', success:'#12A66A', warning:'#B98500', danger:'#D9365E' };
type Colors = typeof DARK_COLORS;
interface ThemeState { theme: ThemeMode; isDark: boolean; colors: Colors; setTheme: (theme: ThemeMode) => Promise<void>; toggleTheme: () => Promise<void>; loadTheme: () => Promise<void>; }
export const useThemeStore = create<ThemeState>((set,get)=>({ theme:'dark', isDark:true, colors:DARK_COLORS, setTheme: async (theme)=>{ const isDark=theme==='dark'; await AsyncStorage.setItem('theme_mode', theme); set({theme,isDark,colors:isDark?DARK_COLORS:LIGHT_COLORS}); }, toggleTheme: async()=>{ await get().setTheme(get().theme==='dark'?'light':'dark'); }, loadTheme: async()=>{ const saved=await AsyncStorage.getItem('theme_mode').catch(()=>null); const theme:ThemeMode=saved==='light'?'light':'dark'; const isDark=theme==='dark'; set({theme,isDark,colors:isDark?DARK_COLORS:LIGHT_COLORS}); } }));
export const getColors = () => useThemeStore.getState().colors;
export const loadTheme = async () => useThemeStore.getState().loadTheme();
export const useTheme = useThemeStore;
export default useThemeStore;
