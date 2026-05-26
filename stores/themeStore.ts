import { create } from 'zustand';
import AsyncStorage from '@react-native-async-storage/async-storage';
export type ThemeMode = 'dark' | 'light';
export const DARK_COLORS = { bg:'#070810', surface:'#10111d', surface2:'#17182b', surface3:'#22233a', card:'#121423', card2:'#1b1d33', border:'rgba(237,232,255,0.09)', accent:'#806fff', accent2:'#ff6aa6', accent3:'#62f2d0', text:'#f2eeff', text2:'#a8a3c0', text3:'#696481', green:'#4ade80', red:'#ff6b7d', gold:'#f6c453', success:'#54E6A5', warning:'#FFD166', danger:'#FF5C7A' };
export const LIGHT_COLORS = { bg:'#F7F8FC', surface:'#FFFFFF', surface2:'#F1F2FA', surface3:'#E6E8F4', card:'#FFFFFF', card2:'#F0F1FA', border:'#DADDEF', accent:'#6758F5', accent2:'#DE3F86', accent3:'#079C83', text:'#101323', text2:'#62677D', text3:'#969AAD', green:'#12A66A', red:'#D9365E', gold:'#B98500', success:'#12A66A', warning:'#B98500', danger:'#D9365E' };
type Colors = typeof DARK_COLORS;
interface ThemeState { theme: ThemeMode; isDark: boolean; colors: Colors; setTheme: (theme: ThemeMode) => Promise<void>; toggleTheme: () => Promise<void>; loadTheme: () => Promise<void>; }
export const useThemeStore = create<ThemeState>((set,get)=>({ theme:'dark', isDark:true, colors:DARK_COLORS, setTheme: async (theme)=>{ const isDark=theme==='dark'; await AsyncStorage.setItem('theme_mode', theme); set({theme,isDark,colors:isDark?DARK_COLORS:LIGHT_COLORS}); }, toggleTheme: async()=>{ await get().setTheme(get().theme==='dark'?'light':'dark'); }, loadTheme: async()=>{ const saved=await AsyncStorage.getItem('theme_mode').catch(()=>null); const theme:ThemeMode=saved==='light'?'light':'dark'; const isDark=theme==='dark'; set({theme,isDark,colors:isDark?DARK_COLORS:LIGHT_COLORS}); } }));
export const getColors = () => useThemeStore.getState().colors;
export const loadTheme = async () => useThemeStore.getState().loadTheme();
export const useTheme = useThemeStore;
export default useThemeStore;
