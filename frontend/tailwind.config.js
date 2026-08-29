/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{js,ts,jsx,tsx}"],
  theme: {
    extend: {
      colors: {
        ink: "#0B1220",
        panel: "#101B2D",
        panel2: "#0E1729",
        border: "#1E2C45",
        accent: "#4F8AF4",
        recovered: "#33C48D",
        atrisk: "#F2A649",
        blocked: "#E5484D",
        pending: "#8B7FF2",
        muted: "#64748B",
      },
      fontFamily: {
        mono: ["ui-monospace", "SFMono-Regular", "Menlo", "monospace"],
      },
    },
  },
  plugins: [],
};
