// @vitest-environment jsdom

import {act, cleanup, render, screen} from "@testing-library/react";
import "@testing-library/jest-dom/vitest";
import {afterEach, describe, expect, it, vi} from "vitest";
import {useDebouncedValue} from "./useDebouncedValue";

function Probe({value}: {value: string}) {
  return <output>{useDebouncedValue(value, 250)}</output>;
}

afterEach(() => {
  cleanup();
  vi.useRealTimers();
});

describe("useDebouncedValue", () => {
  it("publishes only the latest value after the quiet period", () => {
    vi.useFakeTimers();
    const view = render(<Probe value="initial" />);

    view.rerender(<Probe value="first" />);
    view.rerender(<Probe value="latest" />);
    act(() => vi.advanceTimersByTime(249));
    expect(screen.getByText("initial")).toBeInTheDocument();

    act(() => vi.advanceTimersByTime(1));
    expect(screen.getByText("latest")).toBeInTheDocument();
    expect(screen.queryByText("first")).not.toBeInTheDocument();
  });
});
