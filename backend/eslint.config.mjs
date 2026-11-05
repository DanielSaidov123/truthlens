import tseslint from "typescript-eslint";

export default tseslint.config(
  {
    ignores: ["dist/**", "node_modules/**", "prisma/migrations/**"],
  },
  ...tseslint.configs.recommended,
  {
    files: ["src/**/*.ts", "tests/**/*.ts"],
    rules: {
      "@typescript-eslint/no-unused-vars": ["error", { argsIgnorePattern: "^_" }],
    },
  },
);
