/** @vitest-environment jsdom */
import { describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";

import MessageBubble from "@/components/MessageBubble";
import type { ChatMessage } from "@/lib/types";

function assistantMessage(content: string): ChatMessage {
  return {
    id: 1,
    role: "assistant",
    content,
    model: "gpt-5.4-mini",
    tokens_in: 5,
    tokens_out: 8,
    created_at: null,
  };
}

describe("MessageBubble", () => {
  it("renders assistant Markdown (GFM) with code block + copy button", () => {
    render(
      <MessageBubble
        message={assistantMessage(
          "下面是代码：\n\n```js\nconst a = 1;\n```\n\n- 列表项一\n- 列表项二",
        )}
      />,
    );
    expect(screen.getByText("下面是代码：")).toBeTruthy();
    expect(screen.getByText("列表项一")).toBeTruthy();
    expect(document.querySelector("pre code")?.textContent).toContain(
      "const a = 1;",
    );
    expect(
      screen.getByRole("button", { name: "复制代码" }),
    ).toBeTruthy();
  });

  it("shows token counts when known and 未获取 when unknown", () => {
    const { rerender } = render(
      <MessageBubble message={assistantMessage("hi")} />,
    );
    expect(screen.getByText("输入 5 · 输出 8 tokens")).toBeTruthy();
    rerender(
      <MessageBubble
        message={{
          ...assistantMessage("hi"),
          tokens_in: null,
          tokens_out: null,
        }}
      />,
    );
    expect(screen.getByText("Token：未获取")).toBeTruthy();
  });

  it("copy button attempts clipboard write with the code text", async () => {
    const writeText = vi.fn(async (text: string) => {
      void text;
    });
    Object.assign(navigator, { clipboard: { writeText } });
    render(
      <MessageBubble
        message={assistantMessage("```\nhello code\n```")}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: "复制代码" }));
    await vi.waitFor(() => expect(writeText).toHaveBeenCalled());
    expect(writeText.mock.calls[0]?.[0]).toContain("hello code");
    await vi.waitFor(() =>
      expect(screen.getByText("已复制")).toBeTruthy(),
    );
  });

  it("user messages render as plain text with an edit button", () => {
    const onEdit = vi.fn();
    render(
      <MessageBubble
        message={{
          id: 2,
          role: "user",
          content: "请解释",
          model: null,
          tokens_in: null,
          tokens_out: null,
          created_at: null,
        }}
        onEdit={onEdit}
      />,
    );
    expect(screen.getByText("请解释")).toBeTruthy();
    fireEvent.click(screen.getByText("编辑"));
    fireEvent.change(screen.getByLabelText("编辑消息"), {
      target: { value: "请详细解释" },
    });
    fireEvent.click(screen.getByText("保存并重新发送"));
    expect(onEdit).toHaveBeenCalledWith("请详细解释");
  });
});
