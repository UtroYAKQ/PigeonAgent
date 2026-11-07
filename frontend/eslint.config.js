import js from '@eslint/js'
import pluginVue from 'eslint-plugin-vue'
import tseslint from 'typescript-eslint'

export default tseslint.config(
  { ignores: ['dist/**', 'node_modules/**'] },
  js.configs.recommended,
  ...tseslint.configs.recommended,
  ...pluginVue.configs['flat/essential'],
  {
    files: ['**/*.vue'],
    languageOptions: {
      parserOptions: {
        parser: tseslint.parser,
        extraFileExtensions: ['.vue'],
      },
    },
    rules: {
      'vue/multi-word-component-names': 'off',
    },
  },
  {
    files: ['**/*.{ts,vue}'],
    rules: {
      'no-undef': 'off',
      'no-console': 'off',
      '@typescript-eslint/no-explicit-any': 'off',
      '@typescript-eslint/no-unused-vars': [
        'warn',
        { argsIgnorePattern: '^_', varsIgnorePattern: '^_' },
      ],
      'vue/no-v-html': 'off',
      // 新文件超过 500 行就该拆；存量大的先豁免，改到哪拆到哪。
      'max-lines': ['error', { max: 500, skipBlankLines: true, skipComments: true }],
    },
  },
  {
    files: [
      'src/stores/chat/index.ts',
      'src/lib/turnModel.ts',
      'src/components/admin/ModelManagerPanel.vue',
      'src/components/admin/ImageModelManagerPanel.vue',
      'src/components/admin/UserManagementPanel.vue',
      'src/components/chat/AppSidebar.vue',
      'src/components/chat/Composer.vue',
      '**/*.test.ts',
    ],
    rules: {
      'max-lines': 'off',
    },
  },
  {
    files: ['src/components/ai-elements/**/*.vue'],
    rules: {
      '@typescript-eslint/no-empty-object-type': 'off',
    },
  },
  {
    files: ['src/lib/format.ts'],
    rules: {
      'no-control-regex': 'off',
    },
  },
  {
    files: ['src/types/*.d.ts'],
    rules: {
      'no-var': 'off',
    },
  },
)
