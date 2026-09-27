/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{js,jsx}"],
  theme: {
    extend: {
      colors: {
        base: "#090d16",
        panel: "#0f1420",
        panel2: "#141a29",
        border: "#212a3d",
        accent: {
          blue: "#5b8cff",
          purple: "#9b7bff",
        },
      },
      fontFamily: {
        mono: ["JetBrains Mono", "Fira Code", "ui-monospace", "SFMono-Regular", "monospace"],
        sans: ["Inter", "ui-sans-serif", "system-ui", "sans-serif"],
      },
      boxShadow: {
        glow: "0 0 0 1px rgba(91,140,255,0.15), 0 0 24px rgba(91,140,255,0.08)",
      },
    },
  },
  plugins: [],
};
