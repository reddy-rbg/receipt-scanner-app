import { Tabs } from 'expo-router';
import { View, StyleSheet } from 'react-native';
import { Ionicons } from '@expo/vector-icons';

const C = {
  bg: '#080810', surface: '#0f0f1a',
  accent: '#7c6aff', text3: '#3d3a55',
  border: 'rgba(255,255,255,0.06)',
};

export default function TabLayout() {
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
        headerTintColor: '#ede8ff',
        headerTitleStyle: { fontWeight: '800', fontSize: 17, letterSpacing: -0.5 },
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
        tabBarLabelStyle: { fontSize: 9, fontWeight: '600', marginTop: 2 },
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
        name="shopping"
        options={{
          title: 'Shopping List',
          tabBarLabel: 'List',
          tabBarIcon: ({ color, size }) => <Ionicons name="cart-outline" size={size} color={color} />,
        }}
      />
      <Tabs.Screen
        name="price"
        options={{
          title: 'Price Tracker',
          tabBarLabel: 'Prices',
          tabBarIcon: ({ color, size }) => <Ionicons name="trending-up-outline" size={size} color={color} />,
        }}
      />
      <Tabs.Screen
        name="ask"
        options={{
          title: 'Ask AI',
          tabBarLabel: 'Ask AI',
          tabBarIcon: ({ color, size }) => <Ionicons name="sparkles-outline" size={size} color={color} />,
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
    width: 7, height: 7, borderRadius: 4,
    backgroundColor: '#4ade80', marginRight: 16,
    shadowColor: '#4ade80', shadowOpacity: 0.8, shadowRadius: 4,
  },
});
