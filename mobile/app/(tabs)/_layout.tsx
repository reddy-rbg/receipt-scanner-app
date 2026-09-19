import { useEffect, useState } from 'react';
import { router, Tabs } from 'expo-router';
import { View, StyleSheet, ActivityIndicator } from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import { useSafeAreaInsets } from 'react-native-safe-area-context';
import { IconButton } from '../../components/IconButton';
import { loadUser, useAuth } from '../../stores/authStore';
import { loadTheme, useTheme } from '../../stores/themeStore';
import LoginScreen from '../LoginScreen';

const FALLBACK_COLORS = {
  bg:'#06070D', surface:'#0D0F18',
  accent:'#7C6DFF', text3:'#71768C',
  border:'rgba(238,242,255,0.10)',
};

export default function TabLayout() {
  const { isLoggedIn } = useAuth();
  const { colors: C } = useTheme();
  const insets = useSafeAreaInsets();
  const backButton = () => (
    <View style={{ marginLeft: 12 }}>
      <IconButton name="arrow-back" label="Go back" onPress={() => router.canGoBack() ? router.back() : router.replace('/home')} />
    </View>
  );
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
      initialRouteName="home"
      backBehavior="history"
      safeAreaInsets={{ bottom: 0 }}
      screenOptions={{
        headerStyle: {
          backgroundColor: C.bg,
          borderBottomColor: C.border,
          borderBottomWidth: 1,
          elevation: 0,
          shadowOpacity: 0,
        },
        headerTintColor: C.text,
        headerTitleStyle: { fontWeight:'900', fontSize:17, letterSpacing:-0.2 },
        tabBarStyle: {
          marginHorizontal: 13,
          marginBottom: Math.max(insets.bottom, 10),
          backgroundColor: C.surface,
          borderTopColor: C.border,
          borderTopWidth: 1,
          borderLeftWidth: 1,
          borderRightWidth: 1,
          borderBottomWidth: 1,
          borderColor: C.border,
          borderRadius: 26,
          borderBottomRightRadius: 16,
          height: 72,
          paddingBottom: 8,
          paddingTop: 7,
          elevation: 10,
          shadowColor: '#36283E',
          shadowOpacity: 0.17,
          shadowRadius: 22,
          shadowOffset: { width: 0, height: 11 },
        },
        tabBarActiveTintColor: C.accent,
        tabBarLabelPosition: 'below-icon',
        tabBarHideOnKeyboard: true,
        sceneStyle: { backgroundColor: C.bg },
        tabBarInactiveTintColor: C.text3,
        tabBarLabelStyle: { fontSize:10, fontWeight:'800', marginTop:2, letterSpacing:-0.1 },
      }}
    >
      <Tabs.Screen
        name="home"
        options={{
          title: 'Home',
          headerShown: false,
          tabBarLabel: 'Home',
          tabBarIcon: ({ color, size, focused }) => <Ionicons name={focused ? 'home' : 'home-outline'} size={size} color={color} />,
        }}
      />
      <Tabs.Screen
        name="receipts"
        options={{
          title: 'Receipts',
          headerShown: false,
          sceneStyle: { backgroundColor: C.bg, paddingTop: insets.top },
          tabBarLabel: 'Receipts',
          tabBarIcon: ({ color, size, focused }) => <Ionicons name={focused ? 'receipt' : 'receipt-outline'} size={size} color={color} />,
        }}
      />
      <Tabs.Screen
        name="index"
        options={{
          title: 'Capture',
          tabBarLabel: 'Capture',
          tabBarIconStyle: { width: 44, height: 28 },
          tabBarIcon: () => (
            <View style={[styles.captureButton, { backgroundColor:C.accent, shadowColor:C.accent }]}>
              <Ionicons name="scan-outline" size={22} color="#FFF" />
            </View>
          ),
        }}
      />
      <Tabs.Screen
        name="memory"
        options={{
          title: 'Memory',
          headerShown: false,
          sceneStyle: { backgroundColor: C.bg, paddingTop: insets.top },
          tabBarLabel: 'Memory',
          tabBarIcon: ({ color, size, focused }) => <Ionicons name={focused ? 'bar-chart' : 'bar-chart-outline'} size={size} color={color} />,
        }}
      />
      <Tabs.Screen
        name="agent"
        options={{
          title: 'AI Assistant',
          headerShown: false,
          sceneStyle: { backgroundColor: C.bg, paddingTop: insets.top },
          tabBarLabel: 'AI',
          tabBarIcon: ({ color, size, focused }) => <Ionicons name={focused ? 'sparkles' : 'sparkles-outline'} size={size + 1} color={color} />,
        }}
      />
      <Tabs.Screen
        name="shop"
        options={{
          href: null,
          title: 'Shopping',
          headerLeft: backButton,
        }}
      />
      <Tabs.Screen
        name="profile"
        options={{
          href: null,
          title: 'Profile',
          headerLeft: backButton,
        }}
      />
    </Tabs>
  );
}

const styles = StyleSheet.create({
  captureButton: {
    width:44,
    height:28,
    borderRadius:10,
    borderBottomRightRadius:8,
    alignItems:'center',
    justifyContent:'center',
    shadowOpacity:0.34,
    shadowRadius:13,
    shadowOffset:{width:0,height:8},
    elevation:7,
  },
});
