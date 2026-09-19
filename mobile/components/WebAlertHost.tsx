import { useEffect, useMemo, useState } from 'react';
import {
  Alert,
  Modal,
  Platform,
  Pressable,
  StyleSheet,
  Text,
  View,
  type AlertButton,
  type AlertOptions,
} from 'react-native';
import { useTheme } from '../stores/themeStore';

type AlertRequest = {
  id: number;
  title: string;
  message?: string;
  buttons: AlertButton[];
  options?: AlertOptions;
};

let currentAlert: AlertRequest | null = null;
let nextId = 1;
const listeners = new Set<(request: AlertRequest | null) => void>();

function publish(request: AlertRequest | null) {
  currentAlert = request;
  listeners.forEach(listener => listener(request));
}

if (Platform.OS === 'web') {
  Alert.alert = (title, message, buttons, options) => {
    publish({
      id: nextId++,
      title,
      message,
      buttons: buttons?.length ? buttons : [{ text: 'OK' }],
      options,
    });
  };
}

export function WebAlertHost() {
  const { colors: C } = useTheme();
  const [request, setRequest] = useState<AlertRequest | null>(currentAlert);
  const styles = useMemo(() => createStyles(C), [C]);

  useEffect(() => {
    listeners.add(setRequest);
    return () => {
      listeners.delete(setRequest);
    };
  }, []);

  if (Platform.OS !== 'web' || !request) return null;

  const dismiss = (button?: AlertButton) => {
    publish(null);
    button?.onPress?.();
  };
  const cancelButton = request.buttons.find(button => button.style === 'cancel');
  const canDismiss = request.options?.cancelable !== false;

  return (
    <Modal
      transparent
      visible
      animationType="fade"
      onRequestClose={() => canDismiss && dismiss(cancelButton)}
    >
      <View style={styles.backdrop} accessibilityViewIsModal>
        <Pressable
          style={StyleSheet.absoluteFill}
          accessibilityRole="button"
          accessibilityLabel="Dismiss message"
          onPress={() => canDismiss && dismiss(cancelButton)}
        />
        <View style={styles.card} role="alertdialog">
          <Text style={styles.title}>{request.title}</Text>
          {!!request.message && <Text style={styles.message}>{request.message}</Text>}
          <View style={styles.actions}>
            {request.buttons.map((button, index) => {
              const destructive = button.style === 'destructive';
              const primary = !cancelButton || button.style !== 'cancel';
              return (
                <Pressable
                  key={`${request.id}-${button.text || index}`}
                  accessibilityRole="button"
                  accessibilityLabel={button.text || 'OK'}
                  onPress={() => dismiss(button)}
                  style={({ pressed }) => [
                    styles.button,
                    primary && styles.primaryButton,
                    pressed && styles.pressed,
                  ]}
                >
                  <Text style={[
                    styles.buttonText,
                    primary && styles.primaryButtonText,
                    destructive && styles.destructiveText,
                  ]}>
                    {button.text || 'OK'}
                  </Text>
                </Pressable>
              );
            })}
          </View>
        </View>
      </View>
    </Modal>
  );
}

function createStyles(C: any) {
  return StyleSheet.create({
    backdrop: {
      flex: 1,
      alignItems: 'center',
      justifyContent: 'center',
      padding: 24,
      backgroundColor: 'rgba(18, 13, 24, 0.52)',
    },
    card: {
      width: '100%',
      maxWidth: 430,
      padding: 22,
      borderRadius: 24,
      borderBottomRightRadius: 10,
      borderWidth: 1,
      borderColor: C.border,
      backgroundColor: C.surface,
      shadowColor: '#1C1224',
      shadowOpacity: 0.24,
      shadowRadius: 28,
      shadowOffset: { width: 0, height: 14 },
      elevation: 12,
    },
    title: { color: C.text, fontSize: 19, fontWeight: '900', marginBottom: 8 },
    message: { color: C.text2, fontSize: 14, lineHeight: 21, marginBottom: 20 },
    actions: { flexDirection: 'row', flexWrap: 'wrap', justifyContent: 'flex-end', gap: 9 },
    button: {
      minWidth: 92,
      minHeight: 44,
      paddingHorizontal: 16,
      paddingVertical: 11,
      alignItems: 'center',
      justifyContent: 'center',
      borderRadius: 14,
      borderWidth: 1,
      borderColor: C.border,
      backgroundColor: C.surface2,
    },
    primaryButton: { backgroundColor: C.accent, borderColor: C.accent },
    pressed: { opacity: 0.76 },
    buttonText: { color: C.text, fontSize: 13, fontWeight: '800' },
    primaryButtonText: { color: '#FFFFFF' },
    destructiveText: { color: C.red },
  });
}
