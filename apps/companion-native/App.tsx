import React from 'react';
import { StatusBar } from 'expo-status-bar';
import { StyleSheet, View } from 'react-native';
import { SafeAreaProvider, SafeAreaView } from 'react-native-safe-area-context';

import { AppNavigator } from '@/navigation/AppNavigator';
import { ErrorBoundary } from '@/components/ErrorBoundary';
import { ThemeProvider } from '@/theme/ThemeProvider';

export default function App() {
  return (
    <SafeAreaProvider>
      <ErrorBoundary>
        <ThemeProvider>
          <SafeAreaView style={styles.safeArea} edges={['top', 'left', 'right']}>
            <View style={styles.root}>
              <StatusBar style="light" />
              <AppNavigator />
            </View>
          </SafeAreaView>
        </ThemeProvider>
      </ErrorBoundary>
    </SafeAreaProvider>
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
