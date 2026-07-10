import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { vi } from "vitest";
import Login from "../pages/Login";

const loginFn = vi.fn().mockResolvedValue(undefined);
vi.mock("../auth/AuthContext", () => ({ useAuth: () => ({ login: loginFn }) }));

it("submits username and password", async () => {
  render(<MemoryRouter><Login /></MemoryRouter>);
  fireEvent.change(screen.getByLabelText(/username/i), { target: { value: "jo" } });
  fireEvent.change(screen.getByLabelText(/password/i), { target: { value: "pw12345" } });
  fireEvent.click(screen.getByRole("button", { name: /log in/i }));
  await waitFor(() => expect(loginFn).toHaveBeenCalledWith("jo", "pw12345"));
});
