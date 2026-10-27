import type { Metadata } from "next";
import WorkspaceShell from "./WorkspaceShell";
import "./globals.css";

export const metadata: Metadata = {
  title: "Capacity Connect",
  description: "A competency-driven capacity-building platform.",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en">
      <body>
        <WorkspaceShell>{children}</WorkspaceShell>
      </body>
    </html>
  );
}
