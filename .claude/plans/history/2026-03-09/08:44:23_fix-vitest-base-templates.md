# Fix incomplete vitest support across base templates

## Context

The `ts_test_framework` option (node:test vs vitest) was added in commit `5840570`, and the child template (`children/typescript/`) correctly handles it — `package.json` has conditional `test` script and devDependencies, test files use the right imports, and `vitest.config.ts` is conditionally generated.

However, several **base template files** still hardcode `node:test` behavior and ignore the vitest option.

## Changes

### 1. `template/README.md.jinja` (lines 40-57)

The TypeScript section hardcodes `node --experimental-strip-types --test tests/index.test.ts`. Make it conditional:

```jinja
{% elif language == 'typescript' %}
### Install Dependencies

```bash
npm install
```

### Run Tests

```bash
{% if ts_test_framework == 'vitest' -%}
npx vitest run
{%- else -%}
node --experimental-strip-types --test tests/index.test.ts
{%- endif %}
```

### Build

```bash
npx tsc
```
```

### 2. `template/.agents/instructions/AGENTS.md.jinja` (lines 38-46)

The TypeScript section hardcodes `node --experimental-strip-types --test`. Make the test command conditional:

```jinja
- Run tests: {% if ts_test_framework == 'vitest' %}`npx vitest run`{% else %}`node --experimental-strip-types --test tests/index.test.ts`{% endif %}
```

### 3. `template/.config/hk.pkl.jinja` (lines 73-84, 109-111)

Add a `tests` mapping for TypeScript and include it in the `check` hook:

After the TypeScript linters block (~line 84), add:
```pkl
local tests = new Mapping<String, Step> {
{% if ts_test_framework == 'vitest' %}
  ["vitest"] {
    glob = List("**/*.ts")
    check = "npx vitest run"
  }
{% else %}
  ["node_test"] {
    glob = List("**/*.ts")
    check = "node --experimental-strip-types --test tests/index.test.ts"
  }
{% endif %}
}
```

Update the check hook's tests spread (line 109) to include TypeScript:
```jinja
{%- if language in ['python', 'shell', 'typescript'] %}
      ...tests
{%- endif %}
```

## Files to modify

- `template/README.md.jinja`
- `template/.agents/instructions/AGENTS.md.jinja`
- `template/.config/hk.pkl.jinja`

## Verification

1. Generate a project with `language=typescript, ts_test_framework=vitest` and verify:
   - README shows `npx vitest run`
   - AGENTS.md shows `npx vitest run`
   - hk.pkl has vitest test step in check hook
2. Generate a project with `language=typescript, ts_test_framework=node` and verify:
   - README shows `node --experimental-strip-types --test`
   - AGENTS.md shows `node --experimental-strip-types --test`
   - hk.pkl has node_test step in check hook
3. Generate a non-TypeScript project and verify no regressions
