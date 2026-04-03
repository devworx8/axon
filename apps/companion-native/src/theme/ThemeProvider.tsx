import React, { createContext, useContext, type PropsWithChildren } from 'react';

import { colors } from './index';

const ThemeContext = createContext({ colors });

export function ThemeProvider({ children }: PropsWithChildren) {
  return <ThemeContext.Provider value={{ colors }}>{children}</ThemeContext.Provider>;
}

export function useTheme() {
  return useContext(ThemeContext);
}

