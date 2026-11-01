import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { describe, it, expect, vi } from "vitest";
import { CopyIdButton } from "./CopyIdButton";

describe("CopyIdButton", () => {
  it("tıklayınca oturum kimliğini panoya yazar", async () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.defineProperty(navigator, "clipboard", { value: { writeText }, configurable: true });
    render(<CopyIdButton id="b927090d4eba" />);
    fireEvent.click(screen.getByRole("button", { name: "Oturum kimliğini kopyala" }));
    await waitFor(() => expect(writeText).toHaveBeenCalledWith("b927090d4eba"));
    await waitFor(() => expect(screen.getByRole("button").title).toBe("Kopyalandı"));
  });
});
