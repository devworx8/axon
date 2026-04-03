import React from 'react';
import { StatusBar } from 'expo-status-bar';
import { SafeAreaView, StyleSheet, View } from 'react-native';

import { AppNavigator } from '@/navigation/AppNavigator';
import { ThemeProvider } from '@/theme/ThemeProvider';

export default function App() {
  return (
    <ThemeProvider>
      <SafeAreaView style={styles.safeArea}>
        <View style={styles.root}>
          <StatusBar style="light" />
          <AppNavigator />
        </View>
      </SafeAreaView>
    </ThemeProvider>
  );
}

const styles = StyleSheet.create({
  safeArea: {
    flex: 1,
    backgroundColor: '#08111f',
  },
  root: {
    flex: 1,
    backgroundColor: '#08111f',
  },
});

