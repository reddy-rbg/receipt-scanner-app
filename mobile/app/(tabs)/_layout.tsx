import { useEffect, useState } from 'react';
import { Tabs } from 'expo-router';
import { View, StyleSheet, ActivityIndicator } from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import { loadUser, useAuth, clearUser } from '../../stores/authStore';
import { loadTheme, useTheme } from '../../stores/themeStore';
import LoginScreen from '../LoginScreen';

const FALLBACK_COLORS = {
  bg:'#06070D', surface:'#0D0F18',
  accent:'#7C6DFF', text3:'#71768C',
  border:'rgba(238,242,255,0.10)',
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
        headerTitleStyle: { fontWeight:'900', fontSize:17, letterSpacing:0 },
        headerRight: () => <View style={styles.dot} />,
        tabBarStyle: {
          backgroundColor: C.surface,
          borderTopColor: 'rgba(238,242,255,0.08)',
          borderTopWidth: 1,
          height: 78,
          paddingBottom: 14,
          paddingTop: 9,
          elevation: 10,
          shadowColor: '#000',
          shadowOpacity: 0.24,
          shadowRadius: 18,
          shadowOffset: { width: 0, height: -8 },
        },
        tabBarActiveTintColor: C.accent,
        tabBarInactiveTintColor: C.text3,
        tabBarLabelStyle: { fontSize:10, fontWeight:'800', marginTop:2, letterSpacing:0 },
      }}
    >
      <Tabs.Screen
        name="index"
        options={{
          title: 'ReceiptAI',
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
        name="shop"
        options={{
          title: 'Today List',
          tabBarLabel: 'Shop',
          tabBarIcon: ({ color, size }) => <Ionicons name="basket-outline" size={size} color={color} />,
        }}
      />
      <Tabs.Screen
        name="agent"
        options={{
          title: 'Ask Anything',
          tabBarLabel: 'Agent',
          tabBarIcon: ({ color, size }) => <Ionicons name="sparkles-outline" size={size} color={color} />,
        }}
      />
      <Tabs.Screen
        name="memory"
        options={{
          title: 'Matters Now',
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
