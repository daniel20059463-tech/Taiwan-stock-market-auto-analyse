import { fireEvent, render, screen } from "@testing-library/react";
import type { ComponentProps } from "react";
import { useState } from "react";
import { describe, expect, it, vi } from "vitest";
import type { DesktopUpdateState } from "../types/desktop";
import { DesktopUpdateBanner } from "./DesktopUpdateBanner";

function renderBanner(
  state: DesktopUpdateState,
  overrides?: Partial<ComponentProps<typeof DesktopUpdateBanner>>,
) {
  const onUpdateNow = vi.fn();
  const onDismiss = vi.fn();

  render(
    <DesktopUpdateBanner
      state={state}
      isUpdating={false}
      onUpdateNow={onUpdateNow}
      onDismiss={onDismiss}
      {...overrides}
    />,
  );

  return { onUpdateNow, onDismiss };
}

describe("DesktopUpdateBanner", () => {
  it("shows update copy and both actions when a new version is available", () => {
    renderBanner({
      status: "available",
      currentVersion: "1.0.0",
      availableVersion: "1.1.0",
    });

    expect(screen.getByText("發現新版本")).toBeInTheDocument();
    expect(
      screen.getByText("目前版本 1.0.0，可更新為 1.1.0。你可以現在更新，或稍後再說。"),
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "立即更新" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "稍後再說" })).toBeInTheDocument();
  });

  it("calls the correct handlers for update now and dismiss", () => {
    const { onUpdateNow, onDismiss } = renderBanner({
      status: "available",
      currentVersion: "1.0.0",
      availableVersion: "1.1.0",
    });

    fireEvent.click(screen.getByRole("button", { name: "立即更新" }));
    fireEvent.click(screen.getByRole("button", { name: "稍後再說" }));

    expect(onUpdateNow).toHaveBeenCalledTimes(1);
    expect(onDismiss).toHaveBeenCalledTimes(1);
  });

  it("hides when the wrapper dismisses the banner", () => {
    function Wrapper() {
      const [state, setState] = useState<DesktopUpdateState>({
        status: "available",
        currentVersion: "1.0.0",
        availableVersion: "1.1.0",
      });

      return (
        <DesktopUpdateBanner
          state={state}
          isUpdating={false}
          onUpdateNow={vi.fn()}
          onDismiss={() => setState((current) => ({ ...current, status: "dismissed" }))}
        />
      );
    }

    render(<Wrapper />);

    fireEvent.click(screen.getByRole("button", { name: "稍後再說" }));

    expect(screen.queryByText("發現新版本")).not.toBeInTheDocument();
  });
});
