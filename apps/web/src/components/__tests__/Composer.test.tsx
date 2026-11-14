/** @vitest-environment jsdom */
import { describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";

import Composer from "@/components/Composer";

describe("Composer", () => {
  it("sends on button click and clears the input", () => {
    const onSend = vi.fn();
    render(
      <Composer
        onSend={onSend}
        onStop={vi.fn()}
        streaming={false}
        noModel={false}
      />,
    );
    const input = screen.getByLabelText("输入消息");
    fireEvent.change(input, { target: { value: "你好" } });
    fireEvent.click(screen.getByRole("button", { name: "发送消息" }));
    expect(onSend).toHaveBeenCalledWith("你好");
    expect((input as HTMLTextAreaElement).value).toBe("");
  });

  it("send button is disabled while the input is empty", () => {
    render(
      <Composer
        onSend={vi.fn()}
        onStop={vi.fn()}
        streaming={false}
        noModel={false}
      />,
    );
    expect(
      screen.getByRole("button", { name: "发送消息" }),
    ).toHaveProperty("disabled", true);
  });

  it("Enter sends, Shift+Enter does not", () => {
    const onSend = vi.fn();
    render(
      <Composer
        onSend={onSend}
        onStop={vi.fn()}
        streaming={false}
        noModel={false}
      />,
    );
    const input = screen.getByLabelText("输入消息");
    fireEvent.change(input, { target: { value: "第一行" } });
    fireEvent.keyDown(input, { key: "Enter", shiftKey: true });
    expect(onSend).not.toHaveBeenCalled();
    fireEvent.keyDown(input, { key: "Enter", shiftKey: false });
    expect(onSend).toHaveBeenCalledWith("第一行");
  });

  it("shows Stop while streaming and calls onStop", () => {
    const onStop = vi.fn();
    render(
      <Composer
        onSend={vi.fn()}
        onStop={onStop}
        streaming={true}
        noModel={false}
      />,
    );
    expect(
      screen.queryByRole("button", { name: "发送消息" }),
    ).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "停止生成" }));
    expect(onStop).toHaveBeenCalled();
  });

  it("disables sending when no model is available", () => {
    render(
      <Composer
        onSend={vi.fn()}
        onStop={vi.fn()}
        streaming={false}
        noModel={true}
      />,
    );
    expect(screen.getByLabelText("输入消息")).toHaveProperty(
      "placeholder",
      "暂无可用模型，无法发送消息",
    );
  });
});
