import { Stack } from 'expo-router';
import { StatusBar } from 'expo-status-bar';
import { useEffect } from 'react';
import { Text, TouchableOpacity, View } from 'react-native';
import { useTheme } from '../stores/themeStore';
import { appLogger } from '../utils/logger';

export function ErrorBoundary({ error, retry }: { error: Error; retry: () => void }) {
  useEffect(() => {
    appLogger.error('Root app error boundary caught an error', error, {
      screen: 'RootLayout',
      action: 'render',
    });
  }, [error]);

  return (
    <View style={{ flex:1, justifyContent:'center', padding:24, backgroundColor:'#090b0f' }}>
      <Text style={{ color:'#fff', fontSize:22, fontWeight:'900', marginBottom:8 }}>
        Something went wrong
      </Text>
      <Text style={{ color:'#9ca3af', fontSize:14, lineHeight:20, marginBottom:18 }}>
        The error was logged locally with screen and action context. Try again, and share the time of the issue for backend log matching.
      </Text>
      <TouchableOpacity onPress={retry} style={{ backgroundColor:'#7C6AFF', padding:14, borderRadius:12, alignItems:'center' }}>
        <Text style={{ color:'#fff', fontWeight:'900' }}>Try again</Text>
      </TouchableOpacity>
    </View>
  );
}

export default function RootLayout() {
  const { isDark } = useTheme();
  return (
    <>
      <StatusBar style={isDark ? 'light' : 'dark'} />
      <Stack screenOptions={{ headerShown: false }}>
        <Stack.Screen name="(tabs)" options={{ headerShown: false }} />
      </Stack>
    </>
  );
}
