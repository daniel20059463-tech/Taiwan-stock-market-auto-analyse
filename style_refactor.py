import re
import os

filepath = r"src/components/Dashboard.tsx"

with open(filepath, "r", encoding="utf-8") as f:
    text = f.read()

# Replace border-radius everywhere
text = re.sub(r'borderRadius:\s*"\d+px"', 'borderRadius: "0px"', text)
text = re.sub(r'borderRadius:\s*"999px"', 'borderRadius: "0px"', text)

# Replace gradients in panels
text = re.sub(r'background:\s*"linear-gradient\(180deg,\s*rgba\(18,32,51,0\.92\),\s*rgba\(11,22,37,0\.96\)\)"', 'background: "var(--bg-panel)"', text)
text = re.sub(r'background:\s*"linear-gradient\(180deg,\s*rgba\(13,24,40,0\.96\),\s*rgba\(9,18,31,0\.98\)\)"', 'background: "var(--bg-panel)"', text)

# Update inputs and select background
text = re.sub(r'background:\s*"rgba\(18,\s*32,\s*51,\s*0\.88\)"', 'background: "var(--bg-card)"', text)

# Update MetricCard styles
text = re.sub(r'background:\s*"rgba\(255,255,255,0\.03\)"', 'background: "var(--bg-card)"', text)
text = re.sub(r'border:\s*"1px solid rgba\(143, 164, 184, 0\.08\)"', 'border: "1px solid var(--border-strong)"', text)

# Box shadow for neo brutalism
text = re.sub(r'boxShadow:\s*"0 18px 60px rgba\(0, 0, 0, 0\.28\)"', 'boxShadow: "4px 4px 0px var(--accent-blue)"', text)

# Change border from palette.border to --border-strong
text = re.sub(r'border:\s*`1px solid \$\{palette\.border\}`', 'border: `1px solid var(--border-strong)`', text)

# Chart Mode buttons
text = re.sub(r'background: chartMode === "live" \? "rgba\(56, 189, 248, 0\.16\)" : "transparent"', 'background: chartMode === "live" ? "var(--accent-blue)" : "var(--bg-card)"', text)
text = re.sub(r'background: chartMode === "history" \? "rgba\(245, 158, 11, 0\.16\)" : "transparent"', 'background: chartMode === "history" ? "var(--accent-gold)" : "var(--bg-card)"', text)

text = re.sub(r'color: chartMode === "live" \? palette\.accent : palette\.text', 'color: chartMode === "live" ? "var(--bg-dark)" : "var(--text-primary)"', text)
text = re.sub(r'color: chartMode === "history" \? palette\.warning : palette\.text', 'color: chartMode === "history" ? "var(--bg-dark)" : "var(--text-primary)"', text)

# Indicator buttons
text = re.sub(r'background: indicatorVisibility\[key\] \? \`\$\{color\}22\` \: "rgba\(255,255,255,0\.02\)"', 'background: indicatorVisibility[key] ? color : "var(--bg-card)"', text)
text = re.sub(r'color: indicatorVisibility\[key\] \? color \: palette\.muted', 'color: indicatorVisibility[key] ? "var(--bg-dark)" : "var(--text-muted)"', text)

# Metric card shadows
text = re.sub(r'fontWeight:\s*700\s*\}\}\>\{value\}\<\/div\>', r'fontWeight: 700, textShadow: `0 0 8px ${tone}66` }}>{value}</div>', text)

# Lightweight charts options
# Grid lines
text = re.sub(r'vertLines:\s*\{\s*color:\s*"rgba\(143, 164, 184, 0\.02\)"\s*\}', r'vertLines: { color: "var(--border-subtle)" }', text)
text = re.sub(r'horzLines:\s*\{\s*color:\s*"rgba\(143, 164, 184, 0\.08\)"\s*\}', r'horzLines: { color: "var(--border-subtle)" }', text)
text = re.sub(r'horzLines:\s*\{\s*color:\s*"rgba\(143, 164, 184, 0\.04\)"\s*\}', r'horzLines: { color: "var(--border-subtle)" }', text)

# Chart colors
text = re.sub(r'upColor:\s*palette\.success', r'upColor: "var(--success-green)"', text)
text = re.sub(r'downColor:\s*palette\.danger', r'downColor: "transparent"', text)
text = re.sub(r'borderUpColor:\s*palette\.success', r'borderUpColor: "var(--success-green)"', text)
text = re.sub(r'borderDownColor:\s*palette\.danger', r'borderDownColor: "var(--danger-red)"', text)
text = re.sub(r'wickUpColor:\s*palette\.success', r'wickUpColor: "var(--success-green)"', text)
text = re.sub(r'wickDownColor:\s*palette\.danger', r'wickDownColor: "var(--danger-red)"', text)

text = re.sub(r'color:\s*"#1f6fff"', r'color: "var(--accent-blue)"', text)

with open(filepath, "w", encoding="utf-8") as f:
    f.write(text)

print("Replacement done.")
