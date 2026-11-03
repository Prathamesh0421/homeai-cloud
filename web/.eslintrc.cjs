// ESLint 8 config for the SPA (Vite React + TypeScript defaults, matching the devDependencies).
// react-refresh/only-export-components is left out: providers export their hooks
// (useAuth etc.), which only affects dev hot-reload, not correctness.
module.exports = {
  root: true,
  env: { browser: true, es2020: true },
  extends: [
    'eslint:recommended',
    'plugin:@typescript-eslint/recommended',
    'plugin:react-hooks/recommended',
  ],
  ignorePatterns: ['dist', 'coverage', '.eslintrc.cjs'],
  parser: '@typescript-eslint/parser',
  // Listing the extensions here makes `eslint src` (no --ext) lint .ts/.tsx files.
  overrides: [{ files: ['**/*.ts', '**/*.tsx'] }],
};
