import { create } from 'zustand';
import AsyncStorage from '@react-native-async-storage/async-storage';
export type ThemeMode = 'dark' | 'light';
export const DARK_COLORS = { bg:'#100F16', surface:'#17151F', surface2:'#211E2A', surface3:'#2C2836', card:'#191720', card2:'#211E29', border:'rgba(246,240,231,0.11)', accent:'#8A7BFF', accent2:'#F08AC2', accent3:'#5AD9CF', text:'#FFFDF8', text2:'#C3BCC8', text3:'#8D8795', green:'#5ADC9A', red:'#FF7185', gold:'#F3C66B', success:'#5ADC9A', warning:'#F3C66B', danger:'#FF7185' };
export const LIGHT_COLORS = { bg:'#F6F0E7', surface:'#FFFDF8', surface2:'#EEE7DD', surface3:'#E3D9CD', card:'#FFFDF8', card2:'#F9F4EC', border:'#DED5CA', accent:'#6557FF', accent2:'#D95F9E', accent3:'#168B80', text:'#17151B', text2:'#746F78', text3:'#98909B', green:'#168B63', red:'#D84961', gold:'#A87516', success:'#168B63', warning:'#A87516', danger:'#D84961' };
type Colors = typeof DARK_COLORS;
interface ThemeState { theme: ThemeMode; isDark: boolean; colors: Colors; setTheme: (theme: ThemeMode) => Promise<void>; toggleTheme: () => Promise<void>; loadTheme: () => Promise<void>; }
export const useThemeStore = create<ThemeState>((set,get)=>({ theme:'light', isDark:false, colors:LIGHT_COLORS, setTheme: async (theme)=>{ const isDark=theme==='dark'; await AsyncStorage.setItem('theme_mode', theme); set({theme,isDark,colors:isDark?DARK_COLORS:LIGHT_COLORS}); }, toggleTheme: async()=>{ await get().setTheme(get().theme==='dark'?'light':'dark'); }, loadTheme: async()=>{ const saved=await AsyncStorage.getItem('theme_mode').catch(()=>null); const theme:ThemeMode=saved==='dark'?'dark':'light'; const isDark=theme==='dark'; set({theme,isDark,colors:isDark?DARK_COLORS:LIGHT_COLORS}); } }));
export const getColors = () => useThemeStore.getState().colors;
export const loadTheme = async () => useThemeStore.getState().loadTheme();
export const useTheme = useThemeStore;
export default useThemeStore;
