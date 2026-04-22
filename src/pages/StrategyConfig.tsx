import { useState, type ChangeEvent, type CSSProperties, type ReactNode } from "react";

const palette = {
  bg: "#121212",
  panel: "#1a1a1c",
  border: "#333333",
  text: "#f0f0f0",
  muted: "#8c8c8c",
  accent: "#00f5ff",
  success: "#00e676",
  warning: "#d4af37",
};

const mono: CSSProperties = { fontFamily: "var(--font-mono)" };

interface StrategySettings {
  newsEventWeight: number;
  sentimentWeight: number;
  technicalWeight: number;
  entryScoreThreshold: number;
  nearHighRatio: number;
  minVolumeRatio: number;
  positionSizeTwd: number;
  maxPositions: number;
  fastEntryEnabled: boolean;
  fastEntryDecayMs: number;
  dailyLossLimitTwd: number;
  rolling5DayLimitPct: number;
  trailStopAtrMult: number;
  atrPeriod: number;
  marketHaltPct: number;
  allowShort: boolean;
  eodAutoFlat: boolean;
  maxSinglePosSizePct: number;
}

const DEFAULT_SETTINGS: StrategySettings = {
  newsEventWeight: 50,
  sentimentWeight: 30,
  technicalWeight: 60,
  entryScoreThreshold: 60,
  nearHighRatio: 0.9,
  minVolumeRatio: 1.5,
  positionSizeTwd: 100_000,
  maxPositions: 5,
  fastEntryEnabled: true,
  fastEntryDecayMs: 3000,
  dailyLossLimitTwd: -10_000,
  rolling5DayLimitPct: 5,
  trailStopAtrMult: 2,
  atrPeriod: 14,
  marketHaltPct: -1.5,
  allowShort: true,
  eodAutoFlat: true,
  maxSinglePosSizePct: 30,
};

function Section({ children, title }: { children: ReactNode; title: string }) {
  return (
    <section style={{ background: palette.panel, border: `1px solid ${palette.border}`, padding: "18px" }}>
      <div style={{ color: palette.muted, fontSize: "18px", letterSpacing: "0.1em", textTransform: "uppercase", marginBottom: "14px" }}>
        {title}
      </div>
      {children}
    </section>
  );
}

function SliderRow({
  format,
  hint,
  label,
  max,
  min,
  onChange,
  step,
  value,
}: {
  format: (value: number) => string;
  hint: string;
  label: string;
  max: number;
  min: number;
  onChange: (value: number) => void;
  step: number;
  value: number;
}) {
  return (
    <div style={{ marginBottom: "16px" }}>
      <div style={{ display: "flex", justifyContent: "space-between", gap: "12px", marginBottom: "6px" }}>
        <span>{label}</span>
        <span style={{ color: palette.accent, ...mono }}>{format(value)}</span>
      </div>
      <input
        type="range"
        min={min}
        max={max}
        step={step}
        value={value}
        onChange={(event) => onChange(Number(event.target.value))}
        style={{ width: "100%", accentColor: palette.accent }}
      />
      <div style={{ marginTop: "4px", color: palette.muted, fontSize: "18px" }}>{hint}</div>
    </div>
  );
}

function NumberRow({
  hint,
  label,
  onChange,
  step,
  suffix,
  value,
}: {
  hint: string;
  label: string;
  onChange: (value: number) => void;
  step: number;
  suffix?: string;
  value: number;
}) {
  return (
    <div style={{ marginBottom: "14px" }}>
      <label style={{ display: "block", marginBottom: "4px" }}>{label}</label>
      <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
        <input
          type="number"
          step={step}
          value={value}
          onChange={(event: ChangeEvent<HTMLInputElement>) => onChange(Number(event.target.value))}
          style={{ width: "140px", padding: "8px 10px", background: "rgba(255,255,255,0.05)", border: `1px solid ${palette.border}`, color: palette.text, ...mono }}
        />
        {suffix && <span style={{ color: palette.muted, fontSize: "18px" }}>{suffix}</span>}
      </div>
      <div style={{ marginTop: "4px", color: palette.muted, fontSize: "18px" }}>{hint}</div>
    </div>
  );
}

function ToggleRow({
  hint,
  label,
  onChange,
  value,
}: {
  hint: string;
  label: string;
  onChange: (value: boolean) => void;
  value: boolean;
}) {
  return (
    <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: "14px", marginBottom: "14px" }}>
      <div>
        <div>{label}</div>
        <div style={{ marginTop: "4px", color: palette.muted, fontSize: "18px" }}>{hint}</div>
      </div>
      <button
        type="button"
        onClick={() => onChange(!value)}
        style={{
          width: "52px",
          height: "28px",
          borderRadius: "999px",
          border: "none",
          background: value ? palette.success : palette.border,
          position: "relative",
          cursor: "pointer",
        }}
      >
        <span
          style={{
            position: "absolute",
            top: "4px",
            left: value ? "28px" : "4px",
            width: "20px",
            height: "20px",
            borderRadius: "999px",
            background: "#fff",
            transition: "left 120ms ease",
          }}
        />
      </button>
    </div>
  );
}

export function StrategyConfig() {
  const [settings, setSettings] = useState<StrategySettings>(DEFAULT_SETTINGS);
  const [saved, setSaved] = useState(false);
  const [dirty, setDirty] = useState(false);

  const setValue = <K extends keyof StrategySettings>(key: K, value: StrategySettings[K]) => {
    setSettings((previous) => ({ ...previous, [key]: value }));
    setSaved(false);
    setDirty(true);
  };

  const handleSave = () => {
    setSaved(true);
    setDirty(false);
  };

  const handleReset = () => {
    setSettings(DEFAULT_SETTINGS);
    setSaved(false);
    setDirty(false);
  };

  return (
    <div style={{ minHeight: "100vh", background: palette.bg, color: palette.text, padding: "24px", fontFamily: "var(--font-sans)" }}>
      <section style={{ padding: "18px 22px", background: palette.panel, border: `1px solid ${palette.border}`, marginBottom: "20px" }}>
        <div style={{ color: palette.muted, fontSize: "18px", letterSpacing: "0.14em", textTransform: "uppercase" }}>策略設定</div>
        <div style={{ marginTop: "6px", display: "flex", justifyContent: "space-between", gap: "16px", flexWrap: "wrap" }}>
          <div>
            <div style={{ fontSize: "36px", fontWeight: 700 }}>策略權重與風控參數</div>
            <div style={{ marginTop: "6px", color: palette.muted, fontSize: "24px" }}>
              目前先把設定存在頁面狀態，方便你先調整策略形狀；之後可再接 API 或本機持久化。
            </div>
          </div>
          <div style={{ display: "flex", alignItems: "center", gap: "10px", flexWrap: "wrap" }}>
            {saved && <span style={{ color: palette.success, fontSize: "18px" }}>設定已儲存</span>}
            {dirty && !saved && <span style={{ color: palette.warning, fontSize: "18px" }}>有未儲存變更</span>}
            <button
              type="button"
              onClick={handleReset}
              style={{ padding: "8px 14px", border: `1px solid ${palette.border}`, background: "rgba(255,255,255,0.05)", color: palette.text, cursor: "pointer" }}
            >
              還原預設
            </button>
            <button
              type="button"
              onClick={handleSave}
              style={{ padding: "8px 18px", border: "none", background: dirty ? palette.accent : "#3a3a3a", color: dirty ? "#000" : palette.muted, fontWeight: 700, cursor: "pointer" }}
            >
              儲存設定
            </button>
          </div>
        </div>
      </section>

      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "18px" }}>
        <div style={{ display: "grid", gap: "18px" }}>
          <Section title="訊號引擎">
            <SliderRow label="新聞事件權重" hint="事件分數越高，越容易直接放行搶快單。" value={settings.newsEventWeight} min={0} max={100} step={5} onChange={(value) => setValue("newsEventWeight", value)} format={(value) => `${value}`} />
            <SliderRow label="輿情權重" hint="用來平衡文本情緒與熱門度對決策的影響。" value={settings.sentimentWeight} min={0} max={100} step={5} onChange={(value) => setValue("sentimentWeight", value)} format={(value) => `${value}`} />
            <SliderRow label="技術面權重" hint="提高後，系統會更重視量價與突破條件。" value={settings.technicalWeight} min={0} max={100} step={5} onChange={(value) => setValue("technicalWeight", value)} format={(value) => `${value}`} />
            <SliderRow label="進場閾值" hint="分數高於此值才允許正式進場。" value={settings.entryScoreThreshold} min={20} max={95} step={5} onChange={(value) => setValue("entryScoreThreshold", value)} format={(value) => `${value} 分`} />
            <SliderRow label="接近區間高點門檻" hint="避免在區間太低的位置追價。" value={settings.nearHighRatio} min={0.8} max={0.99} step={0.01} onChange={(value) => setValue("nearHighRatio", value)} format={(value) => `${(value * 100).toFixed(0)}%`} />
            <SliderRow label="最低量比" hint="只在明顯放量時放行事件進場。" value={settings.minVolumeRatio} min={1} max={5} step={0.1} onChange={(value) => setValue("minVolumeRatio", value)} format={(value) => `${value.toFixed(1)}x`} />
          </Section>

          <Section title="模擬撮合">
            <NumberRow label="單筆進場金額" hint="單一事件單預設投入金額。" value={settings.positionSizeTwd} step={1000} suffix="元" onChange={(value) => setValue("positionSizeTwd", value)} />
            <NumberRow label="最多同時持倉" hint="限制盤中同時開啟的標的數。" value={settings.maxPositions} step={1} suffix="檔" onChange={(value) => setValue("maxPositions", value)} />
            <NumberRow label="單檔最大倉位" hint="避免資金過度集中在單一標的。" value={settings.maxSinglePosSizePct} step={1} suffix="%" onChange={(value) => setValue("maxSinglePosSizePct", value)} />
            <ToggleRow label="啟用搶快單" hint="先小部位進場，等待技術面補強再決定是否加碼。" value={settings.fastEntryEnabled} onChange={(value) => setValue("fastEntryEnabled", value)} />
            {settings.fastEntryEnabled && (
              <NumberRow label="搶快單衰減時間" hint="超過此時間，事件優勢視為明顯下降。" value={settings.fastEntryDecayMs} step={500} suffix="毫秒" onChange={(value) => setValue("fastEntryDecayMs", value)} />
            )}
          </Section>
        </div>

        <div style={{ display: "grid", gap: "18px" }}>
          <Section title="風控引擎">
            <NumberRow label="單日停損上限" hint="達到後停止新進場，只允許減碼或平倉。" value={settings.dailyLossLimitTwd} step={1000} suffix="元" onChange={(value) => setValue("dailyLossLimitTwd", value)} />
            <SliderRow label="五日滾動虧損上限" hint="防止連續失誤時繼續擴大風險。" value={settings.rolling5DayLimitPct} min={1} max={20} step={0.5} onChange={(value) => setValue("rolling5DayLimitPct", value)} format={(value) => `${value.toFixed(1)}%`} />
            <SliderRow label="追蹤停損 ATR 倍數" hint="倍數越小，停損會越積極。" value={settings.trailStopAtrMult} min={0.5} max={5} step={0.25} onChange={(value) => setValue("trailStopAtrMult", value)} format={(value) => `${value.toFixed(2)}x`} />
            <NumberRow label="ATR 週期" hint="用於追蹤停損與波動度計算。" value={settings.atrPeriod} step={1} suffix="根" onChange={(value) => setValue("atrPeriod", value)} />
            <SliderRow label="大盤熔斷門檻" hint="加權跌幅低於此值時，暫停新的做多訊號。" value={settings.marketHaltPct} min={-5} max={-0.5} step={0.1} onChange={(value) => setValue("marketHaltPct", value)} format={(value) => `${value.toFixed(1)}%`} />
          </Section>

          <Section title="交易開關">
            <ToggleRow label="允許放空" hint="開啟後才會讓空方策略進入執行層。" value={settings.allowShort} onChange={(value) => setValue("allowShort", value)} />
            <ToggleRow label="收盤自動平倉" hint="盤末將倉位收回，降低隔夜風險。" value={settings.eodAutoFlat} onChange={(value) => setValue("eodAutoFlat", value)} />
          </Section>

          <Section title="目前設定摘要">
            <div style={{ display: "grid", gap: "8px", ...mono }}>
              {[
                ["進場閾值", `${settings.entryScoreThreshold} 分`],
                ["單筆資金", `${settings.positionSizeTwd.toLocaleString()} 元`],
                ["最大持倉", `${settings.maxPositions} 檔`],
                ["單日停損", `${settings.dailyLossLimitTwd.toLocaleString()} 元`],
                ["追蹤停損", `${settings.trailStopAtrMult.toFixed(2)}x ATR`],
                ["大盤門檻", `${settings.marketHaltPct.toFixed(1)}%`],
                ["搶快單", settings.fastEntryEnabled ? `開啟 (${settings.fastEntryDecayMs}ms)` : "關閉"],
                ["放空", settings.allowShort ? "開啟" : "關閉"],
              ].map(([label, value]) => (
                <div key={label} style={{ display: "flex", justifyContent: "space-between", padding: "6px 0", borderBottom: `1px solid rgba(255,255,255,0.05)` }}>
                  <span style={{ color: palette.muted }}>{label}</span>
                  <span>{value}</span>
                </div>
              ))}
            </div>
          </Section>
        </div>
      </div>
    </div>
  );
}

