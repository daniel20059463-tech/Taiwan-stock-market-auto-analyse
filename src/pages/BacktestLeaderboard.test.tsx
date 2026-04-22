import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { BacktestLeaderboard } from "./BacktestLeaderboard";

describe("BacktestLeaderboard", () => {
  it("renders the leaderboard summary and top rows", () => {
    render(<BacktestLeaderboard />);

    expect(screen.getByText("回測排行榜")).toBeInTheDocument();
    expect(screen.getAllByText("總排名").length).toBeGreaterThan(0);
    expect(screen.getByText("1802 台玻")).toBeInTheDocument();
    expect(screen.getAllByText("4960 誠美材").length).toBeGreaterThan(0);
  });

  it("shows inactive symbols section copy", () => {
    render(<BacktestLeaderboard />);

    expect(screen.getByText("零成交清單")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "零成交清單" }));
    expect(screen.getByText(/目前這批回測中沒有出手/)).toBeInTheDocument();
  });
});
