import { Platform, Pressable, StyleSheet, Text } from "react-native";

export default function AndroidOnlyButton({
  onPress,
  title,
}: {
  onPress: () => void;
  title: string;
}) {
  if (Platform.OS !== "android") return null;
  return (
    <Pressable style={styles.btn} onPress={onPress}>
      <Text style={styles.txt}>{title}</Text>
    </Pressable>
  );
}

const styles = StyleSheet.create({
  btn: {
    backgroundColor: "#1E88E5",
    paddingVertical: 10,
    paddingHorizontal: 16,
    borderRadius: 8,
  },
  txt: { color: "#fff", fontWeight: "600" },
});
