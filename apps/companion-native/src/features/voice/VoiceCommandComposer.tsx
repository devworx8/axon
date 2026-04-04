import React, { useState } from 'react';
import { Pressable, StyleSheet, Text, TextInput, View } from 'react-native';

import { StatusPill } from '@/components/StatusPill';
import { useTheme } from '@/theme/ThemeProvider';

type Props = {
  onSubmit: (text: string) => void;
  sending?: boolean;
  voiceMode?: string;
  workspaceLabel?: string;
  placeholder?: string;
  initialText?: string;
  prompts?: string[];
};

const defaultPrompts = [
  'What needs attention right now?',
  'What is the workspace path?',
  'Create a plan for the active project.',
];

export function VoiceCommandComposer({
  onSubmit,
  sending,
  voiceMode,
  workspaceLabel,
  placeholder,
  initialText = '',
  prompts = defaultPrompts,
}: Props) {
  const [text, setText] = useState(initialText);
  const { colors } = useTheme();

  return (
    <View style={styles.stack}>
      <View style={styles.statusRow}>
        <StatusPill
          label={voiceMode === 'live' ? 'Axon Voice Mode' : 'Push-to-talk'}
          tone={voiceMode === 'live' ? 'ok' : 'neutral'}
        />
        {workspaceLabel ? <StatusPill label={workspaceLabel} tone="accent" /> : null}
      </View>
      <View style={styles.promptRow}>
        {prompts.map((prompt) => (
          <Pressable key={prompt} onPress={() => setText(prompt)} style={styles.promptChip}>
            <Text style={styles.promptChipText}>{prompt}</Text>
          </Pressable>
        ))}
      </View>
      <TextInput
        multiline
        value={text}
        onChangeText={setText}
        placeholder={placeholder || 'Tell Axon what you want done.'}
        placeholderTextColor={colors.muted}
        style={[styles.input, { borderColor: colors.border, color: colors.text, backgroundColor: '#0b1627' }]}
      />
      <Pressable
        onPress={() => onSubmit(text.trim())}
        style={[styles.button, !text.trim() && styles.buttonDisabled]}
        disabled={!text.trim() || !!sending}
      >
        <Text style={styles.buttonText}>{sending ? 'Running...' : 'Run command'}</Text>
      </Pressable>
    </View>
  );
}

const styles = StyleSheet.create({
  stack: {
    gap: 12,
  },
  statusRow: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    gap: 8,
  },
  promptRow: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    gap: 8,
  },
  promptChip: {
    borderWidth: 1,
    borderColor: '#22304a',
    borderRadius: 999,
    paddingHorizontal: 12,
    paddingVertical: 8,
    backgroundColor: '#0b1627',
  },
  promptChipText: {
    color: '#cfe0f7',
    fontSize: 11,
    fontWeight: '600',
  },
  input: {
    minHeight: 104,
    borderWidth: 1,
    borderRadius: 16,
    paddingHorizontal: 14,
    paddingVertical: 12,
    fontSize: 15,
    textAlignVertical: 'top',
  },
  button: {
    borderRadius: 14,
    paddingVertical: 13,
    alignItems: 'center',
    backgroundColor: '#38bdf8',
  },
  buttonDisabled: {
    opacity: 0.55,
  },
  buttonText: {
    color: '#08111f',
    fontWeight: '800',
  },
});
