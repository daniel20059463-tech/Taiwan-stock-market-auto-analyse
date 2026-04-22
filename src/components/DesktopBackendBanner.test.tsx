import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { DesktopBackendBanner } from "./DesktopBackendBanner";

describe("DesktopBackendBanner", () => {
  it("renders nothing while backend is running", () => {
    const { container } = render(
      <DesktopBackendBanner
        status={{ phase: "running", detail: "ready" }}
        isRetrying={false}
        onRetry={vi.fn()}
      />,
    );

    expect(container).toBeEmptyDOMElement();
  });

  it("shows a retry button for error state and calls retry", () => {
    const onRetry = vi.fn();

    render(
      <DesktopBackendBanner
        status={{ phase: "error", detail: "backend crashed" }}
        isRetrying={false}
        onRetry={onRetry}
      />,
    );

    expect(screen.getByText("backend crashed")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "重試" }));

    expect(onRetry).toHaveBeenCalledTimes(1);
  });

  it("shows a passive status message while backend is starting", () => {
    render(
      <DesktopBackendBanner
        status={{ phase: "starting" }}
        isRetrying={false}
        onRetry={vi.fn()}
      />,
    );

    expect(screen.getByText("桌面後端啟動中")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "重試" })).not.toBeInTheDocument();
  });
});
