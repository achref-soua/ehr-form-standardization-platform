import * as DropdownMenu from "@radix-ui/react-dropdown-menu";
import * as Tooltip from "@radix-ui/react-tooltip";
import {
  Activity,
  ArchiveX,
  BookOpenCheck,
  Boxes,
  ChevronDown,
  CircleGauge,
  Database,
  FileScan,
  GitBranch,
  HeartPulse,
  Menu,
  PanelLeftClose,
  ShieldCheck,
  Waypoints,
  X,
} from "lucide-react";
import { useState, type ReactNode } from "react";
import { Link, useLocation } from "react-router-dom";

import type { Persona, PersonaRole } from "../api/generated";

const navigation = [
  { to: "/", label: "Command center", icon: CircleGauge },
  { to: "/sources", label: "Source explorer", icon: Database },
  { to: "/forms", label: "Form registry", icon: Boxes },
  { to: "/mappings", label: "Mapping workspace", icon: GitBranch },
  { to: "/runs", label: "Pipeline runs", icon: Activity },
  { to: "/quarantine", label: "Quarantine", icon: ArchiveX },
  { to: "/documents", label: "Document lab", icon: FileScan },
  { to: "/omop", label: "OMOP explorer", icon: HeartPulse },
  { to: "/catalog", label: "Research catalog", icon: BookOpenCheck },
  { to: "/lineage", label: "Lineage", icon: Waypoints },
  { to: "/health", label: "System health", icon: ShieldCheck },
] as const;

export function Shell({
  actor,
  onPersonaChange,
  switching,
  children,
}: {
  actor: Persona;
  onPersonaChange: (persona: PersonaRole) => void;
  switching: boolean;
  children: ReactNode;
}) {
  const [mobileOpen, setMobileOpen] = useState(false);
  const location = useLocation();
  return (
    <Tooltip.Provider delayDuration={400}>
      <div className="app-shell">
        <aside
          className={`sidebar ${mobileOpen ? "sidebar-open" : ""}`}
          aria-label="Primary"
        >
          <div className="brand">
            <div className="brand-identity">
              <img
                className="brand-logo"
                src="/ehr-form-standardization-logo.png"
                alt="EHR Form Standardization — smart health"
                width="1602"
                height="487"
              />
              <span>EHR evidence control plane</span>
            </div>
            <button
              className="icon-button mobile-close"
              type="button"
              onClick={() => setMobileOpen(false)}
              aria-label="Close navigation"
            >
              <X />
            </button>
          </div>

          <nav className="nav-list">
            {navigation.map(({ to, label, icon: Icon }) => (
              <Tooltip.Root key={to}>
                <Tooltip.Trigger asChild>
                  <Link
                    to={to}
                    aria-label={label}
                    aria-current={
                      location.pathname === to ||
                      (to !== "/" && location.pathname.startsWith(`${to}/`))
                        ? "page"
                        : undefined
                    }
                    onClick={() => setMobileOpen(false)}
                    className={`nav-item ${location.pathname === to || (to !== "/" && location.pathname.startsWith(`${to}/`)) ? "active" : ""}`}
                  >
                    <Icon aria-hidden="true" />
                    <span>{label}</span>
                  </Link>
                </Tooltip.Trigger>
                <Tooltip.Portal>
                  <Tooltip.Content
                    className="tooltip"
                    side="right"
                    sideOffset={10}
                  >
                    {label}
                  </Tooltip.Content>
                </Tooltip.Portal>
              </Tooltip.Root>
            ))}
          </nav>

          <div className="sidebar-note">
            <PanelLeftClose aria-hidden="true" />
            <div>
              <strong>Bounded demonstration</strong>
              <span>Synthetic data · local processing</span>
            </div>
          </div>
        </aside>

        <div className="app-column">
          <header className="topbar">
            <button
              className="icon-button mobile-menu"
              type="button"
              onClick={() => setMobileOpen(true)}
              aria-label="Open navigation"
            >
              <Menu />
            </button>
            <div className="environment-chip">
              <span /> Demo environment
            </div>
            <div className="topbar-spacer" />
            <DropdownMenu.Root>
              <DropdownMenu.Trigger
                className="persona-trigger"
                disabled={switching}
              >
                <span className="persona-avatar">
                  {actor.display_name.slice(0, 2).toUpperCase()}
                </span>
                <span className="persona-copy">
                  <strong>{actor.display_name}</strong>
                  <small>{actor.role}</small>
                </span>
                <ChevronDown aria-hidden="true" />
              </DropdownMenu.Trigger>
              <DropdownMenu.Portal>
                <DropdownMenu.Content
                  className="persona-menu"
                  align="end"
                  sideOffset={8}
                >
                  <DropdownMenu.Label>Switch demo persona</DropdownMenu.Label>
                  {(
                    ["engineer", "steward", "researcher", "operator"] as const
                  ).map((role) => (
                    <DropdownMenu.Item
                      key={role}
                      className="persona-item"
                      onSelect={() => onPersonaChange(role)}
                    >
                      <span>{role[0]?.toUpperCase()}</span>
                      <div>
                        <strong>
                          {role[0]?.toUpperCase()}
                          {role.slice(1)}
                        </strong>
                        <small>
                          {role === "steward"
                            ? "Approve mappings"
                            : `View as ${role}`}
                        </small>
                      </div>
                    </DropdownMenu.Item>
                  ))}
                </DropdownMenu.Content>
              </DropdownMenu.Portal>
            </DropdownMenu.Root>
          </header>
          <main id="main-content" className="main-content" tabIndex={-1}>
            {children}
          </main>
        </div>
        {mobileOpen ? (
          <button
            type="button"
            className="sidebar-scrim"
            onClick={() => setMobileOpen(false)}
            aria-label="Close navigation"
          />
        ) : null}
      </div>
    </Tooltip.Provider>
  );
}
