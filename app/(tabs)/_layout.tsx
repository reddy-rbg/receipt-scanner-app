import { useEffect, useState } from 'react';
import { Tabs } from 'expo-router';
import { View, StyleSheet, ActivityIndicator } from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import { loadUser, useAuth, clearUser } from '../../stores/authStore';
import { loadTheme, useTheme } from '../../stores/themeStore';
import LoginScreen from '../LoginScreen';

const FALLBACK_COLORS = {
  bg:'#080810', surface:'#0f0f1a',
  accent:'#7c6aff', text3:'#3d3a55',
  border:'rgba(255,255,255,0.06)',
};

export default function TabLayout() {
  const { user, isLoggedIn } = useAuth();
  const { colors: C } = useTheme();
  const [initializing, setInitializing] = useState(true);

  useEffect(() => {
    async function init() {
      await Promise.all([loadUser(), loadTheme()]);
      setInitializing(false);
    }
    init();
  }, []);

  // Show loading spinner while checking saved auth
  if (initializing) {
    return (
      <View style={{ flex:1, backgroundColor:FALLBACK_COLORS.bg, alignItems:'center', justifyContent:'center' }}>
        <ActivityIndicator color={FALLBACK_COLORS.accent} size="large"/>
      </View>
    );
  }

  // Show login screen if not authenticated
  if (!isLoggedIn) {
    return <LoginScreen />;
  }

  // Show tabs after auth
  return (
    <Tabs
      screenOptions={{
        headerStyle: {
          backgroundColor: C.bg,
          borderBottomColor: C.border,
          borderBottomWidth: 1,
          elevation: 0,
          shadowOpacity: 0,
        },
        headerTintColor: C.text,
        headerTitleStyle: { fontWeight:'800', fontSize:17, letterSpacing:-0.5 },
        headerRight: () => <View style={styles.dot} />,
        tabBarStyle: {
          backgroundColor: C.surface,
          borderTopColor: C.border,
          borderTopWidth: 1,
          height: 72,
          paddingBottom: 12,
          paddingTop: 8,
        },
        tabBarActiveTintColor: C.accent,
        tabBarInactiveTintColor: C.text3,
        tabBarLabelStyle: { fontSize:9, fontWeight:'600', marginTop:2 },
      }}
    >
      <Tabs.Screen
        name="index"
        options={{
          title: 'ReceiptAI ✦',
          tabBarLabel: 'Scan',
          tabBarIcon: ({ color, size }) => <Ionicons name="scan-outline" size={size} color={color} />,
        }}
      />
      <Tabs.Screen
        name="receipts"
        options={{
          title: 'My Receipts',
          tabBarLabel: 'Receipts',
          tabBarIcon: ({ color, size }) => <Ionicons name="receipt-outline" size={size} color={color} />,
        }}
      />
      <Tabs.Screen
        name="agent"
        options={{
          title: 'AI Agent',
          tabBarLabel: 'Agent',
          tabBarIcon: ({ color, size }) => <Ionicons name="sparkles-outline" size={size} color={color} />,
        }}
      />
      <Tabs.Screen
        name="memory"
        options={{
          title: 'Price Memory',
          tabBarLabel: 'Memory',
          tabBarIcon: ({ color, size }) => <Ionicons name="pricetag-outline" size={size} color={color} />,
        }}
      />
      <Tabs.Screen
        name="profile"
        options={{
          title: 'Profile',
          tabBarLabel: 'Profile',
          tabBarIcon: ({ color, size }) => <Ionicons name="person-outline" size={size} color={color} />,
        }}
      />
    </Tabs>
  );
}

const styles = StyleSheet.create({
  dot: {
    width:7, height:7, borderRadius:4,
    backgroundColor:'#4ade80', marginRight:16,
    shadowColor:'#4ade80', shadowOpacity:0.8, shadowRadius:4,
  },
});
