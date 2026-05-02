import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { BacktestLeaderboard } from "./BacktestLeaderboard";

describe("BacktestLeaderboard", () => {
  it("renders the leaderboard summary and top rows", () => {
    render(<BacktestLeaderboard />);

    expect(screen.getByText("回測排行榜")).toBeInTheDocument();
    expect(screen.getByText("1802 台玻")).toBeInTheDocument();
    expect(screen.getAllByText(/4960 誠美材/).length).toBeGreaterThan(0);
  });

  it("shows inactive symbols when inactive tab is selected", () => {
    render(<BacktestLeaderboard />);

    fireEvent.click(screen.getByRole("button", { name: "零成交" }));
    expect(screen.getAllByText("3231 緯創").length).toBeGreaterThan(0);
  });
});
