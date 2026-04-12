/** @type {import('tailwindcss').Config} */
// Paths are relative to this file (Tailwind v3).
module.exports = {
  darkMode: "class",
  content: ["../../views/templates/**/*.html", "../js/**/*.js"],
  theme: {
    extend: {
      colors: {
        brand: "#1a73e8",
      },
    },
  },
  plugins: [],
};
