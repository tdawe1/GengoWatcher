import { createTheme } from "@mui/material";
import { useMemo } from "react";
import { useState } from "react";
import { createContext } from "react";

// Carbon Design System Color Palette - Kyros Branded
export const tokens = (mode: "light" | "dark") => ({
  ...(mode === "dark"
    ? {
        // Carbon Dark Theme colors
        gray: {
          10: "#ffffff",
          20: "#f4f4f4",
          30: "#e0e0e0",
          40: "#bababa",
          50: "#a8a8a8",
          60: "#8d8d8d",
          70: "#6f6f6f",
          80: "#525252",
          90: "#393939",
          100: "#262626",
        },
        // Kyros brand colors - Deep Purple/Indigo theme
        brand: {
          10: "#f6f6ff",
          20: "#e6e6ff",
          30: "#d1d1ff",
          40: "#b8b8ff",
          50: "#9999ff",
          60: "#7979ff",
          70: "#5c5cff",
          80: "#4141ff", // Primary brand
          90: "#2c2ce5",
          100: "#1a1ab3",
        },
        // Carbon UI colors
        blue: {
          10: "#edf5ff",
          20: "#d0e2ff",
          30: "#a6c8ff",
          40: "#78a9ff",
          50: "#4589ff",
          60: "#0f62fe",
          70: "#0043ce",
          80: "#002d9c",
          90: "#001d6c",
          100: "#001141",
        },
        // Success/Teal
        teal: {
          10: "#e5f6f5",
          20: "#c7ede9",
          30: "#9fe0d9",
          40: "#6ed4cd",
          50: "#3ac7c0",
          60: "#009d9a",
          70: "#007578",
          80: "#005356",
          90: "#00363a",
          100: "#001a1c",
        },
        // Warning/Orange
        orange: {
          10: "#fff8e5",
          20: "#ffe7b3",
          30: "#ffd380",
          40: "#ffbf4d",
          50: "#ffa726",
          60: "#ff8b00",
          70: "#cc6e00",
          80: "#995100",
          90: "#663500",
          100: "#401a00",
        },
        // Error/Red
        red: {
          10: "#fff1f0",
          20: "#ffd7d5",
          30: "#ffb3b0",
          40: "#ff8389",
          50: "#fa4d56",
          60: "#da1e28",
          70: "#a2191f",
          80: "#750e13",
          90: "#520408",
          100: "#2d0709",
        },
        // Purple accent
        purple: {
          10: "#f6f6ff",
          20: "#e6e6ff",
          30: "#d1d1ff",
          40: "#b8b8ff",
          50: "#9999ff",
          60: "#7979ff",
          70: "#5c5cff",
          80: "#4141ff",
          90: "#2c2ce5",
          100: "#1a1ab3",
        },
      }
    : {
        // Carbon Light Theme colors
        gray: {
          10: "#ffffff",
          20: "#f4f4f4",
          30: "#e0e0e0",
          40: "#bababa",
          50: "#a8a8a8",
          60: "#8d8d8d",
          70: "#6f6f6f",
          80: "#525252",
          90: "#393939",
          100: "#161616",
        },
        // Kyros brand colors - Light theme
        brand: {
          10: "#f6f6ff",
          20: "#e6e6ff",
          30: "#d1d1ff",
          40: "#b8b8ff",
          50: "#9999ff",
          60: "#7979ff",
          70: "#5c5cff",
          80: "#4141ff", // Primary brand
          90: "#2c2ce5",
          100: "#1a1ab3",
        },
        blue: {
          10: "#edf5ff",
          20: "#d0e2ff",
          30: "#a6c8ff",
          40: "#78a9ff",
          50: "#4589ff",
          60: "#0f62fe",
          70: "#0043ce",
          80: "#002d9c",
          90: "#001d6c",
          100: "#001141",
        },
        teal: {
          10: "#e5f6f5",
          20: "#c7ede9",
          30: "#9fe0d9",
          40: "#6ed4cd",
          50: "#3ac7c0",
          60: "#009d9a",
          70: "#007578",
          80: "#005356",
          90: "#00363a",
          100: "#001a1c",
        },
        orange: {
          10: "#fff8e5",
          20: "#ffe7b3",
          30: "#ffd380",
          40: "#ffbf4d",
          50: "#ffa726",
          60: "#ff8b00",
          70: "#cc6e00",
          80: "#995100",
          90: "#663500",
          100: "#401a00",
        },
        red: {
          10: "#fff1f0",
          20: "#ffd7d5",
          30: "#ffb3b0",
          40: "#ff8389",
          50: "#fa4d56",
          60: "#da1e28",
          70: "#a2191f",
          80: "#750e13",
          90: "#520408",
          100: "#2d0709",
        },
        purple: {
          10: "#f6f6ff",
          20: "#e6e6ff",
          30: "#d1d1ff",
          40: "#b8b8ff",
          50: "#9999ff",
          60: "#7979ff",
          70: "#5c5cff",
          80: "#4141ff",
          90: "#2c2ce5",
          100: "#1a1ab3",
        },
      }),
});

// Carbon Design System Theme Settings
export const themeSettings = (mode: "light" | "dark") => {
  const colors = tokens(mode);

  return {
    palette: {
      mode: mode,
      ...(mode === "dark"
        ? {
            // Dark theme using Carbon colors
            primary: {
              main: colors.brand[80],
              light: colors.brand[70],
              dark: colors.brand[90],
              contrastText: colors.gray[10],
            },
            secondary: {
              main: colors.blue[60],
              light: colors.blue[50],
              dark: colors.blue[70],
              contrastText: colors.gray[10],
            },
            background: {
              default: colors.gray[100],
              paper: colors.gray[90],
            },
            text: {
              primary: colors.gray[10],
              secondary: colors.gray[30],
              disabled: colors.gray[50],
            },
            action: {
              active: colors.brand[80],
              hover: colors.brand[70],
              selected: colors.brand[80],
              disabled: colors.gray[60],
              disabledBackground: colors.gray[80],
            },
            divider: colors.gray[80],
            info: {
              main: colors.blue[60],
              light: colors.blue[40],
              dark: colors.blue[70],
            },
            success: {
              main: colors.teal[60],
              light: colors.teal[40],
              dark: colors.teal[70],
            },
            warning: {
              main: colors.orange[60],
              light: colors.orange[40],
              dark: colors.orange[70],
            },
            error: {
              main: colors.red[60],
              light: colors.red[40],
              dark: colors.red[70],
            },
          }
        : {
            // Light theme using Carbon colors
            primary: {
              main: colors.brand[80],
              light: colors.brand[70],
              dark: colors.brand[90],
              contrastText: colors.gray[10],
            },
            secondary: {
              main: colors.blue[60],
              light: colors.blue[50],
              dark: colors.blue[70],
              contrastText: colors.gray[10],
            },
            background: {
              default: colors.gray[10],
              paper: colors.gray[20],
            },
            text: {
              primary: colors.gray[100],
              secondary: colors.gray[80],
              disabled: colors.gray[50],
            },
            action: {
              active: colors.brand[80],
              hover: colors.brand[70],
              selected: colors.brand[80],
              disabled: colors.gray[40],
              disabledBackground: colors.gray[20],
            },
            divider: colors.gray[30],
            info: {
              main: colors.blue[60],
              light: colors.blue[40],
              dark: colors.blue[70],
            },
            success: {
              main: colors.teal[60],
              light: colors.teal[40],
              dark: colors.teal[70],
            },
            warning: {
              main: colors.orange[60],
              light: colors.orange[40],
              dark: colors.orange[70],
            },
            error: {
              main: colors.red[60],
              light: colors.red[40],
              dark: colors.red[70],
            },
          }),
    },
    typography: {
      // Carbon Typography - IBM Plex Sans
      fontFamily: '"IBM Plex Sans", "Helvetica Neue", Arial, sans-serif',
      fontSize: 16,
      h1: {
        fontSize: "2.5rem",
        fontWeight: 300,
        lineHeight: 1.25,
        letterSpacing: "-0.01em",
      },
      h2: {
        fontSize: "2rem",
        fontWeight: 400,
        lineHeight: 1.25,
        letterSpacing: "-0.01em",
      },
      h3: {
        fontSize: "1.75rem",
        fontWeight: 400,
        lineHeight: 1.25,
        letterSpacing: "-0.01em",
      },
      h4: {
        fontSize: "1.5rem",
        fontWeight: 400,
        lineHeight: 1.25,
        letterSpacing: "-0.01em",
      },
      h5: {
        fontSize: "1.25rem",
        fontWeight: 400,
        lineHeight: 1.25,
        letterSpacing: "-0.01em",
      },
      h6: {
        fontSize: "1.125rem",
        fontWeight: 500,
        lineHeight: 1.25,
        letterSpacing: "-0.01em",
      },
      subtitle1: {
        fontSize: "1rem",
        fontWeight: 400,
        lineHeight: 1.5,
        letterSpacing: "0.16px",
      },
      subtitle2: {
        fontSize: "0.875rem",
        fontWeight: 500,
        lineHeight: 1.4,
        letterSpacing: "0.16px",
      },
      body1: {
        fontSize: "1rem",
        fontWeight: 400,
        lineHeight: 1.5,
        letterSpacing: "0.16px",
      },
      body2: {
        fontSize: "0.875rem",
        fontWeight: 400,
        lineHeight: 1.4,
        letterSpacing: "0.16px",
      },
      button: {
        fontSize: "0.875rem",
        fontWeight: 500,
        lineHeight: 1.4,
        letterSpacing: "0.32px",
        textTransform: "none" as const,
      },
      caption: {
        fontSize: "0.75rem",
        fontWeight: 400,
        lineHeight: 1.3,
        letterSpacing: "0.32px",
      },
      overline: {
        fontSize: "0.625rem",
        fontWeight: 500,
        lineHeight: 1.2,
        letterSpacing: "1.6px",
        textTransform: "uppercase" as const,
      },
    },
    shape: {
      borderRadius: 0, // Carbon has sharp corners by default
    },
    components: {
      // Carbon Component Styles
      MuiButton: {
        styleOverrides: {
          root: {
            borderRadius: 0,
            textTransform: "none",
            fontWeight: 500,
            padding: "11px 32px",
            boxShadow: "none",
            variants: [],
            "&:hover": {
              boxShadow: "none",
            },
            "&.Mui-disabled": {
              backgroundColor: mode === "dark" ? colors.gray[80] : colors.gray[20],
              color: mode === "dark" ? colors.gray[50] : colors.gray[40],
            },
          },
          contained: {
            "&:hover": {
              backgroundColor: colors.brand[70],
            },
          },
          outlined: {
            borderWidth: "2px",
            "&:hover": {
              borderWidth: "2px",
            },
          },
        },
      },
      MuiTextField: {
        styleOverrides: {
          root: {
            "& .MuiOutlinedInput-root": {
              borderRadius: 0,
              "&:hover .MuiOutlinedInput-notchedOutline": {
                borderColor: colors.brand[80],
              },
              "&.Mui-focused .MuiOutlinedInput-notchedOutline": {
                borderColor: colors.brand[80],
                borderWidth: "2px",
              },
            },
            "& .MuiInputLabel-root": {
              "&.Mui-focused": {
                color: colors.brand[80],
              },
            },
          },
        },
      },
      MuiCard: {
        styleOverrides: {
          root: {
            borderRadius: 0,
            boxShadow: "none",
            border: `1px solid ${colors.gray[70]}`,
            backgroundColor: mode === "dark" ? colors.gray[90] : colors.gray[10],
          },
        },
      },
      MuiPaper: {
        styleOverrides: {
          root: {
            borderRadius: 0,
            backgroundColor: mode === "dark" ? colors.gray[90] : colors.gray[10],
          },
        },
      },
      MuiChip: {
        styleOverrides: {
          root: {
            borderRadius: "16px",
            fontWeight: 500,
            height: "32px",
          },
        },
      },
      MuiTabs: {
        styleOverrides: {
          indicator: {
            backgroundColor: colors.brand[80],
            height: "3px",
          },
        },
      },
      MuiTab: {
        styleOverrides: {
          root: {
            textTransform: "none",
            fontWeight: 500,
            minWidth: "auto",
            padding: "12px 24px",
            variants: [],
            "&.Mui-selected": {
              color: colors.brand[80],
            },
          },
        },
      },
      MuiDrawer: {
        styleOverrides: {
          paper: {
            borderRight: `1px solid ${colors.gray[70]}`,
            backgroundColor: mode === "dark" ? colors.gray[90] : colors.gray[10],
          },
        },
      },
      MuiListItemIcon: {
        styleOverrides: {
          root: {
            minWidth: "40px",
            color: mode === "dark" ? colors.gray[40] : colors.gray[70],
          },
        },
      },
      MuiListItemText: {
        styleOverrides: {
          primary: {
            fontSize: "1rem",
            fontWeight: 400,
          },
        },
      },
      MuiAppBar: {
        styleOverrides: {
          root: {
            boxShadow: "none",
            borderBottom: `1px solid ${colors.gray[70]}`,
            backgroundColor: mode === "dark" ? colors.gray[90] : colors.gray[10],
          },
        },
      },
      MuiToolbar: {
        styleOverrides: {
          root: {
            minHeight: "48px",
            paddingLeft: "24px",
            paddingRight: "24px",
          },
        },
      },
    },
    transitions: {
      duration: {
        shortest: 150,
        shorter: 200,
        short: 250,
        standard: 300,
        complex: 375,
        enteringScreen: 225,
        leavingScreen: 195,
      },
      easing: {
        easeInOut: "cubic-bezier(0.4, 0, 0.2, 1)",
        easeOut: "cubic-bezier(0, 0, 0.2, 1)",
        easeIn: "cubic-bezier(0.4, 0, 1, 1)",
        sharp: "cubic-bezier(0.4, 0, 0.6, 1)",
      },
    },
    spacing: 8,
    zIndex: {
      mobileStepper: 1000,
      speedDial: 1050,
      appBar: 1100,
      drawer: 1200,
      modal: 1300,
      snackbar: 1400,
      tooltip: 1500,
    },
  };
};

// Context For Color Mode
export const ColorModeContext = createContext({
  toggleColorMode: () => {},
});

export const useMode = () => {
  const [mode, setMode] = useState<"light" | "dark">("dark");

  const colorMode = useMemo(() => ({
    toggleColorMode: () =>
      setMode((prev) => (prev === "light" ? "dark" : "light")),
  }), []);

  const theme = useMemo(() => createTheme(themeSettings(mode)), [mode]);

  return [theme, colorMode] as const;
};