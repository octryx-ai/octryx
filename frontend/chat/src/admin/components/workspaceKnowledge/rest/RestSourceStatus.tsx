import { useEffect, useState } from "react";
import { connectorsApi } from "../connectorsApi";
import type { SourceConnector } from "../connectorTypes";
import { TimeText } from "../../../utils/TimeText";
import { aclNotice, restStatus } from "./restSourceSample";
import type { AclState } from "./restSourceSample";
import { ACL_NOTICE_ASK, ACL_NOTICE_LINK, knowledgeSourcesAccess } from "../sourceAcl/knowledgeSourcesAccess";
import { sourceAclHref } from "../sourceLinks";
import "./rest-source.css";

// The REST lines of a source's status (`GET …/connectors/{key}`): what it reads and as whom, who finds the
// items, errors and the next sync, and the notice when restricted items are held back because the Workspace does not
// enforce source permissions.

export function RestAclNotice({ acl, workspaceId, isPlatformAdmin, newTab = false }: {
  acl: AclState | null;
  workspaceId: string;
  isPlatformAdmin: boolean;
  // In the source form: the switch opens in a new tab, so the draft stays.
  newTab?: boolean;
}) {
  const notice = aclNotice(acl);
  if (!notice) return null;
  const access = knowledgeSourcesAccess(isPlatformAdmin);
  return (
    <div className="rest-source__notice" role="note" data-testid="rest-source-acl-notice">
      <b>{notice.title}</b>
      <p>{notice.text}</p>
      <p>
        {access.aclNotice === "link" ? (
          <a className="rest-source__notice-link" href={sourceAclHref(workspaceId)} data-testid="rest-source-acl-link"
            {...(newTab ? { target: "_blank", rel: "noreferrer noopener" } : {})}>{ACL_NOTICE_LINK}</a>
        ) : ACL_NOTICE_ASK}{access.aclNotice === "link" ? "." : ""} {notice.alternative}
      </p>
    </div>
  );
}

export function RestSourceStatus({ connector, workspaceId, isPlatformAdmin }: { connector: SourceConnector; workspaceId: string; isPlatformAdmin: boolean }) {
  const [current, setCurrent] = useState<SourceConnector>(connector);
  useEffect(() => {
    setCurrent(connector);
    let active = true;
    connectorsApi.get(workspaceId, connector.connector_key)
      .then((answer) => { if (active) setCurrent(answer); })
      .catch(() => undefined); // The listing's entry is the same content; it stays shown.
    return () => { active = false; };
  }, [connector, workspaceId]);
  const status = restStatus(current as unknown as Record<string, unknown>);
  return (
    <div className="rest-source__status" data-testid="rest-source-status">
      <RestAclNotice acl={status.acl} workspaceId={workspaceId} isPlatformAdmin={isPlatformAdmin} />
      <dl className="knowledge-source__overview">
        <div><dt>Reads</dt><dd>{status.reads}</dd></div>
        <div><dt>Read as</dt><dd>{status.readAs}</dd></div>
        <div><dt>Found by</dt><dd>{status.visibility}</dd></div>
        <div><dt>Errors</dt><dd data-testid="rest-source-errors">{status.errors}</dd></div>
        <div><dt>Next sync</dt><dd>{status.nextSync ? <TimeText value={status.nextSync} mode="dateTime" /> : "Not scheduled: only Sync now syncs it"}</dd></div>
      </dl>
    </div>
  );
}
