import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";
import { AppShell } from "./AppShell";

describe("AppShell", () => {
  it("renders clean Chinese navigation labels", () => {
    render(
      <MemoryRouter initialEntries={["/"]}>
        <AppShell>
          <div>測試內容</div>
        </AppShell>
      </MemoryRouter>,
    );

    expect(screen.getByText("盤中總控台")).toBeInTheDocument();
    expect(screen.getByText("策略作戰台")).toBeInTheDocument();
    expect(screen.getByText("交易回放")).toBeInTheDocument();
    expect(screen.getByText("績效分析")).toBeInTheDocument();
    expect(screen.getByText("策略設定")).toBeInTheDocument();
    expect(screen.queryByText("Alpha Radar")).not.toBeInTheDocument();
    expect(screen.queryByText("Paper Trading")).not.toBeInTheDocument();
  });

  it("renders an optional top banner above the page content", () => {
    render(
      <MemoryRouter initialEntries={["/"]}>
        <AppShell topBanner={<div>desktop banner</div>}>
          <div>main content</div>
        </AppShell>
      </MemoryRouter>,
    );

    expect(screen.getByText("desktop banner")).toBeInTheDocument();
    expect(screen.getByText("main content")).toBeInTheDocument();
  });
});
