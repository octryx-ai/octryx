---
title: REST APIs
---

Any REST API can become read tools for agents without code. Octryx decides who may call which operation, on which data.

### What you do here
- Add a REST API: import its OpenAPI 3 or Swagger 2 description (paste it or give a URL), or enter it by hand.
- Open an API to enable operations, describe them for the model, grant them to roles and limit each grant to its data.
- Add a connection: the base URL and the technical account the API is called with.
- Run a test call to see what a person with your roles would get.

### Next steps
- [See the calls](/chat?area=admin&tab=restApiCalls)
- [Open MCP servers](/chat?area=admin&tab=mcp)

### How access works
The API is called with one technical account, which often sees more than the person asking. So every operation has
**grants**: a role (a platform role, or a work-role key the person holds in the Workspace), optionally limited to one
Workspace. An operation without grants is offered to nobody, even when it is enabled.

### Data scope
A grant can fix parameter values (for example `assignment_group = G1`). Octryx sets them last on every call and refuses
a call that asks for another value. A fixed value only works if the API honours it, so add a **result filter**
(`field = value`) as well: records outside it are dropped and counted.

### Imported operations stay off
An import never enables anything. Each operation stays off until you enable it and grant it to a role.

### Writes
A write is anything but GET and HEAD, or a POST you mark as a read-only search. Writes are offered like reads, but every
write waits for an approval: in a chat the write plan, in a workflow the approval with the exact request. Runs without a
person always ask. A write needs a run class: **Deliver** (the default) lets only runs that may write to other systems
call it; **Change** lets runs that may change things call it too. A PUT or DELETE can be marked safe to repeat; a POST
or PATCH is never sent twice. A grant's **body scope** fixes fields of the request body (for example
`assignment_group = G1`); a body naming another value there is refused. Test calls run reads only. Under Calls, each
write names the approval or write plan that admitted it.

### SAP and OData
An OData document is recognized on import. Its collection reads get a template that says where the records and the
next page are: OData v2 (`d.results`, next page from `d.__next`), OData v2 paged with `$skip` and `$top`, or OData v4
(`value`, next page from `@odata.nextLink`). Change it per operation under Setup, or for all collection reads right
after the import. OData options such as `$select` are offered to the model as `select` and sent as `$select`; the
editor and the test call show both names. A list such as `select` is typed with commas in the test call.

With writes and authentication the import also turns on **Fetch a CSRF token before writes** (Details), as SAP
Gateway needs. A `$batch` operation is shown as not supported and cannot be enabled: a batch would carry several
requests past the per-call grants and audit. Enable the single operations instead.

Under Calls, filter by API and operation; an API's Details and each operation link to their calls.

### Connections
One connection for the platform and, if needed, one per Workspace. A Workspace's own connection wins over the platform
one for calls in that Workspace. Secrets are write-only: the page shows whether one is set, and lets you replace or
clear it.

### Deleting
Deleting an API also removes its operations and connections and releases their secrets. The audit of its calls stays.

### Local and internal addresses
A REST API on `localhost` or another loopback, link-local or cloud-metadata address is always refused: the call never
leaves Octryx (protection against server-side request forgery). An API in your own network needs its `host:port` on
the private-host allowlist.
