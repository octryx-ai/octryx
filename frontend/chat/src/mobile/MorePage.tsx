// More: who is signed in on this phone, the phone's notifications, the person's Macs and signing the phone out.

import type { ReactNode } from "react";
import { workspaceInitials } from "../chat/workspace/globalWorkspaceModel";
import { Icon, type IconName } from "./icons";
import type { PhoneSession } from "./mobileSession";
import { untilDate } from "./mobileUsageModel";
import { TabHeader } from "./PageHeader";
import { PushSettings } from "./PushSettings";

export type MoreLink = { key: string; label: string; detail: string; icon: IconName; onOpen: () => void };

export function MorePage({
  session,
  links,
  onSignOut,
}: {
  session: PhoneSession;
  links: MoreLink[];
  onSignOut: () => void;
}) {
  return (
    <>
      <TabHeader title="More" />
      <main className="m-body">
        <section className="m-account" aria-label="Signed in">
          <span className="m-avatar" aria-hidden="true">
            {workspaceInitials(session.user.name)}
          </span>
          <span className="m-account-text">
            <b>{session.user.name}</b>
            <span>
              {session.device.name} · signed in until {untilDate(session.device.login_expires_at)}
            </span>
          </span>
        </section>
        {links.length > 0 && (
          <ul className="m-rows m-group">
            {links.map((link) => (
              <li key={link.key}>
                <MoreRow icon={link.icon} label={link.label} detail={link.detail} onClick={link.onOpen} />
              </li>
            ))}
          </ul>
        )}
        <PushSettings />
        <button type="button" className="m-danger m-full" onClick={onSignOut}>
          <Icon name="signOut" size={20} />
          Sign out this phone
        </button>
      </main>
    </>
  );
}

function MoreRow({ icon, label, detail, onClick }: { icon: IconName; label: string; detail: ReactNode; onClick: () => void }) {
  return (
    <button type="button" className="m-row m-row-icon" onClick={onClick}>
      <span className="m-row-glyph" aria-hidden="true">
        <Icon name={icon} size={20} />
      </span>
      <span className="m-row-text">
        <b>{label}</b>
        <span>{detail}</span>
      </span>
      <Icon name="chevronRight" size={18} className="m-row-chevron" />
    </button>
  );
}
