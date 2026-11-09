# Shifter Design System: Foundation Artifacts

This reference explains the framework-neutral examples produced for
[#1299](https://github.com/Brad-Edwards/bigrae/issues/1299).
The [foundation design](../spa-design-system-foundation-1299.md) records tokens, components, states, accessibility targets, Django coexistence, and the migration map.

This directory contains example tokens, component styles, and an HTML style guide.
It is not the current portal stylesheet.
The SPA loads `frontend/src/index.css` through `frontend/src/main.tsx` under `shifter/shifter_platform/`.
Source inspection did not establish product consumption of these example assets.

## Files

| File | Purpose |
| --- | --- |
| `tokens.css` | Example CSS custom properties, primitive scales, and semantic tokens; dark and light themes; reduced-motion rules |
| `components.css` | Framework-neutral `.ds-*` component classes that use the example token contract |
| `index.html` | HTML examples with a theme toggle and component states |
| `styleguide.css` | Style-guide page layout |
| `styleguide.js` | External theme-toggle script |

## Viewing the style guide

The example needs no build step.
Open `index.html` directly, or serve the directory:

```bash
cd docs/design/design-system
python3 -m http.server 8791
# open http://localhost:8791/index.html
```

Use the header toggle to preview light and dark themes.
Use Tab to inspect focus states.
These examples do not establish the shipping portal's accessibility conformance.

## Consuming the tokens

Load `tokens.css` first, then `components.css`, then app/surface CSS:

```html
<link rel="stylesheet" href="tokens.css" />
<link rel="stylesheet" href="components.css" />
```

The foundation contract requires components to reference **semantic** tokens, such as `--ds-color-accent` and `--ds-space-4`.
They must not reference raw ramps, such as `--ds-blue-500` and `--ds-neutral-900`, or literal values.
This contract separates component rules from token values.

## Reskinning

To change the example appearance, edit the **semantic** values in `tokens.css`.
The dark values use `:root`; the light values use the two light-theme blocks.
Keep raw ramps when only the mapping changes.
Add or replace ramp values for a new palette.
Repeat the foundation document's contrast check before claiming AA.

## Status

These artifacts preserve the stack-neutral foundation design.
[#1300](https://github.com/Brad-Edwards/bigrae/issues/1300) owned framework selection.
The foundation's migration map describes its original portal baseline.
It does not prove that the current portal uses these tokens or that every example meets AA.
