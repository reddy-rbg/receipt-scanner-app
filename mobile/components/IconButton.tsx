import { Ionicons } from '@expo/vector-icons';
import { StyleSheet, TouchableOpacity } from 'react-native';
import { useTheme } from '../stores/themeStore';

type Props = {
  name: 'close' | 'arrow-back';
  label: string;
  onPress: () => void;
};

/** Visible, labelled navigation controls with a consistent touch target. */
export function IconButton({ name, label, onPress }: Props) {
  const { colors: C } = useTheme();
  return (
    <TouchableOpacity
      onPress={onPress}
      accessibilityRole="button"
      accessibilityLabel={label}
      activeOpacity={0.7}
      style={[styles.button, { backgroundColor: C.surface2, borderColor: C.border }]}
    >
      <Ionicons name={name} size={24} color={C.text} />
    </TouchableOpacity>
  );
}

const styles = StyleSheet.create({
  button: {
    width: 44,
    height: 44,
    flexShrink: 0,
    borderRadius: 16,
    borderWidth: 1,
    alignItems: 'center',
    justifyContent: 'center',
  },
});
