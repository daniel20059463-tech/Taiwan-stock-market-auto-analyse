import re

filepath = "src/components/Dashboard.tsx"

with open(filepath, "r", encoding="utf-8") as f:
    text = f.read()

# 1. Update Palette
text = re.sub(
    r"const palette = \{ panel: '#1a1a1c', border: '#333333', text: '#f0f0f0', muted: '#8c8c8c', success: '#00e676', warning: '#d4af37', danger: '#ff3366', accent: '#00f5ff', volume: '#4facfe', \};",
    "const palette = { panel: '#08080a', border: '#f0f0f0', text: '#ffffff', muted: '#a1a1aa', success: '#00ff66', warning: '#ffea00', danger: '#ff0055', accent: '#00f5ff', volume: '#bd00ff', };",
    text
)

# 2. shellStyle
text = re.sub(
    r"const shellStyle: CSSProperties = \{ minHeight: '100vh', color: palette.text, background: '#121212', padding: '24px', fontFamily: 'var\(--font-sans\)' \};",
    "const shellStyle: CSSProperties = { minHeight: '100vh', color: palette.text, background: '#000000', padding: '24px', fontFamily: 'var(--font-sans)', display: 'flex', flexDirection: 'column', gap: '18px' };",
    text
)

# 3. All border 1px solid #333333 -> 2px solid var(--border-strong)
text = re.sub(r'border: 1px solid #333333', 'border: "2px solid #f0f0f0"', text)
text = re.sub(r'border: `1px solid #333333`', 'border: `2px solid #f0f0f0`', text)
text = re.sub(r'border:\s*"1px solid #333333"', 'border: "2px solid #f0f0f0"', text)
text = re.sub(r'borderBottom: `1px solid #333333`', 'borderBottom: `2px solid #f0f0f0`', text)

# 4. textShadows are not Neo-Brutalist
text = re.sub(r'textShadow:\s*`[\w\s\$#]*`', 'textShadow: "none"', text)

# 5. Backgrounds rgba to solid
text = re.sub(r'background:\s*"rgba\(255,255,255,0\.03\)"', 'background: "#08080a"', text)
text = re.sub(r'background:\s*"rgba\(255,255,255,0\.02\)"', 'background: "#000000"', text)
text = re.sub(r'background:\s*"#1a1a1c"', 'background: "#08080a"', text)

# 6. Buttons and Dropdowns shadows
# specifically find button styles
text = re.sub(r'padding: "10px 14px",\n\s*cursor: "pointer",', 'padding: "10px 14px",\n                      cursor: "pointer",\n                      boxShadow: "3px 3px 0px 0px #f0f0f0",', text)

# 7. Panel Component
text = re.sub(
    r'function Panel\(\{ title, children \}: \{ title: string; children: ReactNode \}\) \{\n  return \(\n    <section\n      style=\{\{\n        border: `2px solid #f0f0f0`,\n        borderRadius: "0px",\n        background: "#08080a",\n        padding: "18px",\n      \}\}',
    """function Panel({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section
      style={{
        border: `2px solid #f0f0f0`,
        borderRadius: "0px",
        background: "#08080a",
        padding: "18px",
        boxShadow: "4px 4px 0px 0px var(--accent-blue)",
      }}""",
    text
)

# 8. MetricCard Component
text = re.sub(
    r'function MetricCard\(\{ label, value, tone \}: \{ label: string; value: string; tone: string \}\) \{\n  return \(\n    <div\n      style=\{\{\n        padding: "12px 14px",\n        borderRadius: "0px",\n        border: "2px solid #f0f0f0",\n        background: "#08080a",\n      \}\}\n    \>\n      <div style=\{\{ color: palette\.muted, fontSize: "12px", marginBottom: "6px", textTransform: "uppercase", letterSpacing: "0\.08em" \}\}>\n        \{label\}\n      \<\/div\>\n      <div style=\{\{ \.\.\.marketNumbers, color: tone, fontSize: "18px", fontWeight: 700, textShadow: "none" \}\}>\{value\}\<\/div\>',
    """function MetricCard({ label, value, tone }: { label: string; value: string; tone: string }) {
  return (
    <div
      style={{
        padding: "12px 14px",
        borderRadius: "0px",
        border: "2px solid #f0f0f0",
        background: "#08080a",
        boxShadow: `4px 4px 0px 0px ${tone}`,
      }}
    >
      <div style={{ color: palette.muted, fontSize: "12px", marginBottom: "6px", textTransform: "uppercase", letterSpacing: "0.08em", fontWeight: 800 }}>
        {label}
      </div>
      <div style={{ ...marketNumbers, color: tone, fontSize: "20px", fontWeight: 900 }}>{value}</div>""",
    text
)

# 9. Main top board box shadow is already there, but let's confirm
text = re.sub(r'boxShadow: "4px 4px 0px #00f5ff"', 'boxShadow: "4px 4px 0px 0px var(--accent-volume)"', text)

with open(filepath, "w", encoding="utf-8") as f:
    f.write(text)

print("success")
