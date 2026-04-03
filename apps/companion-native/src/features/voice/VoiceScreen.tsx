import React, { useState } from 'react';
import { Pressable, StyleSheet, Text, TextInput, View } from 'react-native';

import { SurfaceCard, SurfaceHeader } from '@/components/SurfaceCard';
import { useTheme } from '@/theme/ThemeProvider';

type Props = {
  onSubmit: (text: string) => void;
  sending?: boolean;
  transcript?: string;
  response?: string;
};

export function VoiceScreen({ onSubmit, sending, transcript, response }: Props) {
  const [text, setText] = useState('');
  const { colors } = useTheme();

  return (
    <SurfaceCard>
      <SurfaceHeader title="Voice" subtitle="Capture a command, then let Axon route it to the right workspace." />
      <TextInput
        multiline
        value={text}
        onChangeText={setText}
        placeholder="Ask Axon to inspect a repo, open a PR, or report attention..."
        placeholderTextColor={colors.muted}
        style={[styles.input, { borderColor: colors.border, color: colors.text, backgroundColor: '#0b1627' }]}
      />
      <Pressable onPress={() => onSubmit(text.trim())} style={[styles.button, !text.trim() && styles.buttonDisabled]} disabled={!text.trim() || !!sending}>
        <Text style={styles.buttonText}>{sending ? 'Sending...' : 'Send voice turn'}</Text>
      </Pressable>
      <View style={styles.stack}>
        {transcript ? <Text style={[styles.meta, { color: colors.muted }]}>Transcript: {transcript}</Text> : null}
        {response ? <Text style={[styles.meta, { color: colors.muted }]}>Reply: {response}</Text> : null}
      </View>
    </SurfaceCard>
  );
}

const styles = StyleSheet.create({
  input: {
    minHeight: 100,
    borderWidth: 1,
    borderRadius: 16,
    paddingHorizontal: 14,
    paddingVertical: 12,
    fontSize: 15,
    textAlignVertical: 'top',
  },
  button: {
    borderRadius: 14,
    paddingVertical: 12,
    alignItems: 'center',
    backgroundColor: '#8b5cf6',
  },
  buttonDisabled: {
    opacity: 0.55,
  },
  buttonText: {
    color: '#08111f',
    fontWeight: '800',
  },
  stack: {
    gap: 8,
  },
  meta: {
    fontSize: 12,
    lineHeight: 18,
  },
});
