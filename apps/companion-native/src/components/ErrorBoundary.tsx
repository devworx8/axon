import React from 'react';
import { View, Text, Pressable, StyleSheet } from 'react-native';

type ErrorBoundaryProps = {
  children: React.ReactNode;
  fallback?: React.ReactNode;
};

type ErrorBoundaryState = {
  hasError: boolean;
  error: Error | null;
};

/**
 * Global error boundary — catches unhandled render errors and shows
 * a JARVIS-style recovery screen instead of crashing the app.
 */
export class ErrorBoundary extends React.Component<ErrorBoundaryProps, ErrorBoundaryState> {
  constructor(props: ErrorBoundaryProps) {
    super(props);
    this.state = { hasError: false, error: null };
  }

  static getDerivedStateFromError(error: Error): ErrorBoundaryState {
    return { hasError: true, error };
  }

  componentDidCatch(error: Error, info: React.ErrorInfo) {
    console.error('[Axon] Unhandled render error:', error, info.componentStack);
  }

  private handleRestart = () => {
    this.setState({ hasError: false, error: null });
  };

  render() {
    if (this.state.hasError) {
      if (this.props.fallback) return this.props.fallback;

      return (
        <View style={styles.container}>
          <View style={styles.card}>
            <Text style={styles.icon}>{'///'}</Text>
            <Text style={styles.title}>System Fault Detected</Text>
            <Text style={styles.message}>
              I appear to have encountered a fault, sir.{'\n'}
              Shall we try again?
            </Text>
            {this.state.error && (
              <Text style={styles.detail} numberOfLines={3}>
                {this.state.error.message}
              </Text>
            )}
            <Pressable
              style={styles.button}
              onPress={this.handleRestart}
              accessibilityRole="button"
              accessibilityLabel="Restart Axon"
            >
              <Text style={styles.buttonText}>Restart</Text>
            </Pressable>
          </View>
        </View>
      );
    }

    return this.props.children;
  }
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: '#0a0e17',
    alignItems: 'center',
    justifyContent: 'center',
    padding: 24,
  },
  card: {
    backgroundColor: 'rgba(15, 23, 42, 0.85)',
    borderWidth: 1,
    borderColor: 'rgba(239, 68, 68, 0.3)',
    borderRadius: 16,
    padding: 32,
    alignItems: 'center',
    maxWidth: 360,
    width: '100%',
  },
  icon: {
    fontSize: 32,
    color: '#ef4444',
    fontWeight: '700',
    marginBottom: 16,
    fontFamily: 'monospace',
  },
  title: {
    fontSize: 20,
    fontWeight: '700',
    color: '#e2e8f0',
    marginBottom: 8,
    textAlign: 'center',
  },
  message: {
    fontSize: 15,
    color: '#94a3b8',
    textAlign: 'center',
    lineHeight: 22,
    marginBottom: 16,
  },
  detail: {
    fontSize: 12,
    color: '#64748b',
    fontFamily: 'monospace',
    textAlign: 'center',
    marginBottom: 20,
    paddingHorizontal: 8,
  },
  button: {
    backgroundColor: '#38bdf8',
    paddingHorizontal: 32,
    paddingVertical: 12,
    borderRadius: 8,
  },
  buttonText: {
    color: '#0a0e17',
    fontSize: 16,
    fontWeight: '700',
  },
});
