import { create } from 'zustand';
import AsyncStorage from '@react-native-async-storage/async-storage';
export type ThemeMode = 'dark' | 'light';
export const DARK_COLORS = { bg:'#06070D', surface:'#0D0F18', surface2:'#151824', surface3:'#202432', card:'#10131F', card2:'#181C2B', border:'rgba(238,242,255,0.10)', accent:'#7C6DFF', accent2:'#E85D97', accent3:'#52E6C8', text:'#F5F3FF', text2:'#AAAEC3', text3:'#71768C', green:'#42D987', red:'#FF6378', gold:'#F3C75C', success:'#42D987', warning:'#F3C75C', danger:'#FF6378' };
export const LIGHT_COLORS = { bg:'#F5F7FB', surface:'#FFFFFF', surface2:'#EEF1F8', surface3:'#E2E7F1', card:'#FFFFFF', card2:'#F8FAFE', border:'#D9DFEC', accent:'#6556F3', accent2:'#D83D7C', accent3:'#078F79', text:'#101522', text2:'#5E6577', text3:'#8C93A4', green:'#0D9F63', red:'#D83C5C', gold:'#AE7D00', success:'#0D9F63', warning:'#AE7D00', danger:'#D83C5C' };
type Colors = typeof DARK_COLORS;
interface ThemeState { theme: ThemeMode; isDark: boolean; colors: Colors; setTheme: (theme: ThemeMode) => Promise<void>; toggleTheme: () => Promise<void>; loadTheme: () => Promise<void>; }
export const useThemeStore = create<ThemeState>((set,get)=>({ theme:'dark', isDark:true, colors:DARK_COLORS, setTheme: async (theme)=>{ const isDark=theme==='dark'; await AsyncStorage.setItem('theme_mode', theme); set({theme,isDark,colors:isDark?DARK_COLORS:LIGHT_COLORS}); }, toggleTheme: async()=>{ await get().setTheme(get().theme==='dark'?'light':'dark'); }, loadTheme: async()=>{ const saved=await AsyncStorage.getItem('theme_mode').catch(()=>null); const theme:ThemeMode=saved==='light'?'light':'dark'; const isDark=theme==='dark'; set({theme,isDark,colors:isDark?DARK_COLORS:LIGHT_COLORS}); } }));
export const getColors = () => useThemeStore.getState().colors;
export const loadTheme = async () => useThemeStore.getState().loadTheme();
export const useTheme = useThemeStore;
export default useThemeStore;
